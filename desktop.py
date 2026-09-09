#!/usr/bin/env python3
"""Run VisualLM as a NATIVE desktop window (no browser chrome at all).

This is the most "real app" option. It needs one extra package:

    pip install pywebview
    python3 desktop.py

It starts the local server in the background and opens VisualLM in a native OS
window (WKWebView on macOS, WebView2 on Windows, GTK/Qt on Linux). API keys via
.env work exactly as in launch.py. If you don't want the extra dependency, use
`python3 launch.py` instead — it opens an app-style browser window.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import launch  # reuse .env loading, free_port, and the health check

HERE = Path(__file__).resolve().parent


def main() -> int:
    try:
        import webview  # pywebview
    except ImportError:
        print("This needs pywebview:  pip install pywebview")
        print("(or just run:  python3 launch.py  — opens an app-style browser window)")
        return 1

    launch.load_dotenv(HERE / ".env")
    forced = os.environ.get("VISUALLM_PORT")
    port = int(forced) if forced else launch.free_port(4173)
    os.environ["VISUALLM_PORT"] = str(port)
    os.environ.setdefault("VISUALLM_HOST", "127.0.0.1")
    url = f"http://127.0.0.1:{port}"

    server = subprocess.Popen([sys.executable, str(HERE / "main.py")], cwd=str(HERE))
    try:
        if not launch.wait_healthy(f"{url}/api/health"):
            print("✗ The server did not start — see output above.")
            return 1
        webview.create_window("VisualLM", url, width=1280, height=820, min_size=(900, 600))
        webview.start()  # blocks until the window closes (must run on main thread)
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
