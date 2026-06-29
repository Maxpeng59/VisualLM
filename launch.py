#!/usr/bin/env python3
"""One-click launcher for VisualLM.

Run it:
    python3 launch.py            # start the server + open the app in a window
    ./VisualLM.command           # macOS: just double-click this in Finder

It loads API keys from a `.env` file next to this script (if present), starts the
local server (main.py), waits until it's healthy, then opens the UI — preferring
a chrome-less "app window" (Chrome / Edge / Brave --app mode) and falling back to
your default browser. Leave the launcher running; Ctrl+C stops everything.

Flags:
    --no-browser   start the server but don't open a window
    --smoke        start, confirm healthy, stop, exit 0 (used for testing)
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE lines from `.env` into the environment.

    Does NOT override variables already set in the real environment, so an
    explicit `export ANTHROPIC_API_KEY=...` still wins over the file.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def free_port(preferred: int) -> int:
    """Return `preferred` if it's bindable, otherwise an OS-chosen free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def wait_healthy(url: str, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.25)
    return False


def open_app_window(url: str) -> None:
    """Open `url` in a chrome-less app window if a Chromium browser is present,
    else fall back to the default browser."""
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("microsoft-edge"),
        shutil.which("brave-browser"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            try:
                subprocess.Popen(
                    [c, f"--app={url}", "--new-window"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except OSError:
                pass
    webbrowser.open(url)


def main() -> int:
    load_dotenv(HERE / ".env")

    forced = os.environ.get("VISUALLM_PORT")
    port = int(forced) if forced else free_port(4173)
    os.environ["VISUALLM_PORT"] = str(port)
    os.environ.setdefault("VISUALLM_HOST", "127.0.0.1")
    url = f"http://127.0.0.1:{port}"
    no_browser = "--no-browser" in sys.argv or "--smoke" in sys.argv
    smoke = "--smoke" in sys.argv

    if not any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")):
        print("• No cloud API key found — running in code-only mode. Chemistry,")
        print("  reactions, the step-by-step solver, and the demo library all work")
        print("  offline. For AI generation of free-form prompts, put")
        print("  ANTHROPIC_API_KEY=sk-ant-... in a .env file next to launch.py")
        print("  (copy .env.example to .env). See README for details.\n")

    print(f"• Starting VisualLM on {url} …")
    server = subprocess.Popen([sys.executable, str(HERE / "main.py")], cwd=str(HERE))
    try:
        if not wait_healthy(f"{url}/api/health"):
            print("✗ The server did not become healthy in time — see output above.")
            return 1
        print("✓ VisualLM is up.")
        if smoke:
            print("✓ Smoke check passed.")
            return 0
        if no_browser:
            print(f"  Open {url} in your browser.")
        else:
            print("• Opening the app window …")
            open_app_window(url)
        print("\nVisualLM is running. Keep this window open. Press Ctrl+C to stop.\n")
        server.wait()
    except KeyboardInterrupt:
        print("\n• Stopping VisualLM …")
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
