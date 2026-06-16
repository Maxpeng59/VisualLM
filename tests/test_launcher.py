"""Tests for the app launcher (launch.py) and native-app entry (app_main.py).

Stdlib only, headless: covers .env loading, free-port selection, the health
poll, and the frozen-vs-source .env search-path logic — the glue that runs
`python3 launch.py`, the VisualLM.app wrapper, and the PyInstaller bundle.
"""
from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_main  # noqa: E402
import launch  # noqa: E402


class LoadDotenvTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)

    def test_loads_keys_strips_quotes_skips_junk(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text('# comment\nFOO_T=bar\nQUOTED="hello world"\n\nNO_EQUALS\n')
            for k in ("FOO_T", "QUOTED"):
                os.environ.pop(k, None)
            launch.load_dotenv(p)
            self.assertEqual(os.environ.get("FOO_T"), "bar")
            self.assertEqual(os.environ.get("QUOTED"), "hello world")
            self.assertNotIn("NO_EQUALS", os.environ)

    def test_does_not_override_existing_env(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("FOO_T2=fromfile\n")
            os.environ["FOO_T2"] = "preset"
            launch.load_dotenv(p)
            self.assertEqual(os.environ["FOO_T2"], "preset")  # shell wins

    def test_missing_file_is_noop(self):
        launch.load_dotenv(Path("/no/such/.env"))  # must not raise


class FreePortTests(unittest.TestCase):
    @staticmethod
    def _an_unused_port() -> int:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def test_returns_preferred_when_free(self):
        port = self._an_unused_port()
        self.assertEqual(launch.free_port(port), port)

    def test_falls_back_when_preferred_is_taken(self):
        held = socket.socket()
        held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        taken = held.getsockname()[1]
        try:
            got = launch.free_port(taken)
            self.assertNotEqual(got, taken)
            probe = socket.socket()  # the returned port must be bindable
            probe.bind(("127.0.0.1", got))
            probe.close()
        finally:
            held.close()


class WaitHealthyTests(unittest.TestCase):
    def test_true_when_server_responds_200(self):
        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), _H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            self.assertTrue(launch.wait_healthy(f"http://127.0.0.1:{port}/health", timeout=5))
        finally:
            srv.shutdown()
            srv.server_close()

    def test_false_when_nothing_listens(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        self.assertFalse(launch.wait_healthy(f"http://127.0.0.1:{port}/health", timeout=1.0))


class EnvFilesTests(unittest.TestCase):
    def test_unfrozen_uses_local_env(self):
        self.assertFalse(getattr(sys, "frozen", False))
        self.assertEqual(app_main._env_files(), [app_main.HERE / ".env"])

    def test_frozen_searches_alongside_app_and_user_dir(self):
        had_frozen = hasattr(sys, "frozen")
        orig_frozen = getattr(sys, "frozen", None)
        orig_exe = sys.executable
        sys.frozen = True
        sys.executable = str(Path(tempfile.gettempdir()) / "X/VisualLM.app/Contents/MacOS/VisualLM")
        try:
            files = app_main._env_files()
        finally:
            sys.executable = orig_exe
            if had_frozen:
                sys.frozen = orig_frozen
            else:
                del sys.frozen
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0].name, ".env")
        self.assertIn(Path.home() / ".visuallm" / ".env", files)


if __name__ == "__main__":
    unittest.main()
