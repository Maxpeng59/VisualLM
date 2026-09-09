#!/bin/bash
# Double-click this file in Finder to launch VisualLM like an app.
# (macOS may ask once to confirm running it — right-click → Open the first time.)
cd "$(dirname "$0")" || exit 1
exec python3 launch.py
