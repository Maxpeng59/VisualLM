#!/usr/bin/env bash
# ============================================================================
# VisualLM — one-shot dependency installer (macOS / Linux)
#
#   ./install.sh
#
# Creates an isolated virtual environment (.venv) and downloads everything
# VisualLM needs to run as a desktop app:
#
#   • anthropic   — the Claude API client that powers the best animations.
#                   VisualLM relies ONLY on code: with a key it calls Claude,
#                   without one it uses the built-in pure-code library
#                   (interactive demos + chemistry + step-by-step solver).
#                   No local model app (Ollama etc.) is required or used.
#   • pywebview   — opens VisualLM in a true native OS window. Optional: if it
#                   fails to build, the app still opens an app-style browser
#                   window, so the install continues either way.
#
# The server itself is pure Python standard library — nothing else needed.
#
# After it finishes:
#   source .venv/bin/activate
#   python3 desktop.py          # native window   (or ./VisualLM.command)
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\033[1m• %s\033[0m\n' "$*"; }
ok()  { printf '\033[32m✓ %s\033[0m\n' "$*"; }
warn(){ printf '\033[33m! %s\033[0m\n' "$*"; }

# --- 1. Find a Python 3 interpreter -----------------------------------------
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 9) else 1)' 2>/dev/null; then
      PY="$cand"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  warn "Python 3.9+ was not found on your PATH."
  echo "  Install it from https://www.python.org/downloads/ (or 'brew install python')"
  echo "  and re-run ./install.sh"
  exit 1
fi
ok "Using $("$PY" --version 2>&1) at $(command -v "$PY")"

# --- 2. Create / reuse a virtual environment --------------------------------
if [ ! -d ".venv" ]; then
  say "Creating virtual environment (.venv) …"
  "$PY" -m venv .venv
else
  say "Reusing existing virtual environment (.venv)"
fi
# shellcheck disable=SC1091
source .venv/bin/activate
VENV_PY="$(command -v python)"

say "Upgrading pip …"
"$VENV_PY" -m pip install --quiet --upgrade pip

# --- 3. Core dependency: the Claude client ----------------------------------
say "Installing core dependencies (anthropic) …"
"$VENV_PY" -m pip install --quiet -r requirements.txt
ok "Core dependencies installed."

# --- 4. Optional: native-window backend -------------------------------------
say "Installing the native-window backend (pywebview) …"
if "$VENV_PY" -m pip install --quiet pywebview; then
  ok "pywebview installed — desktop.py will open a true native window."
else
  warn "pywebview could not be installed (that's OK)."
  echo "  VisualLM will open an app-style browser window instead."
fi

# NOTE: we deliberately do NOT create a .env. With no key, VisualLM runs cleanly
# in code-only mode. When you want AI generation, copy .env.example to .env and
# add a real key (a placeholder key would make the app try — and fail — Claude).

cat <<'DONE'

──────────────────────────────────────────────────────────────────────────
✓ VisualLM is ready.

  Run the desktop app:
      source .venv/bin/activate
      python3 desktop.py            # native window
      #  …or:  ./VisualLM.command   (double-click in Finder on macOS)
      #  …or:  python3 launch.py    (app-style browser window)

  No API key? It still runs — you'll get the built-in pure-code library
  (interactive demos, 3D chemistry, and the step-by-step solver), all offline.
  For AI-generated animations: cp .env.example .env  then put your real
  ANTHROPIC_API_KEY=sk-ant-... in .env
──────────────────────────────────────────────────────────────────────────
DONE
