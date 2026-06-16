#!/bin/bash
# Build a SELF-CONTAINED, double-click VisualLM.app with PyInstaller.
#
#   ./build_app.sh
#   open dist/VisualLM.app
#
# Unlike make_app.sh (a lightweight wrapper that needs the repo + system Python),
# this produces a standalone bundle that includes Python and all dependencies.
# To bundle Claude support, `pip install anthropic` first; otherwise the app
# uses OpenAI / Gemini / Ollama. For a true native window, `pip install pywebview`
# before building; otherwise it opens an app-style browser window.
#
# macOS only (uses sips/iconutil for the icon). Output: dist/VisualLM.app
set -euo pipefail
cd "$(dirname "$0")"

echo "• Ensuring PyInstaller is available …"
python3 -c "import PyInstaller" 2>/dev/null || python3 -m pip install --disable-pip-version-check pyinstaller

echo "• Generating icon …"
python3 make_icon.py VisualLM.png >/dev/null
ICONSET="VisualLM.iconset"; rm -rf "$ICONSET"; mkdir "$ICONSET"
gen() { sips -z "$2" "$2" VisualLM.png --out "$ICONSET/$1" >/dev/null; }
gen icon_16x16.png 16;   gen icon_16x16@2x.png 32
gen icon_32x32.png 32;   gen icon_32x32@2x.png 64
gen icon_128x128.png 128; gen icon_128x128@2x.png 256
gen icon_256x256.png 256; gen icon_256x256@2x.png 512
gen icon_512x512.png 512; gen icon_512x512@2x.png 1024
iconutil -c icns "$ICONSET" -o VisualLM.icns
rm -rf "$ICONSET" VisualLM.png

echo "• Freezing app with PyInstaller …"
python3 -m PyInstaller --noconfirm --clean VisualLM.spec

rm -f VisualLM.icns
echo "✓ Built dist/VisualLM.app"
echo "  Verify:  dist/VisualLM.app/Contents/MacOS/VisualLM --smoke"
echo "  Run:     open dist/VisualLM.app"
