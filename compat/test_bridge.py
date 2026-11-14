"""Check byte-for-byte passthrough with controlled and public HTTP responses."""
import hashlib
import io
import json
import os
import socket
import sqlite3
import sys
import threading
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

os.environ.setdefault('SJSJ_BRIDGE_KEY', 'local-test-only')
import bridge_server as bridge

REAL_FETCH = bridge.fetch
HOST = 'sjsj-client.wanwan4399.com'


class BridgeTests(unittest.TestCase):
    def setUp(self):
        bridge.CACHE.clear()
        bridge.EVENTS.clear()
        bridge.CRITICAL_EVENTS.clear()
        bridge.MEMORY_SAMPLES.clear()
        bridge.SESSIONS['test'] = {'sockets': []}
        self.server = bridge.ThreadingHTTPServer(('127.0.0.1', 0), bridge.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.local = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def proxy(self, path):
        with urlopen(f'{self.local}/proxy/test/http/{HOST}{path}', timeout=40) as response:
            return response.read()

    def test_runtime_mime_types_without_system_lookup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = root / 'web-runtime'
            runtime.mkdir()
            for filename in ('ruffle.js', 'core.wasm'):
                (runtime / filename).write_bytes(b'fixture')
            with patch.object(bridge, 'ROOT', root):
                for filename, content_type in (
                    ('ruffle.js', 'text/javascript'),
                    ('core.wasm', 'application/wasm'),
                ):
                    with urlopen(f'{self.local}/runtime/{filename}', timeout=5) as response:
                        self.assertEqual(response.headers.get_content_type(), content_type)
                        self.assertEqual(response.read(), b'fixture')

    def test_all_former_patch_routes_are_passthrough(self):
        paths = (
            '/www_sjsj/main_2_379_0_143824.swf',
            '/www_sjsj/sj_include_2_379_0_143824.swf',
            '/www_sjsj/sj_code_2_379_0_143824.swf',
            '/www_sjsj/resource/moduleRes/RoomCommonResource_a18a19a85e0ef543120ed3b3442b26c0.swf',
            '/www_sjsj_s2/resource/moduleRes/BackPackPanel_df5e90b42541ded6d1501b72ed2cc862.swf',
            '/www_sjsj_s2/newInterface_2_379_0_143824.swf',
        )
        for path in paths:
            with self.subTest(path=path):
                payload = b'CWS\x00' + path.encode()
                upstream = io.BytesIO(payload)
                upstream.headers = {'Content-Type': 'application/x-shockwave-flash'}
                with patch.object(bridge, 'fetch', return_value=upstream) as fetch:
                    self.assertEqual(self.proxy(path), payload)
                    self.assertEqual(self.proxy(path), payload)
                    fetch.assert_called_once()

    def test_diagnostics_and_socket_checks_still_require_authorization(self):
        with self.assertRaises(HTTPError) as denied:
            urlopen(self.local + '/diagnostics/patches')
        self.assertEqual(denied.exception.code, 403)
        with urlopen(Request(self.local + '/diagnostics/patches',
                             headers={'Authorization': 'Bearer ' + bridge.KEY})) as response:
            self.assertIn(b'"mode": "original"', response.read())
        with self.assertRaises(HTTPError) as denied:
            urlopen(self.local + '/socket/test?host=sjsj-client.wanwan4399.com&port=1')
        self.assertEqual(denied.exception.code, 403)

    def test_versioned_dynamic_assets_reuse_public_bytes(self):
        path = '/www_sjsj/2026111300/resource/dynamic/3450637561'

        def upstream(url, **_):
            response = io.BytesIO(b'original asset bytes')
            response.status = 200
            response.geturl = lambda: url
            response.headers = {
                'Content-Type': 'application/octet-stream',
                'Cache-Control': 'max-age=3600',
            }
            return response

        with tempfile.TemporaryDirectory() as folder, patch.object(Path, 'home', return_value=Path(folder)), \
                patch.object(bridge, 'fetch', side_effect=upstream) as fetch:
            self.assertEqual(self.proxy(path), b'original asset bytes')
            bridge.CACHE.clear()
            self.assertEqual(self.proxy(path), b'original asset bytes')
            fetch.assert_called_once()
            self.proxy(path + '?v=2026111301')
            self.proxy(path + '?v=2026111301')
            self.proxy(path + '?test=1')
            self.proxy(path + '?test=1')
            self.assertEqual(fetch.call_count, 4)

    def test_resource_cache_expiry_and_size_limit(self):
        with patch.object(bridge, 'RESOURCE_CACHE_BYTES', 5):
            bridge.cache_resource('first', b'aaa', 'test')
            bridge.cache_resource('second', b'bbb', 'test')
            self.assertIsNone(bridge.cached_resource('first'))
            self.assertEqual(bridge.cached_resource('second'), (b'bbb', 'test'))
        bridge.cache_resource('expired', b'aaa', 'test', ttl=0)
        self.assertIsNone(bridge.cached_resource('expired'))
        self.assertIsNone(bridge.dynamic_asset_ttl({'Cache-Control': 'private, max-age=3600'}))
        self.assertEqual(bridge.dynamic_asset_ttl({'Cache-Control': 'max-age=3600', 'Age': '120'}), 3480)

    def test_expired_public_assets_revalidate_or_replace(self):
        for path, header, value, conditional in (
            ('/www_sjsj/2026111300/resource/dynamic/3450637561',
             'ETag', '"old"', 'If-None-Match'),
            ('/www_sjsj_s2/2026111300/Loading_test.swf',
             'Last-Modified', 'Fri, 13 Nov 2026 10:00:00 GMT', 'If-Modified-Since'),
        ):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as folder, \
                    patch.object(Path, 'home', return_value=Path(folder)):
                database = Path(folder) / 'Library/Caches/SJSJPublicAssets/assets.sqlite3'
                url = 'http://' + HOST + path

                def expire():
                    with sqlite3.connect(database) as db:
                        db.execute('UPDATE assets SET expires=expires-3601')
                        db.execute('UPDATE asset_validators SET expires=expires-3601')

                def downloaded(body):
                    response = io.BytesIO(body)
                    response.status = 200
                    response.geturl = lambda: url
                    response.headers = {'Cache-Control': 'max-age=3600', header: value}
                    return response

                with patch.object(bridge, 'fetch', side_effect=[
                    downloaded(b'CWS original'),
                    HTTPError(url, 304, 'Not Modified', {}, io.BytesIO()),
                    downloaded(b'CWS updated'),
                ]) as fetch:
                    self.assertEqual(self.proxy(path), b'CWS original')
                    expire()
                    self.assertEqual(self.proxy(path), b'CWS original')
                    self.assertEqual(fetch.call_args.kwargs['extra_headers'], {conditional: value})
                    self.assertEqual(self.proxy(path), b'CWS original')
                    self.assertEqual(fetch.call_count, 2)
                    expire()
                    self.assertEqual(self.proxy(path), b'CWS updated')
                    self.assertEqual(self.proxy(path), b'CWS updated')
                    self.assertEqual(fetch.call_count, 3)

    def test_socket_upgrade_forwards_original_bytes(self):
        bridge.SESSIONS['test']['sockets'] = [(HOST, 12345)]
        remote, game = socket.socketpair()
        with remote, game, socket.socket() as browser:
            game.settimeout(2)
            browser.settimeout(2)
            browser.connect(self.server.server_address)
            with patch.object(bridge.socket, 'create_connection', return_value=remote), browser.makefile('rb') as wire:
                browser.sendall((
                    f'GET /socket/test?host={HOST}&port=12345 HTTP/1.1\r\n'
                    f'Host: 127.0.0.1:{self.server.server_port}\r\n'
                    f'Origin: {self.local}\r\n'
                    'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                    'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n'
                ).encode())
                self.assertIn(b'101', wire.readline())
                headers = []
                while (line := wire.readline()) not in (b'\r\n', b''):
                    headers.append(line)
                self.assertIn(b'Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n', headers)
                browser.sendall(b'\x82\x83abcd' + bytes(a ^ b for a, b in zip(b'abc', b'abc')))
                self.assertEqual(game.makefile('rb').read(3), b'abc')
                game.sendall(b'def')
                self.assertEqual(wire.read(5), b'\x82\x03def')
                browser.sendall(b'\x88\x80abcd')

    def test_critical_diagnostics_survive_recent_event_rollover(self):
        with urlopen(Request(
            self.local + '/report/test',
            data=b'critical: synthetic error at http://127.0.0.1/example?token=example',
        )) as response:
            self.assertEqual(response.status, 200)
        with patch('builtins.print'):
            for _ in range(170):
                bridge.event('player', message='routine')
        endpoint = self.local + '/diagnostics/critical'
        with self.assertRaises(HTTPError) as denied:
            urlopen(endpoint)
        self.assertEqual(denied.exception.code, 403)
        with urlopen(Request(endpoint, headers={'Authorization': 'Bearer ' + bridge.KEY})) as response:
            rows = json.load(response)
            self.assertGreaterEqual(rows[0].pop('elapsed_seconds'), 0)
            self.assertEqual(rows, [{
                'kind': 'player',
                'message': 'critical: synthetic error at http://127.0.0.1/example',
            }])

    def test_memory_diagnostics_survive_recent_event_rollover(self):
        with urlopen(Request(self.local + '/report/test', data=b'wasm-memory 4194304')) as response:
            self.assertEqual(response.status, 200)
        with patch('builtins.print'):
            for _ in range(170):
                bridge.event('player', message='routine')
        endpoint = self.local + '/diagnostics/memory'
        with self.assertRaises(HTTPError) as denied:
            urlopen(endpoint)
        self.assertEqual(denied.exception.code, 403)
        with urlopen(Request(endpoint, headers={'Authorization': 'Bearer ' + bridge.KEY})) as response:
            rows = json.load(response)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['wasm_bytes'], 4194304)
            self.assertGreaterEqual(rows[0]['elapsed_seconds'], 0)

    @unittest.skipUnless('--public-assets' in sys.argv, 'public HTTP comparison disabled')
    def test_public_loading_movie_bytes_for_both_realms(self):
        for realm in ('www_sjsj', 'www_sjsj_s2'):
            with self.subTest(realm=realm):
                origin = f'http://{HOST}'
                settings = bridge.settings(f'{origin}/{realm}/game.html')
                self.assertTrue(settings['sockets'])
                path = settings['movie'][len(origin):]
                with REAL_FETCH(settings['movie']) as response:
                    upstream = response.read()
                self.assertEqual(upstream[:3], b'CWS')
                self.assertEqual(self.proxy(path), upstream)
                self.assertEqual(self.proxy(path), upstream)
                print(realm, len(upstream), hashlib.sha256(upstream).hexdigest())


if __name__ == '__main__':
    unittest.main(argv=[arg for arg in sys.argv if arg != '--public-assets'])
