# -*- coding: utf-8 -*-
"""v2.3.1: 시작할 때 업데이트 감지(app_update) — 서버 배포 / 공유 폴더 / 다운로드 검증."""
import hashlib
import json
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app_update  # noqa: E402

INSTALLER = b'MZ' + b'\x00installer-bytes' * 5000
NAME = 'NC_Tool_List_Setup_v2.3.1.exe'


class FakeServer:
    """라이선스 서버의 /api/v1/update 와 다운로드만 흉내 낸다."""

    def __init__(self):
        self.update = {'version': '2.3.1', 'file': NAME, 'size': len(INSTALLER),
                       'sha256': hashlib.sha256(INSTALLER).hexdigest()}
        self.body = INSTALLER
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == '/api/v1/update':
                    data = json.dumps({'ok': True, 'update': owner.update}).encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                elif self.path == '/api/v1/update/download/' + NAME:
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(owner.body)))
                    self.end_headers()
                    self.wfile.write(owner.body)
                else:
                    self.send_response(404)
                    self.end_headers()

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = 'http://127.0.0.1:%d' % self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _closed_port_url():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return 'http://127.0.0.1:%d' % port


class FindUpdateTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer()
        self.addCleanup(self.server.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_server_newer_version_is_found(self):
        c = app_update.find_update('2.3.0', server_url=self.server.url)
        self.assertEqual(c['source'], 'server')
        self.assertEqual(c['version'], (2, 3, 1))
        self.assertEqual(c['file'], NAME)

    def test_same_or_older_version_is_ignored(self):
        self.assertIsNone(app_update.find_update('2.3.1', server_url=self.server.url))
        self.assertIsNone(app_update.find_update('2.4.0', server_url=self.server.url))

    def test_server_without_update_falls_back_to_share(self):
        self.server.update = None
        share = lambda root: (Path(root) / 'NC_Tool_List_Setup_v2.3.2.exe', (2, 3, 2))  # noqa: E731
        c = app_update.find_update('2.3.0', server_url=self.server.url, share_root='X:/share', share_finder=share)
        self.assertEqual((c['source'], c['version_text']), ('share', '2.3.2'))

    def test_unreachable_server_is_silent_and_uses_share(self):
        share = lambda root: (Path(root) / 'NC_Tool_List_Setup_v2.3.1.exe', (2, 3, 1))  # noqa: E731
        c = app_update.find_update('2.3.0', server_url=_closed_port_url(), share_root='X:/s', share_finder=share)
        self.assertEqual(c['source'], 'share')
        self.assertIsNone(app_update.find_update('2.3.0', server_url=_closed_port_url()))

    def test_share_errors_are_swallowed(self):
        def broken(root):
            raise OSError('no access')
        self.assertIsNone(app_update.find_update('2.3.0', share_root='X:/s', share_finder=broken))

    def test_malformed_server_reply_is_ignored(self):
        for bad in ({'version': '2.3.1', 'file': '../evil.exe', 'size': 1, 'sha256': 'a' * 64},
                    {'version': 'x', 'file': NAME, 'size': 1, 'sha256': 'a' * 64},
                    {'version': '2.3.1', 'file': NAME, 'size': 1, 'sha256': 'short'}):
            self.server.update = bad
            self.assertIsNone(app_update.find_update('2.3.0', server_url=self.server.url), bad)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer()
        self.addCleanup(self.server.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dest = Path(self.tmp.name)

    def candidate(self):
        return app_update.find_update('2.3.0', server_url=self.server.url)

    def test_download_verifies_and_reports_progress(self):
        seen = []
        path = app_update.download_server_update(self.candidate(), dest_dir=self.dest,
                                                 progress=lambda d, t: seen.append((d, t)), chunk_size=4096)
        self.assertEqual(path, self.dest / NAME)
        self.assertEqual(path.read_bytes(), INSTALLER)
        self.assertEqual(seen[-1], (len(INSTALLER), len(INSTALLER)))
        self.assertFalse((self.dest / (NAME + '.part')).exists())

    def test_hash_mismatch_is_rejected_and_file_removed(self):
        c = self.candidate()
        self.server.body = INSTALLER[:-1] + b'X'
        with self.assertRaises(app_update.UpdateError) as ctx:
            app_update.download_server_update(c, dest_dir=self.dest)
        self.assertIn('SHA-256', str(ctx.exception))
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_size_mismatch_is_rejected(self):
        c = self.candidate()
        self.server.body = INSTALLER[:1000]
        with self.assertRaises(app_update.UpdateError):
            app_update.download_server_update(c, dest_dir=self.dest)
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_cancel(self):
        with self.assertRaises(app_update.UpdateCancelled):
            app_update.download_server_update(self.candidate(), dest_dir=self.dest, cancelled=lambda: True)
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_unreachable_download_raises_update_error(self):
        c = self.candidate()
        c['server_url'] = _closed_port_url()
        with self.assertRaises(app_update.UpdateError):
            app_update.download_server_update(c, dest_dir=self.dest, timeout=2)


if __name__ == '__main__':
    unittest.main()
