"""Bounded, loopback-only heartbeat history and macOS freeze snapshots."""

import ctypes
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time


FIELDS = {
    'raf', 'ticks', 'logic', 'frame', 'submits', 'gcObjects', 'movieLibraries',
    'collections', 'phase', 'tickMaxMs', 'logicMaxMs', 'renderMaxMs', 'reclaimMaxMs', 'gl', 'fenceDone',
    'fenceAgeMs', 'contextLosses', 'allocatedBytes', 'librarySwfBytes', 'bitmapPixelBytes',
}
FLAGS = {'playing', 'visible'}
RECLAIM_FIELDS = {'reclaimHeapBefore', 'reclaimHeapAfter', 'reclaimBitmapBefore', 'reclaimBitmapAfter'}
BITMAP_DISPOSAL_FIELDS = {'bitmapDisposeCalls', 'bitmapDisposedMiB'}
BITMAP_ORIGIN_FIELDS = {'bitmapGeneratedBytes', 'bitmapEmbeddedBytes',
                        'bitmapSuppliedBytes', 'bitmapCopyOnWriteBytes'}


def classify(old, new, gap):
    if not new['visible']:
        return None
    if gap >= 12:
        return 'C-heartbeat-timeout'
    if new['gl'] in (2, 3):
        return 'D-webgl-context'
    if new['fenceAgeMs'] >= 8000:
        return 'D-gpu-fence-timeout'
    if not old or not new['playing'] or not old['playing'] or not old['logic']:
        return None
    if new['raf'] == old['raf']:
        return 'D-animation-callback-stopped'
    if new['ticks'] == old['ticks']:
        return 'C-wasm-tick-not-returning'
    if new['logic'] > old['logic'] and new['submits'] == old['submits']:
        return 'B-render-not-returning'
    if new['logic'] == old['logic'] and new['submits'] > old['submits']:
        return 'A-logic-frames-stopped'
    if new['logic'] == old['logic'] and new['submits'] == old['submits']:
        return 'A-or-B-no-frame-progress'
    return None


def owned_processes(parent):
    # WebKit XPC processes are reparented to launchd. Only sample processes
    # macOS attributes to this App, never another browser's WebContent process.
    try:
        owner = ctypes.CDLL('/usr/lib/libSystem.B.dylib').responsibility_get_pid_responsible_for_pid
        owner.argtypes = [ctypes.c_int]
        owner.restype = ctypes.c_int
    except (OSError, AttributeError):
        owner = lambda _pid: -1
    output = subprocess.check_output(
        ['/bin/ps', '-axo', 'pid=,uid=,state=,pcpu=,rss=,comm='], text=True, timeout=4,
    )
    rows = []
    for line in output.splitlines():
        pid, uid, state, cpu, rss, command = line.split(None, 5)
        pid = int(pid)
        if int(uid) != os.getuid():
            continue
        if pid == parent and Path(command).name == 'SJSJNative':
            role = 'app'
        elif command.startswith('/System/Library/Frameworks/WebKit.framework/') and owner(pid) == parent:
            binary = Path(command).name
            if binary.startswith('com.apple.WebKit.WebContent'):
                role = 'webcontent'
            elif binary == 'com.apple.WebKit.GPU':
                role = 'gpu'
            else:
                continue
        else:
            continue
        rows.append(dict(pid=pid, role=role, state=state, cpu_percent=float(cpu), rss_kib=int(rss)))
    return sorted(rows, key=lambda row: (row['role'], -row['rss_kib']))


def sample_process(row, directory):
    path = directory / f"{row['role']}-{row['pid']}.sample.txt"
    try:
        proc = subprocess.run(
            ['/usr/bin/sample', str(row['pid']), '1', '10', '-file', str(path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=8,
        )
        if proc.returncode == 0:
            return path.name
        return f"unavailable (sample exited {proc.returncode})"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f'unavailable ({type(exc).__name__})'


class Diagnostics:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows = deque(maxlen=2400)
        self.session = None
        self.pending = None
        self.last_snapshot = None
        self.last_reason = None
        self.capture_count = 0
        self.last_capture = float('-inf')

    def add(self, session, data):
        if not isinstance(data, dict) or set(data) not in (
            FIELDS | FLAGS,
            FIELDS | FLAGS | RECLAIM_FIELDS,
            FIELDS | FLAGS | RECLAIM_FIELDS | BITMAP_DISPOSAL_FIELDS,
            FIELDS | FLAGS | RECLAIM_FIELDS | BITMAP_DISPOSAL_FIELDS | BITMAP_ORIGIN_FIELDS,
            FIELDS | FLAGS | RECLAIM_FIELDS | BITMAP_DISPOSAL_FIELDS | BITMAP_ORIGIN_FIELDS | {'bitmapPackMaxMs'},
        ):
            return False
        if any(type(data[key]) is not bool for key in FLAGS):
            return False
        if any(
            type(data[key]) not in (int, float) or not 0 <= data[key] <= 2**53
            or not math.isfinite(data[key]) for key in data.keys() - FLAGS
        ):
            return False
        now = time.monotonic()
        with self.lock:
            if session != self.session:
                self.rows.clear()
                self.session = session
                self.pending = None
                self.last_reason = None
            self.rows.append((now, dict(data)))
        return True

    def mark_fatal(self, session):
        with self.lock:
            if session == self.session:
                self.pending = 'fatal-error'

    def recent(self, started):
        with self.lock:
            return [dict(row, elapsed_seconds=round(at - started, 3)) for at, row in self.rows]

    def poll(self, now):
        with self.lock:
            if not self.rows:
                return None
            at, latest = self.rows[-1]
            old = next((row for t, row in reversed(self.rows) if t <= at - 12), None)
            reason = self.pending or classify(old, latest, now - at)
            if not reason:
                self.last_reason = None
                return None
            if self.last_reason == reason or self.capture_count >= 8:
                return None
            if now - self.last_capture < (5 if self.pending else 60):
                return None
            self.pending = None
            self.last_reason = reason
            self.last_capture = now
            self.capture_count += 1
            return reason

    def watch(self, parent, mode, started, get_context):
        checkpoint_due = time.monotonic() + 30
        while True:
            time.sleep(1)
            now = time.monotonic()
            reason = self.poll(now)
            try:
                if reason is not None:
                    self.capture(reason, parent, mode, started, get_context)
                if now >= checkpoint_due:
                    checkpoint_due = now + 30
                    self.checkpoint(mode, started, get_context)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                with self.lock:
                    if reason is not None and self.last_snapshot is None:
                        self.last_snapshot = {'error': type(exc).__name__, 'reason': reason}

    def checkpoint(self, mode, started, get_context):
        history = self.recent(started)
        if not history:
            return
        folder = Path.home() / 'Library/Logs/SJSJFreezeDiagnostics'
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = folder / f'latest-reclaim-{mode}.json'
        temporary = path.with_suffix('.tmp')
        snapshot = {
            'mode': mode, 'captured_at': datetime.now().astimezone().isoformat(),
            'heartbeats': history, **get_context(),
        }
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)

    def capture(self, reason, parent, mode, started, get_context):
        folder = Path.home() / 'Library/Logs/SJSJFreezeDiagnostics'
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory = folder / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        directory.mkdir(mode=0o700)
        snapshot = {
            'reason': reason, 'mode': mode, 'captured_at': datetime.now().astimezone().isoformat(),
            'heartbeats': self.recent(started), **get_context(),
        }
        path = directory / 'freeze.json'
        # Persist the evidence before running any external sampling commands.
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
        with self.lock:
            self.last_snapshot = {'directory': str(directory), 'reason': reason}
        processes = owned_processes(parent) if parent else []
        snapshot['processes'] = processes
        selected = [
            row for role in ('app', 'webcontent', 'gpu')
            for row in [next((item for item in processes if item['role'] == role), None)]
            if row is not None
        ]
        with ThreadPoolExecutor(max_workers=3) as executor:
            samples = executor.map(lambda row: sample_process(row, directory), selected)
            for row, sample in zip(selected, samples):
                row['stack_sample'] = sample
        try:
            pressure = subprocess.run(
                ['/usr/bin/memory_pressure', '-Q'], capture_output=True, text=True, timeout=4,
            )
            if pressure.returncode == 0:
                snapshot['system_memory_pressure'] = pressure.stdout
        except (OSError, subprocess.TimeoutExpired):
            pass
        webcontent = next((row for row in selected if row['role'] == 'webcontent'), None)
        if webcontent:
            try:
                output = subprocess.check_output(
                    ['/usr/bin/vmmap', '-summary', str(webcontent['pid'])],
                    stderr=subprocess.DEVNULL, text=True, timeout=5,
                )
                webcontent['footprint'] = [
                    line.strip() for line in output.splitlines() if line.startswith('Physical footprint')
                ]
            except (OSError, subprocess.SubprocessError):
                pass
        temporary = directory / 'freeze.json.tmp'
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
