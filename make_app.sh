#!/bin/bash
# Build VisualLM.app — a real, double-clickable macOS app for VisualLM.
#
#   ./make_app.sh
#
# It generates an icon, then assembles a .app bundle that (when double-clicked)
# starts the local server and opens VisualLM in a native window if pywebview is
# installed (`pip install pywebview`), otherwise an app-style browser window.
#
# The bundle lives next to this script and resolves the repo by its own
# location, so keep VisualLM.app inside the repo folder. It's a build artifact
# (git-ignored); re-run this script to rebuild. macOS only (needs iconutil/sips).
set -euo pipefail
cd "$(dirname "$0")"

APP="VisualLM.app"
PYBIN="$(command -v python3 || true)"
[ -n "$PYBIN" ] || { echo "python3 not found on PATH"; exit 1; }

echo "• Generating icon …"
python3 make_icon.py VisualLM.png >/dev/null
ICONSET="VisualLM.iconset"; rm -rf "$ICONSET"; mkdir "$ICONSET"
# Exact names iconutil expects (logical size + @2x retina variant).
gen() { sips -z "$2" "$2" VisualLM.png --out "$ICONSET/$1" >/dev/null; }
gen icon_16x16.png        16
gen icon_16x16@2x.png     32
gen icon_32x32.png        32
gen icon_32x32@2x.png     64
gen icon_128x128.png     128
gen icon_128x128@2x.png  256
gen icon_256x256.png     256
gen icon_256x256@2x.png  512
gen icon_512x512.png     512
gen icon_512x512@2x.png 1024
iconutil -c icns "$ICONSET" -o VisualLM.icns

echo "• Assembling $APP …"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp VisualLM.icns "$APP/Contents/Resources/VisualLM.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>VisualLM</string>
  <key>CFBundleDisplayName</key><string>VisualLM</string>
  <key>CFBundleIdentifier</key><string>com.visuallm.app</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>VisualLM</string>
  <key>CFBundleIconFile</key><string>VisualLM</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
</dict>
</plist>
PLIST

# The launcher. PYBIN is baked at build time because a Finder-launched app gets
# a minimal PATH that usually won't include a pyenv/framework python3.
cat > "$APP/Contents/MacOS/VisualLM" <<LAUNCH
#!/bin/bash
REPO="\$(cd "\$(dirname "\$0")/../../.." && pwd)"
cd "\$REPO" || exit 1
LOG="\$HOME/Library/Logs/VisualLM.log"; mkdir -p "\$(dirname "\$LOG")"
PY="$PYBIN"; [ -x "\$PY" ] || PY="\$(command -v python3 || echo python3)"
echo "--- VisualLM \$(date) repo=\$REPO py=\$PY ---" >> "\$LOG"
# Native window via pywebview if available; otherwise an app-style browser window.
"\$PY" desktop.py >> "\$LOG" 2>&1 || "\$PY" launch.py >> "\$LOG" 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/VisualLM"

rm -rf "$ICONSET" VisualLM.png VisualLM.icns
touch "$APP"   # nudge Finder to refresh the icon

echo "✓ Built $APP"
echo "  Double-click it in Finder. First launch: right-click → Open (clears the"
echo "  macOS 'unidentified developer' warning once). For a true native window,"
echo "  'pip install pywebview' first; otherwise it opens an app-style window."
