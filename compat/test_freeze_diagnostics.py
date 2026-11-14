"""Exercise the watchdog without a game session or access to the network."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from freeze_diagnostics import Diagnostics, FIELDS, classify


def heartbeat(**changes):
    row = dict.fromkeys(FIELDS, 0)
    row.update(raf=50, ticks=50, logic=20, submits=20, gl=1, visible=True, playing=True)
    row.update(changes)
    return row


class WatchdogTests(unittest.TestCase):
    def test_distinguishes_logic_render_wasm_and_gpu(self):
        old = heartbeat()
        cases = (
            (heartbeat(raf=70, ticks=70, submits=40), 'A-logic-frames-stopped'),
            (heartbeat(raf=70, ticks=70, logic=40), 'B-render-not-returning'),
            (heartbeat(raf=70), 'C-wasm-tick-not-returning'),
            (heartbeat(gl=2), 'D-webgl-context'),
            (heartbeat(fenceAgeMs=8000), 'D-gpu-fence-timeout'),
            (heartbeat(raf=70, ticks=70, logic=40, submits=40), None),
            (heartbeat(raf=70, ticks=70, playing=False), None),
        )
        for new, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(classify(old, new, 0), reason)

    def test_missing_and_background_heartbeats(self):
        self.assertEqual(classify(None, heartbeat(), 13), 'C-heartbeat-timeout')
        self.assertIsNone(classify(None, heartbeat(visible=False), 13))

    def test_watchdog_captures_once_and_keeps_first_error(self):
        diagnostics = Diagnostics()
        self.assertFalse(diagnostics.add('a', heartbeat(secret='invalid')))
        with patch('freeze_diagnostics.time.monotonic', return_value=10):
            self.assertTrue(diagnostics.add('a', heartbeat()))
        self.assertIsNone(diagnostics.poll(21.9))
        self.assertEqual(diagnostics.poll(22.1), 'C-heartbeat-timeout')
        self.assertIsNone(diagnostics.poll(23))
        diagnostics.mark_fatal('other-session')
        self.assertIsNone(diagnostics.poll(30))
        diagnostics.mark_fatal('a')
        self.assertEqual(diagnostics.poll(31), 'fatal-error')

    def test_local_snapshot_written_before_sampling(self):
        diagnostics = Diagnostics()
        diagnostics.add('secret-session', heartbeat())
        with tempfile.TemporaryDirectory() as directory:
            def verify_initial_snapshot(_pid):
                paths = list(Path(directory).rglob('freeze.json'))
                self.assertEqual(len(paths), 1)
                body = paths[0].read_text()
                self.assertNotIn('secret-session', body)
                self.assertEqual(json.loads(body)['heartbeats'][-1]['logic'], 20)
                return []

            with patch('freeze_diagnostics.Path.home', return_value=Path(directory)), patch(
                'freeze_diagnostics.owned_processes', side_effect=verify_initial_snapshot,
            ):
                diagnostics.capture('fatal-error', 123, 'on', 0, lambda: {'critical': []})
                diagnostics.checkpoint('on', 0, lambda: {'wasm_capacity': []})
                diagnostics.checkpoint('off', 0, lambda: {'wasm_capacity': []})
            self.assertEqual(diagnostics.last_snapshot['reason'], 'fatal-error')
            self.assertEqual(
                {path.name for path in Path(directory).rglob('latest-*.json')},
                {'latest-reclaim-on.json', 'latest-reclaim-off.json'},
            )


if __name__ == '__main__':
    unittest.main()
