@echo off
REM ===========================================================================
REM VisualLM - one-shot dependency installer (Windows)
REM
REM   install.bat
REM
REM Creates an isolated virtual environment (.venv) and downloads everything
REM VisualLM needs to run as a desktop app:
REM
REM   * anthropic  - the Claude API client that powers the best animations.
REM                  VisualLM relies ONLY on code: with a key it calls Claude,
REM                  without one it uses the built-in pure-code library
REM                  (interactive demos + 3D chemistry + step-by-step solver).
REM                  No local model app (Ollama etc.) is required or used.
REM   * pywebview  - opens VisualLM in a true native OS window (WebView2).
REM                  Optional: if it fails to install, the app opens an
REM                  app-style browser window instead.
REM
REM The server itself is pure Python standard library - nothing else needed.
REM
REM After it finishes:
REM   .venv\Scripts\activate
REM   python desktop.py
REM ===========================================================================
setlocal
cd /d "%~dp0"

REM --- 1. Find a Python 3 interpreter ----------------------------------------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo ! Python 3.9+ was not found on your PATH.
  echo   Install it from https://www.python.org/downloads/ ^(check "Add to PATH"^)
  echo   and re-run install.bat
  exit /b 1
)
echo - Using Python: %PY%

REM --- 2. Create / reuse a virtual environment -------------------------------
if not exist ".venv" (
  echo - Creating virtual environment ^(.venv^) ...
  %PY% -m venv .venv || (echo ! Failed to create venv & exit /b 1)
) else (
  echo - Reusing existing virtual environment ^(.venv^)
)
set "VENV_PY=.venv\Scripts\python.exe"

echo - Upgrading pip ...
"%VENV_PY%" -m pip install --quiet --upgrade pip

REM --- 3. Core dependency: the Claude client ---------------------------------
echo - Installing core dependencies ^(anthropic^) ...
"%VENV_PY%" -m pip install --quiet -r requirements.txt || (echo ! Failed to install core deps & exit /b 1)
echo + Core dependencies installed.

REM --- 4. Optional: native-window backend ------------------------------------
echo - Installing the native-window backend ^(pywebview^) ...
"%VENV_PY%" -m pip install --quiet pywebview && (
  echo + pywebview installed - desktop.py will open a true native window.
) || (
  echo ! pywebview could not be installed ^(that's OK^).
  echo   VisualLM will open an app-style browser window instead.
)

REM NOTE: we deliberately do NOT create a .env. With no key, VisualLM runs cleanly
REM in code-only mode. When you want AI generation, copy .env.example to .env and
REM add a real key (a placeholder key would make the app try - and fail - Claude).

echo.
echo --------------------------------------------------------------------------
echo + VisualLM is ready.
echo.
echo   Run the desktop app:
echo       .venv\Scripts\activate
echo       python desktop.py
echo.
echo   No API key? It still runs - you get the built-in pure-code library
echo   (interactive demos, 3D chemistry, step-by-step solver), all offline.
echo   For AI animations: copy .env.example .env  then add your real
echo   ANTHROPIC_API_KEY=sk-ant-... to .env
echo --------------------------------------------------------------------------
endlocal
