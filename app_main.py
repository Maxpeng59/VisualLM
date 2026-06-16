#!/usr/bin/env python3
"""VisualLM native-app entry point — runs the server IN-PROCESS and opens a window.

This is what PyInstaller freezes into VisualLM.app, and it also works unfrozen
(`python3 app_main.py`). Unlike launch.py / desktop.py — which spawn `python
main.py` as a subprocess for the dev workflow — this imports the server and runs
it in a background thread, because a frozen app's `sys.executable` is the app
binary, not a Python interpreter, so spawning a subprocess can't work once bundled.

Flags:
    --no-window   start the server only (print the URL, keep serving)
    --smoke       start, confirm /api/health, stop, exit 0 (for testing)
"""
from __future__ import annotations

import os
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import launch  # reuse load_dotenv / free_port / wait_healthy / open_app_window

HERE = Path(__file__).resolve().parent


def _env_files() -> list[Path]:
    """Where to look for a .env. When frozen (inside VisualLM.app) __file__ is
    in the bundle, so also check next to the .app and a per-user config dir —
    that's where a user can drop ANTHROPIC_API_KEY=... for the packaged app."""
    if getattr(sys, "frozen", False):
        out: list[Path] = []
        exe = Path(sys.executable).resolve()
        # .../VisualLM.app/Contents/MacOS/VisualLM -> the folder holding the .app
        if len(exe.parents) >= 4:
            out.append(exe.parents[3] / ".env")
        out.append(Path.home() / ".visuallm" / ".env")
        return out
    return [HERE / ".env"]


def main() -> int:
    for env_file in _env_files():
        launch.load_dotenv(env_file)
    forced = os.environ.get("VISUALLM_PORT")
    port = int(forced) if forced else launch.free_port(4173)
    os.environ["VISUALLM_PORT"] = str(port)
    os.environ.setdefault("VISUALLM_HOST", "127.0.0.1")
    url = f"http://127.0.0.1:{port}"

    # Importing the server module is side-effect-free (its server start is under
    # an `if __name__ == "__main__"` guard); we drive it ourselves below.
    import main as server_mod

    httpd = ThreadingHTTPServer(("127.0.0.1", port), server_mod.VisualLMHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    smoke = "--smoke" in sys.argv
    no_window = smoke or "--no-window" in sys.argv
    try:
        if not launch.wait_healthy(f"{url}/api/health"):
            print("✗ Server did not become healthy.")
            return 1
        print(f"✓ VisualLM is up on {url}")
        if smoke:
            # Also confirm static assets serve — the real test that bundled data
            # files (index.html etc.) resolve via BASE_DIR when frozen.
            import urllib.request
            try:
                with urllib.request.urlopen(url + "/", timeout=3) as r:
                    served = r.status == 200 and b"VisualLM" in r.read()
            except Exception:  # noqa: BLE001
                served = False
            print("✓ static assets served (index.html)" if served else "✗ static assets NOT served")
            print("✓ Smoke check passed." if served else "✗ Smoke check FAILED.")
            return 0 if served else 1
        if no_window:
            print(f"  Open {url} in your browser. Ctrl+C to stop.")
            _block()
            return 0
        try:
            import webview  # pywebview → true native window
        except ImportError:
            print("• pywebview not installed — opening an app-style browser window.")
            print("  (pip install pywebview for a true native window.)")
            launch.open_app_window(url)
            _block()
            return 0
        webview.create_window("VisualLM", url, width=1280, height=820, min_size=(900, 600))
        webview.start()  # blocks on the main thread until the window closes
        return 0
    finally:
        httpd.shutdown()


def _block() -> None:
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
