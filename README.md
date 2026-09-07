# VisualLM

VisualLM turns any STEM question, equation, or idea into a custom **animated 2D
or 3D explanation**. Instead of picking from a handful of fixed demos, the AI
*writes the animation itself* — generating JavaScript that runs in a locked-down
sandbox in your browser — so it can visualize essentially any topic.

## Two editions

VisualLM ships in two flavors of the same project:

| | **Browser edition** (`web/`) | **Desktop / server edition** (repo root) |
|---|---|---|
| Runs | 100% in the browser — **no server, no install, no API key** | Local Python server (or packaged desktop app) |
| Host | **GitHub Pages** (static) — instant, free, shareable link | Your machine, or any server host (Render, etc.) |
| Chemistry: 3D molecules + equation balancing | ✅ | ✅ |
| 333 interactive curriculum demos + 50 curated scenes | ✅ | ✅ |
| Interface languages: English, Chinese, Spanish, Hindi, French, German | ✅ | ✅ |
| Free-form AI generation (type *any* idea) | ❌ (needs a model + key) | ✅ (Claude ▸ ChatGPT ▸ Gemini) |
| AI tutor chat | ❌ | ✅ |

The browser edition is a faithful client-side port: the chemistry engine and the
demo/scene matcher are reimplemented in JavaScript (`web/js/`) with **verified
parity** against the Python — same molecules, same exact-integer balancing, same
scene routing. It's the fastest way to share VisualLM (just a link); the desktop
edition adds the open-ended AI generation that needs server-side keys.

- **Browser edition (live):** https://maxpeng59.github.io/VisualLM/
- **Desktop app:** `python3 launch.py` (browser app-window) or `python3 desktop.py`
  (native window), or build a standalone app with `./build_app.sh`.
- **Server deploy (full app):** see [Deploy](#deploy) below (Render blueprint).

## How it works

```
prompt ──▶ /api/visualize ──▶ AI writes scene code ──▶ sandbox renders it
                                      │                        │
                       (Claude ▸ ChatGPT ▸ Gemini)            │
                                                        error? └─▶ /api/repair ──┐
                                                                                  │
                                                       fixed code ◀───────────────┘
```

1. **You type** an equation (`z = sin(x) * cos(y)`) or an idea ("show how a
   Fourier series builds a square wave"), and optionally prefer 2D or 3D.
2. **The AI generates animation code** — the body of a `scene(ctx, t)`
   function — using a documented helper library (`H`) for 2D plotting, **solid
   shaded 3D surfaces, parametric meshes, spheres**, vectors, and labels.
3. **The sandbox runs it** in a dedicated Web Worker with an OffscreenCanvas.
   The worker has no DOM, no same-origin window, and no network, so generated
   code can't touch your machine. If code hangs, the worker is terminated and
   restarted.
4. **Self-repair loop:** if the generated code throws, the exact error is sent
   back to the model, which returns corrected code. Up to three automatic repairs.
5. **Tutor chat** answers follow-up questions, grounded in the exact scene on
   screen.

**3D scenes are interactive:** drag the canvas to orbit, scroll to zoom,
double-click to reset the view.

## Languages

Use the language selector in the top bar to switch the learning interface
between English, Simplified Chinese, Spanish, Hindi, French, and German. The
choice is saved on the device and restored at the next launch. In the
desktop/server edition, the selected language is also sent to the configured AI
provider so custom scene titles, explanations, canvas labels, and tutor replies
are generated in that language. Equations, variable names, and units remain
universal. Built-in curated lesson subject matter remains available offline.

## Real 3D, not point clouds

The sandbox ships a software 3D pipeline the AI is trained (in-context) to use:

- `H.surface3d(cam, (x,y) => h, …)` — solid, light-shaded, depth-sorted
  height surfaces for anything of the form z = f(x, y).
- `H.mesh3d(cam, (u,v) => [x,y,z], …)` — parametric surfaces: spheres, tori,
  cylinders, tubes, ribbons, Möbius strips.
- `cam.sphere / cam.line / cam.path / cam.poly / cam.grid / cam.axes` —
  shaded balls (molecules, planets), 3D trajectories, filled polygons, and
  spatial reference geometry.

The system prompt teaches the model when to choose 3D (surfaces, orbits,
molecules, fields in space) versus 2D (single-variable functions, circuits,
graphs, planar geometry), and worked examples show exactly how to use the
pipeline.

## Getting the *right* animation — fast and reliably

Generating animation code from a prompt is error-prone, especially with a small
local model. Four layers make it fast and correct without training a model from
scratch (which would be worse and need heavy infrastructure):

1. **Curated STEM scene library** (`scene_library.py` +
   `scene_library_generated.json`) — ~50 hand- and AI-authored scenes across
   two dozen STEM domains, every one re-validated to actually run, paint
   on-screen, animate, and carry labels. A strong keyword match short-circuits
   straight to the matching scene: a "Fourier series" prompt renders in ~5 ms
   instead of a 10–60 s generation that might fail. This is the practical,
   retrieval-augmented realization of "feed it STEM data."
2. **Headless validator** (`validate_scene.js`, run server-side via Node) —
   runs each generated scene in a hardened sandbox (`vm`, fresh empty context,
   2 s timeout) and reports throws / blank / off-screen / no-motion / no-labels
   in ~50 ms. The browser is no longer the validator, so a bad scene is caught
   and repaired *server-side* before it's ever sent — instead of costing a full
   client round-trip per repair. It even catches the subtle "draws everything
   off-screen" coordinate-space mixup. Degrades gracefully if Node is absent.
3. **Deterministic auto-fixer** — mechanically prefixes bare `Math.*` calls
   (`sin(x)` → `Math.sin(x)`, the #1 cause of "X is not defined"), fixing the
   most common failure with zero model round-trips.
4. **Validated-scene cache** — a repeated prompt (or a shared link) returns the
   already-verified scene instantly.

The result: common topics are instant and always correct; novel prompts are
generated, validated, and repaired server-side, then handed to the browser
ready to run. `GET /api/health` reports whether the validator and library are
active (`validator`, `library_size`).

### Regenerating the library

The generated scenes were produced by a multi-agent workflow (one author per
STEM domain, an independent adversarial review per scene). To re-run or extend
it, regenerate `scene_library_generated.json`; every scene is re-checked by
`validate_scene.js` (the test suite asserts the whole library runs).

## Brains (multi-provider)

Generation tries providers in this order — the first one with a key wins:

| Provider | Enable with | Role |
| --- | --- | --- |
| **Claude** | `ANTHROPIC_API_KEY` (+ `pip install anthropic`) | Primary generator — best quality |
| **ChatGPT** | `OPENAI_API_KEY` | Cloud fallback generator |
| **Gemini** | `GEMINI_API_KEY` | Cloud fallback generator |

All cloud providers are called over plain REST — no extra SDKs required. **The AI
relies only on code — there is no local model app.** With **no key at all**,
VisualLM still runs entirely on its built-in pure-code library: 3D chemistry,
balanced reactions, the step-by-step solver, and every interactive demo work
offline. A key only adds free-form "type any idea" generation.

## Run it (as an app)

The easy way — after a one-time setup, **no terminal needed**:

1. **Install dependencies (once).** Run **`./install.sh`** (macOS/Linux) or
   **`install.bat`** (Windows). It creates a `.venv` and downloads everything —
   the Claude client and the native-window backend (pywebview). Then, optionally,
   add a key to `.env`: `ANTHROPIC_API_KEY=sk-ant-...`. **No key? Skip it** —
   chemistry, reactions, the solver, and the demos all run offline; a key only
   adds free-form AI generation.
2. **Launch it.**
   - **macOS:** double-click **`VisualLM.command`** in Finder (first time: right-click → Open to clear the macOS warning).
   - **Any OS:** `python3 launch.py`

   The launcher loads `.env`, starts the server on a free port, waits until it's
   healthy, and opens VisualLM in its own app-style window. Keep that window open;
   Ctrl+C (or closing it) stops everything.

**Prefer a true native window** (no browser chrome at all)? `pip install pywebview`
then `python3 desktop.py`.

**Want a real, self-contained app** (bundles Python — no terminal, no repo needed
to run)? `./build_app.sh` produces **`dist/VisualLM.app`** via PyInstaller; move it
to /Applications and double-click. It runs the server in-process (`app_main.py`)
and serves bundled assets. For Claude inside the bundle, `pip install anthropic`
before building; for a native window, `pip install pywebview` before building.
The packaged app reads a `.env` placed next to `VisualLM.app` or in `~/.visuallm/`.

### Plain manual start

Equivalent to what the launcher does, if you'd rather drive it yourself:

```bash
./install.sh                              # one-time: creates .venv + installs deps
export ANTHROPIC_API_KEY=sk-ant-...       # optional — and/or OPENAI_API_KEY / GEMINI_API_KEY
python3 main.py                           # then open http://127.0.0.1:4173
```

## Deploy to the web

The repo is deploy-ready for any Docker host. The server reads `PORT` and
binds `0.0.0.0` automatically when it's set.

### Render (one click, free tier)

1. Push this repo to GitHub (already done if you're reading this there).
2. In the [Render dashboard](https://dashboard.render.com), **New → Blueprint**,
   pick this repo — `render.yaml` configures everything.
3. In the service's **Environment** tab, set `ANTHROPIC_API_KEY` (or
   `OPENAI_API_KEY` / `GEMINI_API_KEY`).
4. Strongly recommended for a public URL: set `VISUALLM_ACCESS_CODE` to any
   secret phrase. Visitors are asked for it once before they can generate, so
   strangers can't burn your API credits. Per-IP rate limiting is on by
   default (`VISUALLM_RATE_LIMIT`, 10/min via render.yaml).

It works with **no API key** — all curriculum demos and STEM library scenes are
served from the bundled libraries (no model calls), so the site is fully useful
out of the box. A key only enables free-form "type any idea" generation.

### Custom domain (e.g. www.VisualLM.com)

The app is origin-agnostic (all requests are relative paths), so a custom domain
needs only DNS — no code changes:

1. Own the domain (buy `VisualLM.com` from any registrar if you don't).
2. In your Render service → **Settings → Custom Domains** → add `www.visuallm.com`
   (and `visuallm.com`). Render shows the exact DNS records to create.
3. At your registrar's DNS panel, add what Render gives you — typically:
   - `www`  → **CNAME** → `your-app.onrender.com`
   - root `@` → Render's **A record** (or an ALIAS/ANAME → `your-app.onrender.com`)
4. Wait for DNS to propagate (minutes–hours); Render auto-provisions free HTTPS.

### Any other Docker host (Fly.io, Railway, Cloud Run, a VPS…)

```bash
docker build -t visuallm .
docker run -p 8080:8080 -e ANTHROPIC_API_KEY=sk-ant-... visuallm
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Covers code sanitization, JSON extraction from model output, blank-scene
detection, scene normalization, rate limiting, the access-code gate, and real
HTTP round-trips against every endpoint (with stubbed generators).

## Files

- `main.py` — web server, the three cloud AI bridges (Claude/OpenAI/Gemini —
  no local model app), the validate→auto-fix→repair pipeline, library retrieval
  + cache, rate limiting, and the system prompt that defines the rendering
  contract.
- `install.sh` / `install.bat` — one-shot dependency installers (create a
  `.venv`, download the Claude client + the pywebview native-window backend).
- `sandbox-worker.js` — the sandboxed Web Worker that runs generated code on
  an OffscreenCanvas, the `H` helper library, and the software 3D pipeline.
- `validate_scene.js` — headless server-side scene validator (hardened Node
  `vm` sandbox); mirrors the worker's `H` API surface.
- `scene_library.py` / `scene_library_generated.json` — curated, verified STEM
  scene corpus + the keyword retrieval used for the instant fast path.
- `app.js` — orchestration: sandbox runner, generate→run→repair loop, orbit
  controls, playback, tutor chat, resources, status.
- `index.html` / `styles.css` — app structure and visual design.
- `launch.py` / `VisualLM.command` / `desktop.py` — run VisualLM as an app:
  the one-click launcher (loads `.env`, starts the server on a free port, opens
  an app-style window), the macOS double-click wrapper, and the optional
  native-window version (pywebview). `.env.example` is the key template.
- `stem-viz-plugin/` — the scene-generation capability packaged as a portable
  Claude skill + plugin (drop into any AI); see its own README.
- `Dockerfile` / `render.yaml` — production deployment (Docker image bundles
  Node for the validator).
- `tests/` — stdlib-only test suite (covers the validator, auto-fixer,
  library, cache, and every endpoint).

## API

- `POST /api/visualize` `{prompt, preferred_mode}` → a scene (`title`, `tag`,
  `dimension`, `equation`, `summary`, `bullets`, `student_prompts`, `code`).
- `POST /api/repair` `{prompt, code, error}` → a corrected scene.
- `POST /api/chat` `{question, visualization, history}` → tutor answer.
- `GET /api/health` → which backends are available + whether an access code
  is required.
- `GET/POST/DELETE /api/resources` — uploaded reference material.

When `VISUALLM_ACCESS_CODE` is set, all POST/DELETE endpoints require the
`X-Access-Code` header (the UI handles this automatically).

## Environment variables

- `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` (default `claude-opus-4-8`)
- `OPENAI_API_KEY` / `OPENAI_MODEL` (default `gpt-4o`) / `OPENAI_BASE_URL`
- `GEMINI_API_KEY` / `GEMINI_MODEL` (default `gemini-2.0-flash`) / `GEMINI_BASE_URL`
- `VISUALLM_ACCESS_CODE` — require a shared code for generation (recommended
  on public deployments).
- `VISUALLM_RATE_LIMIT` — requests/min per IP (default 20; 0 disables).
- `VISUALLM_HOST` / `VISUALLM_PORT` — default `127.0.0.1` / `4173` locally;
  `PORT` (set by cloud hosts) switches to `0.0.0.0`.

## Safety notes

Generated code is treated as untrusted: it runs only inside the Web Worker
sandbox (no DOM, no same-origin access), and network / sub-worker APIs
(`fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource`, `Worker`,
`SharedWorker`, `WebTransport`, `BroadcastChannel`, `navigator.sendBeacon`,
`importScripts`) are stripped from the worker scope. Runaway code is killed
by a watchdog. The server sanitizes generated code, rate-limits every AI
endpoint per client IP, and can gate generation behind an access code.
