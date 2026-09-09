# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — freezes VisualLM into a self-contained, double-click macOS app.
#
#   ./build_app.sh        # regenerates the icon, then runs `pyinstaller VisualLM.spec`
#   open dist/VisualLM.app
#
# The frozen app runs the server in-process (app_main.py) and serves the bundled
# static assets via main.py's BASE_DIR -> sys._MEIPASS. It opens a native
# pywebview window if pywebview was importable at build time, else an app-style
# browser window. To include Claude, `pip install anthropic` before building;
# otherwise the bundle uses OpenAI / Gemini, or the built-in pure-code library.
from pathlib import Path

# Static + data files the server reads at runtime, placed at the bundle root.
_ASSETS = [
    "index.html", "app.js", "sandbox-worker.js", "styles.css",
    "validate_scene.js", "scene_library.py", "scene_library_generated.json",
]
datas = [(a, ".") for a in _ASSETS if Path(a).exists()]
if Path("web/i18n.js").exists():
    datas.append(("web/i18n.js", "web"))

# pywebview is optional: include its backend only if it's installed, so the
# build works without it (app_main.py falls back to a browser window).
hiddenimports = ["main", "launch"]
try:
    import webview  # noqa: F401
    hiddenimports.append("webview")
except ImportError:
    pass

icon = "VisualLM.icns" if Path("VisualLM.icns").exists() else None

a = Analysis(
    ["app_main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VisualLM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed app — no terminal
    argv_emulation=False,
    icon=icon,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="VisualLM")

app = BUNDLE(
    coll,
    name="VisualLM.app",
    icon=icon,
    bundle_identifier="com.visuallm.app",
    info_plist={
        "CFBundleName": "VisualLM",
        "CFBundleDisplayName": "VisualLM",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "10.13",
    },
)
