from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import defaultdict, deque
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


# When bundled by PyInstaller, the static assets + validate_scene.js live in the
# unpacked bundle dir (sys._MEIPASS), not beside a source file. Harmless when
# not frozen (falls back to this file's directory). _MEIPASS is injected by the
# PyInstaller bootloader at runtime and isn't in the type stubs, so read it via
# getattr to keep static type-checkers (Pylance/Pyright) quiet.
_meipass = getattr(sys, "_MEIPASS", None)
if getattr(sys, "frozen", False) and _meipass:
    BASE_DIR = Path(_meipass)
else:
    BASE_DIR = Path(__file__).resolve().parent

# Hard caps for the in-memory resource store (single-user local app).
MAX_RESOURCES = 12
MAX_RESOURCE_CHARS = 60_000           # per file
MAX_TOTAL_RESOURCE_CHARS = 240_000    # across all files combined
MAX_CONTEXT_PER_RESOURCE = 18_000     # chars used per generation/chat turn

# Largest POST body we'll read off the wire. The biggest legitimate request
# is a resource upload of ~1.5 MB; 4 MB gives plenty of headroom while
# preventing a malicious `Content-Length: 999999999` from hanging a worker
# thread on `rfile.read(huge_n)` (which would either OOM or wait forever).
MAX_REQUEST_BODY_BYTES = 4 * 1024 * 1024

# --- Ollama (local) is used for the tutor chat and as an offline fallback. ---
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
PREFERRED_MODELS = (
    "qwen2.5:7b",
    "llama3.2",
    "llama3.1:8b",
    "phi4-mini",
)

# --- Claude (cloud) is the primary brain for generating animation code. ---
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")
# Generation depth/latency lever. Opus 4.8 effort levels: low|medium|high|xhigh|max.
# Default "high": code-gen for novel STEM scenes is intelligence-sensitive, and
# correct first-try code is precisely what AVOIDS the slow client-side repair
# loop. Set VISUALLM_CLAUDE_EFFORT=medium to trade a little quality for speed.
ANTHROPIC_EFFORT = os.environ.get("VISUALLM_CLAUDE_EFFORT", "high").strip() or "high"
# Hard per-response ceiling (the model isn't aware of it). A scene is a few KB of
# code plus short text, so 32k is generous headroom for thinking + output; lower
# it only if you need to cap cost. Too low risks truncated JSON -> a parse error
# that the caller counts as a failed generation.
ANTHROPIC_MAX_TOKENS = int(os.environ.get("VISUALLM_CLAUDE_MAX_TOKENS", "32000"))

# --- OpenAI / Gemini are optional cloud fallbacks (key = enabled). ---
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
GEMINI_BASE_URL = os.environ.get(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
).rstrip("/")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")


# ===================================================================== #
# Abuse protection (the app may be exposed to the public internet)      #
# ===================================================================== #
#
# Every /api POST burns either local compute (Ollama) or the operator's paid
# API credits (Claude/OpenAI/Gemini), so when published we (a) rate-limit per
# client IP with a sliding 60 s window and (b) optionally require a shared
# access code (VISUALLM_ACCESS_CODE) so only people you invite can generate.

RATE_LIMIT_PER_MIN = int(os.environ.get("VISUALLM_RATE_LIMIT", "20"))
ACCESS_CODE = os.environ.get("VISUALLM_ACCESS_CODE", "").strip()

_rate_lock = threading.Lock()
_rate_hits: dict[str, deque] = defaultdict(deque)


def rate_limit_ok(ip: str, now: float | None = None) -> bool:
    """Record a hit for `ip` and return False once it exceeds the window."""
    if RATE_LIMIT_PER_MIN <= 0:  # 0 disables limiting (local dev)
        return True
    now = time.time() if now is None else now
    with _rate_lock:
        hits = _rate_hits[ip]
        while hits and hits[0] <= now - 60.0:
            hits.popleft()
        if len(hits) >= RATE_LIMIT_PER_MIN:
            return False
        hits.append(now)
        # Bound memory: drop idle IPs once the table gets large.
        if len(_rate_hits) > 5000:
            for stale in [k for k, v in _rate_hits.items() if not v]:
                del _rate_hits[stale]
        return True


def access_code_ok(supplied: object) -> bool:
    if not ACCESS_CODE:
        return True
    if not isinstance(supplied, str):
        return False
    return hmac.compare_digest(supplied.strip(), ACCESS_CODE)


# ===================================================================== #
# HTTP plumbing                                                         #
# ===================================================================== #


def read_json_body(handler: SimpleHTTPRequestHandler) -> dict:
    raw_header = handler.headers.get("Content-Length", "0")
    try:
        content_length = int(raw_header)
    except ValueError as err:
        # A non-numeric Content-Length used to ValueError out of do_POST and
        # drop the connection (curl saw HTTP 000). Surface a clean 400 by
        # raising a JSONDecodeError, which do_POST already catches.
        raise json.JSONDecodeError(
            f"Invalid Content-Length: {raw_header!r}", "", 0
        ) from err
    if content_length < 0:
        raise json.JSONDecodeError(
            f"Negative Content-Length: {content_length}", "", 0
        )
    if content_length > MAX_REQUEST_BODY_BYTES:
        raise json.JSONDecodeError(
            f"Body too large: {content_length} > {MAX_REQUEST_BODY_BYTES}", "", 0
        )
    raw_body = handler.rfile.read(content_length) if content_length else b"{}"
    if not raw_body:
        return {}
    return json.loads(raw_body.decode("utf-8"))


def send_json(handler: SimpleHTTPRequestHandler, status: HTTPStatus, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    try:
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
    except (BrokenPipeError, ConnectionError):
        # Client disconnected mid-response (common when the user navigates away
        # during a slow generation). There's no one to send to — swallow it
        # rather than let it surface as an unhandled traceback in the log.
        pass


# ===================================================================== #
# Ollama bridge                                                         #
# ===================================================================== #


def ollama_request(path: str, payload: dict | None = None, timeout: float = 60.0) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(details or f"Ollama returned HTTP {error.code}.") from error
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", error)
        raise RuntimeError(f"Could not reach Ollama at {OLLAMA_URL}. {reason}") from error


def fetch_ollama_models() -> list[dict]:
    response = ollama_request("/api/tags", timeout=10.0)
    return response.get("models", [])


def choose_ollama_model(models: list[dict]) -> str:
    configured = os.environ.get("OLLAMA_MODEL", "").strip()
    if configured:
        return configured
    available = [m.get("name", "") for m in models]
    for candidate in PREFERRED_MODELS:
        if candidate in available:
            return candidate
    return available[0] if available else PREFERRED_MODELS[0]


def ollama_available() -> tuple[bool, str | None]:
    try:
        fetch_ollama_models()
        return True, None
    except RuntimeError as error:
        return False, str(error)


# ===================================================================== #
# Resource store (uploaded reference material)                          #
# ===================================================================== #
#
# Single-user, in-memory. Files are kept as text so both the generator
# (Claude) and the tutor (Ollama/Claude) can ground their output in them.
# Binary files are rejected; users upload notes, problem sets, lecture
# excerpts, code, datasets — anything text-ish.

_resources_lock = threading.Lock()
_resources: list[dict] = []


def _resources_total_chars() -> int:
    return sum(len(r["content"]) for r in _resources)


def list_resources() -> list[dict]:
    with _resources_lock:
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "size": len(r["content"]),
                "uploaded_at": r["uploaded_at"],
            }
            for r in _resources
        ]


def add_resource(name: str, content: str) -> dict:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Resource name is required.")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Resource content is empty or not text.")

    # Light binary detection: reject if too many NULs / control bytes appear.
    sample = content[:4000]
    non_text = sum(
        1
        for ch in sample
        if ch not in "\n\r\t" and (ord(ch) < 32 or ord(ch) == 127)
    )
    if sample and non_text / max(1, len(sample)) > 0.05:
        raise ValueError(
            "That file looks binary. Upload text-based files (.txt, .md, "
            ".csv, .json, .py, .js, etc.)."
        )

    trimmed = content[:MAX_RESOURCE_CHARS]
    with _resources_lock:
        if len(_resources) >= MAX_RESOURCES:
            raise ValueError(
                f"You can keep at most {MAX_RESOURCES} resources. Delete one first."
            )
        if _resources_total_chars() + len(trimmed) > MAX_TOTAL_RESOURCE_CHARS:
            raise ValueError(
                "Total resource size would exceed the limit. Delete a larger "
                "resource first."
            )
        entry = {
            "id": uuid.uuid4().hex[:12],
            "name": name.strip()[:200],
            "content": trimmed,
            "uploaded_at": time.time(),
        }
        _resources.append(entry)
        return {
            "id": entry["id"],
            "name": entry["name"],
            "size": len(entry["content"]),
            "uploaded_at": entry["uploaded_at"],
            "truncated": len(content) > MAX_RESOURCE_CHARS,
        }


def delete_resource(resource_id: str) -> bool:
    with _resources_lock:
        for i, r in enumerate(_resources):
            if r["id"] == resource_id:
                _resources.pop(i)
                return True
    return False


def resources_context_block() -> str:
    """Format every resource as a labeled text block for prompts.

    Returns "" when there are no resources, so callers can cheaply skip
    appending it.
    """
    with _resources_lock:
        if not _resources:
            return ""
        parts = ["The student has uploaded reference material. Use it to ground "
                 "your explanation, examples, and any equations or notation:"]
        for r in _resources:
            snippet = r["content"][:MAX_CONTEXT_PER_RESOURCE]
            note = ""
            if len(r["content"]) > MAX_CONTEXT_PER_RESOURCE:
                note = f" (truncated; showing first {MAX_CONTEXT_PER_RESOURCE} chars)"
            parts.append(f"\n--- BEGIN RESOURCE: {r['name']}{note} ---\n{snippet}\n--- END RESOURCE ---")
        return "\n".join(parts)


# ===================================================================== #
# Anthropic / Claude bridge                                            #
# ===================================================================== #


def anthropic_client():
    """Return an Anthropic client, or None if unavailable."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        # Lazy import — keeps the app runnable without the SDK installed.
        # Pylance/Pyright can't see this is intentional, so suppress the warning.
        import anthropic  # type: ignore[reportMissingImports]
    except ImportError:
        return None
    try:
        return anthropic.Anthropic()
    except Exception:  # noqa: BLE001 - any construction failure means "unavailable"
        return None


def claude_available() -> dict:
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    try:
        import anthropic  # type: ignore[reportMissingImports]  # noqa: F401
        has_sdk = True
    except ImportError:
        has_sdk = False
    return {
        "available": has_key and has_sdk,
        "has_key": has_key,
        "has_sdk": has_sdk,
        "model": ANTHROPIC_MODEL,
    }


# The renderer contract + helper API + worked examples. This is the heart of
# the product: it teaches the model exactly how to write animation code that the
# sandbox can run. It is static, so we cache it as a prompt prefix.
SCENE_SYSTEM_PROMPT = textwrap.dedent(
    r"""
    You are VisualLM, an engine that turns any STEM question, equation, or idea
    into a clear, animated 2D or 3D explanation. You do this by WRITING
    JavaScript animation code that runs in a sandboxed canvas renderer.

    Your output is consumed by a program, not a human. Return ONLY the structured
    fields requested. The most important field is `code`.

    ## The rendering contract

    `code` is the BODY of a function with this exact signature:

        function scene(ctx, t) {
          // your code here
        }

    - `ctx` is a Canvas 2D context. The canvas is already cleared before each
      call, but you may also paint a background.
    - `t` is elapsed time in SECONDS as a float (it respects pause and speed).
      Drive ALL motion from `t` so the animation loops smoothly. Do not keep your
      own frame counter or mutate outer state — `scene` is called ~60 times per
      second and must be a pure function of (ctx, t).
    - `H` is a helper library, available as a global in the worker scope.
      Just reference it directly (e.g. `H.text(...)`); do not declare it.
    - Use `H.W` and `H.H` for the logical width/height of the drawing area.
    - NEVER use: loops without bounds, `while(true)`, `setTimeout`, `setInterval`,
      `requestAnimationFrame`, network calls, DOM, `import`, or `eval`. Keep every
      loop finite and cheap (a few hundred iterations max per frame).
    - Do NOT define `function scene(...)` yourself and do NOT wrap the code in a
      function — provide only the statements that go INSIDE the body.

    ## Hard rules — code that violates these will be REJECTED

    ### Rule 0 — every scene MUST PAINT

    The single biggest failure mode is code that computes but never draws.
    EVERY scene you emit MUST do all three of these:

      1. Call `H.background()` (or `H.clear(...)`) on the FIRST line of the
         body. This guarantees the canvas isn't transparent / stuck black.
      2. Call at least THREE drawing helpers per frame from this set:
         `H.text`, `H.line`, `H.path`, `H.circle`, `H.rect`, `H.arrow`,
         `H.legend`, `H.surface3d`, `H.mesh3d`, any `H.plot2d` view method
         (`.grid()`, `.axes()`, `.fn()`, `.dot()`), or any `cam` method
         (`.line()`, `.path()`, `.poly()`, `.sphere()`, `.grid()`, `.axes()`).
         A `for` loop that calls one of them counts.
      3. Use real on-screen pixel coordinates between 0 and `H.W`/`H.H`. Do
         NOT draw at math coordinates like (-3, 0.5) directly — either go
         through `H.plot2d` (which maps for you) or scale with `H.map(...)`.

    Minimal complete skeleton (use this as a starting point):

        H.background();
        const v = H.plot2d({ xMin: -6, xMax: 6, yMin: -2, yMax: 2 });
        v.grid(); v.axes();
        v.fn(x => Math.sin(x + t), { color: H.colors.accent, width: 3 });
        H.text("Your scene title", 24, 30,
          { color: H.colors.ink, size: 18, weight: 700 });

    If your scene doesn't contain `H.background` AND at least 3 other `H.*`
    drawing calls, the renderer treats it as a failed generation.

    ### Rule 1 — every scene MUST MOVE

    `scene` is called ~60 times per second; the picture only animates if your
    code reads `t`. Scenes that never use `t` are rejected as static images.
    - Drive at least one PRIMARY element from `t`: a moving particle, a
      propagating wave, a sweeping tangent/angle, a growing sum, a rotating
      camera (`cam.yaw = 0.3 * t`), oscillating values.
    - If the concept itself is static (a structure, a proof, a shape), animate
      the EXPLANATION: sweep the highlight through the parts, pulse the region
      being discussed, orbit the camera, or step through stages with
      `const phase = Math.floor(t % 9 / 3);`.
    - KEEP MOVING SUBJECTS IN FRAME. Motion must LOOP, never drift away. Do NOT
      write `x = speed * t` (the object sails off-screen and never comes back).
      Instead oscillate — `x = A * Math.sin(t)` — or wrap — `x = (t * v) % span`
      — or reset a phase with `t % period`. A car passing an observer should
      loop back and pass again; a wave should keep propagating across the SAME
      visible window. If after a few seconds your main subject would leave the
      canvas, the scene is rejected.

    ### Rule 2 — every scene MUST BE LABELED with real values

    A picture without numbers teaches nothing. Scenes with zero `H.text`
    calls are rejected.
    - Title (H.text, size 18, weight 700) at the top-left + a one-line caption
      under it (size 13, H.colors.sub).
    - `view.axes()` (2D) and `cam.axes(len)` (3D) draw numeric tick values
      automatically — use them whenever the scene has coordinates.
    - Label the key quantities ON the drawing (axis names, point coordinates,
      vector names, units).
    - Include at least one LIVE READOUT that changes with `t`, e.g.
      `H.text("E = " + energy.toFixed(2) + " J", 24, 76, { color: H.colors.sub, size: 13 });`
    - With 2+ colored elements, add `H.legend([{label, color}, ...], x, y)`.

    ### Other hard rules — code that violates these will be REJECTED

    The following patterns break the sandbox. Do not produce them under any
    circumstance:
    -  Always call math functions through `Math.*` — write `Math.sin(x)`, not
       `sin(x)`. The only globals available are `Math`, `Number`, `Array`,
       `Object`, `JSON`, `console`, and `H` (the helper library).
    -  Use `H.colors.<name>` only for these exact names: bg, panel, ink, sub,
       grid, axis, accent, accent2, good, warn, violet, yellow. For any other
       color, use a CSS string ("#ffaa00") or `H.hsl(h,s,l)` / `H.color(i)`.
    -  If you need a local name for `H.W` / `H.H` (canvas width / height), use
       different identifiers — e.g. `const w = H.W, h = H.H`. Don't pick `H`
       as your local variable name.
    -  Don't access properties off `undefined`. Every helper call must use one
       of the documented helpers below.

    ## Helper library `H`

    Constants: `H.W`, `H.H`, `H.TAU` (2π), `H.PI`, `H.colors`, `H.palette` (array).
    `H.colors` has: bg, panel, ink (bright text), sub (dim text), grid, axis,
    accent, accent2, good, warn, violet, yellow.

    Math: `H.clamp(x,lo,hi)`, `H.lerp(a,b,t)`, `H.map(x,inMin,inMax,outMin,outMax)`,
    `H.ease(t)` (smoothstep 0..1), `H.color(i)` (palette pick), `H.hsl(h,s,l,a)`.

    Drawing (all coordinates in pixels, origin top-left, y grows downward):
    - `H.clear(color?)` — fill the whole canvas.
    - `H.background(top?, bottom?)` — vertical gradient background.
    - `H.text(str, x, y, {size,color,align,baseline,weight,maxWidth})`.
    - `H.line(x1,y1,x2,y2,{color,width,dash,cap})`.
    - `H.path(points,{color,width,fill,close,dash})` — points is `[[x,y],...]`.
    - `H.circle(x,y,r,{fill,stroke,width})`.
    - `H.rect(x,y,w,h,{fill,stroke,width,radius})`.
    - `H.arrow(x1,y1,x2,y2,{color,width,head})` — line with an arrowhead.
    - `H.legend([{label,color},...], x, y)`.

    2D graphing — `H.plot2d({xMin,xMax,yMin,yMax,pad})` returns a `view`:
    - `view.X(v)` / `view.Y(v)` — map data coords to pixels.
    - `view.grid()` — light grid. `view.axes()` — x/y axes. `view.box` — pixel box.
    - `view.fn(f, {color,width,steps})` — plot `y=f(x)` across the domain.
    - `view.dot(x,y,{r,fill,stroke})` — a data-space marker.
    - Data-space drawing (coordinates in MATH units, not pixels):
      `view.line(x1,y1,x2,y2,opts)`, `view.arrow(x1,y1,x2,y2,opts)`,
      `view.text(str,x,y,opts)`, `view.circle(x,y,rPx,opts)`,
      `view.path([[x,y],...],opts)`, `view.rect(x,y,w,h,opts)` (lower-left
      corner + size in data units). Use these for geometry, annotations, and
      shapes tied to graph coordinates.
    Chain them: `const v = H.plot2d({xMin:-6,xMax:6,yMin:-3,yMax:3}); v.grid(); v.axes(); v.fn(Math.sin);`
    `view.axes()` draws numeric tick values automatically.

    3D — `H.cam3d({yaw,pitch,scale,dist,cx,cy})` returns a `cam`. Convention:
    +y is UP on screen; the ground plane is x/z. Larger `depth` = farther away,
    so painter's algorithm = sort DESCENDING by depth, draw far first.
    - `cam.project([x,y,z])` -> `{x,y,depth,f}` (screen point + depth).
    - `cam.yaw`/`cam.pitch` are settable (rotate the view with `t`).
    - `cam.line(a, b, opts)` — 3D segment between two `[x,y,z]` points.
    - `cam.path(points, opts)` — 3D polyline (orbits, trajectories, curves).
    - `cam.poly(points, {fill,stroke,width})` — filled 3D polygon (you depth-sort).
    - `cam.sphere([x,y,z], r, {color})` — SHADED ball, world-unit radius, any CSS
      color. Returns the projection. For many spheres: depth-sort by
      `cam.project(p).depth` descending, then draw (atoms, planets, particles).
    - `cam.grid(size, step)` — ground-plane grid at y=0 (gives depth perception).
    - `cam.axes(len)` — labeled x/y/z axes.

    SOLID SURFACES — use these instead of point clouds. They render filled,
    light-shaded, depth-sorted meshes that genuinely look 3D:
    - `H.surface3d(cam, (x, y) => height, {xMin,xMax,yMin,yMax,nx,ny,alpha,
      wire,hueMin,hueMax})` — THE way to draw any height function z = f(x,y).
      The returned height is drawn along the screen-up axis; color is mapped
      from height automatically (override with hueMin/hueMax).
    - `H.mesh3d(cam, (u, v) => [x,y,z], {uMin,uMax,vMin,vMax,nu,nv,hue,alpha,
      wire})` — parametric surface: spheres, tori, cylinders, tubes, ribbons,
      Möbius strips. u/v default to [0, TAU]. Use a fixed `hue` (0-360).
      Example sphere: `(u,v) => [Math.cos(u)*Math.sin(v)*R, Math.cos(v)*R,
      Math.sin(u)*Math.sin(v)*R]` with vMin: 0, vMax: Math.PI.
    Keep nx/ny/nu/nv at or below ~40 each (they're capped at 64).

    The user can DRAG the canvas to orbit any 3D scene and scroll to zoom (this
    is automatic). Still give the scene a slow default spin (`cam.yaw = 0.3*t`)
    so it reads as 3D even before they touch it.

    ## Style and pedagogy

    ### Teach the mechanism — do not just solve their problem

    The point of every scene is to help the learner UNDERSTAND, not to be an
    answer key. If the prompt is really a specific problem ("a ball thrown at
    22 m/s at 58 deg, find the range"), do NOT just compute the number and show
    it as the answer — that does the student's work for them. Instead reveal the
    MECHANISM that produces it: the parabola forming, the velocity components,
    why it peaks where it does, so the learner can see the structure and reason
    to the result themselves. Prefer the general relationship over a single
    instance — SWEEP the parameter (let the point `a`, the angle, or the
    harmonic count vary with `t`) so they watch how it behaves across cases, not
    only at their one value. Make labels EXPLAIN ("slope = f'(a): watch it flip
    sign at the peak"), not just state a result; use the bullets and
    student_prompts to provoke prediction, not to spoon-feed the solution.

    This is NOT a license to be vague. Scenes stay concrete, runnable, and
    labeled, and a live readout of a CHANGING quantity is good teaching — it
    makes the relationship visible. The line: illuminate the mechanism (teach)
    vs. hand over the one specific answer to their assigned problem (solve).

    - Teach the idea. Label axes, key points, and quantities with `H.text`.
    - Animate the MECHANISM (a moving particle, sweeping angle, growing sum,
      propagating wave, rotating object), not just a static picture.
    - Use color from `H.colors`/`H.palette`; keep it readable on the dark bg.
    - Title the scene at the top-left and add a one-line caption if helpful.
    - Make it loop or breathe so it looks alive even when the concept is static.
    - Choosing 2D vs 3D: pick 3D whenever the concept lives in space — surfaces
      z=f(x,y), orbits and trajectories, molecules and crystal structures,
      vector fields in space, electromagnetic waves, multivariable calculus,
      rotations. Pick 2D for single-variable functions, time series, circuits,
      graphs/algorithms, and planar geometry. Honor the user's preference when
      given.
    - When you do 3D, make it SOLID: use `H.surface3d` / `H.mesh3d` /
      `cam.sphere` (lit, filled, depth-sorted). Do NOT draw 3D as a cloud of
      flat dots — that reads as 2D. Add `cam.grid()` and `cam.axes()` so depth
      is legible, and a slow `cam.yaw = 0.3 * t` spin.

    ## Worked example 1 — "derivative of x^2 as a moving tangent line" (2D)

    code:
    const v = H.plot2d({ xMin: -3.2, xMax: 3.2, yMin: -1, yMax: 9, pad: 50 });
    v.grid(); v.axes();
    const f = (x) => x * x;
    v.fn(f, { color: H.colors.accent, width: 3 });
    // sweep the point of tangency with time
    const a = 3 * Math.sin(t * 0.6);
    const slope = 2 * a;                 // derivative of x^2
    const tx = (x) => f(a) + slope * (x - a);
    H.line(v.X(-3.2), v.Y(tx(-3.2)), v.X(3.2), v.Y(tx(3.2)),
      { color: H.colors.accent2, width: 2.4, dash: [7, 6] });
    v.dot(a, f(a), { r: 6 });
    H.text("y = x^2", v.X(-3.0), v.Y(8.4), { color: H.colors.accent, size: 16 });
    H.text("slope = 2a = " + slope.toFixed(2), 24, 30,
      { color: H.colors.ink, size: 18, weight: 700 });
    H.text("The tangent line's slope IS the derivative.", 24, 52,
      { color: H.colors.sub, size: 13 });

    ## Worked example 2 — "rotating 3D surface z = sin(r)/r" (3D, SOLID)

    code:
    H.background();
    const cam = H.cam3d({ scale: 34, dist: 16, pitch: -0.55, cy: H.H * 0.54 });
    cam.yaw = 0.35 * t;
    cam.grid(6, 2);
    H.surface3d(cam, (x, y) => {
      const r = Math.sqrt(x * x + y * y) + 1e-6;
      return (Math.sin(r - t) / r) * 4;   // ripple that propagates with t
    }, { xMin: -6, xMax: 6, yMin: -6, yMax: 6, nx: 40, ny: 40 });
    cam.axes(7);
    H.text("z = sin(r - t) / r", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
    H.text("A circular wave radiating from the origin. Drag to orbit.", 24, 52,
      { color: H.colors.sub, size: 13 });

    ## Worked example 3 — "DNA double helix" (3D, spheres + bonds)

    code:
    H.background();
    const cam = H.cam3d({ scale: 36, dist: 18, pitch: -0.2 });
    cam.yaw = 0.5 * t;
    const balls = [];
    const N = 34;
    for (let i = 0; i < N; i++) {
      const s = i / (N - 1);
      const ang = s * H.TAU * 2.1;
      const ypos = (s - 0.5) * 9;
      const a = [2.1 * Math.cos(ang), ypos, 2.1 * Math.sin(ang)];
      const b = [-2.1 * Math.cos(ang), ypos, -2.1 * Math.sin(ang)];
      balls.push({ p: a, color: H.colors.accent, r: 0.32 });
      balls.push({ p: b, color: H.colors.accent2, r: 0.32 });
      if (i % 3 === 0) cam.line(a, b, { color: H.colors.sub, width: 1.6 });
    }
    balls
      .map((o) => ({ ...o, depth: cam.project(o.p).depth }))
      .sort((a, b) => b.depth - a.depth)        // far first
      .forEach((o) => cam.sphere(o.p, o.r, { color: o.color }));
    H.text("DNA double helix", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
    H.text("Two antiparallel strands joined by base pairs.", 24, 52,
      { color: H.colors.sub, size: 13 });

    ## Output fields

    - title: short scene title (<= 60 chars).
    - tag: short subject label, e.g. "Calculus", "Electromagnetism", "Algorithms".
    - dimension: "2D" or "3D".
    - equation: the central equation in plain text (e.g. "y = sin(x)"), or "" if none.
    - summary: one or two sentences on what the animation shows.
    - bullets: exactly 3 short teaching points tied to what is on screen.
    - student_prompts: 3 good follow-up questions a student could ask the tutor.
    - code: the function body described above. Self-contained, runnable, robust.

    Make the code correct and defensive: guard against division by zero, NaN, and
    values outside the visible range. The animation must never throw.

    Correctness rules that are easy to get wrong:
    - Physically nonnegative quantities (lengths, areas, radii, masses,
      probabilities, concentrations) must NEVER display as negative. Don't
      animate them with a bare Math.sin(t) — use a form that stays positive,
      e.g. `2 + Math.sin(t)` or `Math.abs(...)`, and sanity-check every live
      readout you print.
    - Generated code receives NO mouse or keyboard input. Never claim the
      scene is interactive ("drag the vertices", "click to...") in the code,
      summary, or bullets. The ONLY interactivity is the built-in camera
      orbit on 3D scenes, which the app provides automatically.
    - Make sure the numbers you display are consistent with the picture: if
      the readout says a = 3.0, the drawn length must actually be 3 units.
    """
).strip()


SCENE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "tag": {"type": "string"},
        "dimension": {"type": "string", "enum": ["2D", "3D"]},
        "equation": {"type": "string"},
        "summary": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}},
        "student_prompts": {"type": "array", "items": {"type": "string"}},
        "code": {"type": "string"},
    },
    "required": [
        "title",
        "tag",
        "dimension",
        "equation",
        "summary",
        "bullets",
        "student_prompts",
        "code",
    ],
}


def _mode_hint(preferred_mode: str) -> str:
    return {
        "2d": "The user prefers a 2D scene if it fits the concept well.",
        "3d": "The user prefers a 3D scene if it fits the concept well.",
    }.get(preferred_mode, "Pick 2D or 3D, whichever explains the idea best.")


def claude_call_scene(user_blocks: list[dict]) -> dict:
    """Run one structured Claude generation and return the parsed scene dict."""
    client = anthropic_client()
    if client is None:
        raise RuntimeError("Claude is not configured.")

    with client.messages.stream(
        model=ANTHROPIC_MODEL,
        max_tokens=ANTHROPIC_MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={
            "effort": ANTHROPIC_EFFORT,
            "format": {"type": "json_schema", "schema": SCENE_SCHEMA},
        },
        system=[
            {
                "type": "text",
                "text": SCENE_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_blocks}],
    ) as stream:
        message = stream.get_final_message()

    text = next((b.text for b in message.content if b.type == "text"), "")
    if not text:
        raise RuntimeError("Claude returned no visualization.")
    plan = json.loads(text)
    plan["model"] = ANTHROPIC_MODEL
    plan["engine"] = "claude"
    return plan


def generate_with_claude(prompt: str, preferred_mode: str) -> dict:
    resources = resources_context_block()
    user_text = (
        f"Create a STEM visualization for this request:\n\n{prompt}\n\n"
        f"{_mode_hint(preferred_mode)}"
    )
    if resources:
        user_text += "\n\n" + resources
    return claude_call_scene([{"type": "text", "text": user_text}])


def _repair_hint(error: str) -> str:
    """Turn a sandbox error into a targeted fix instruction.

    The repair loop's worst failure mode is the model *rewriting the whole
    scene* and introducing a different bug — so every hint ends with a
    minimal-change directive. The error-class prefix points the model straight
    at the fault. Substring match: sandbox error messages aren't structured.
    """
    e = (error or "").lower()
    if "is not defined" in e:
        specific = (
            "A name was used before it was declared (usually a typo). Declare it "
            "with const/let, or fix the misspelling. Do NOT add other new names."
        )
    elif "is not a function" in e:
        specific = (
            "You called something that isn't a real helper. Use ONLY the helpers "
            "from the contract above (H.*, the plot2d view methods, the cam3d "
            "methods). Delete or replace the invalid call."
        )
    elif "cannot read" in e and ("undefined" in e or "null" in e):
        specific = (
            "You read a property of undefined/null. Guard the access — confirm "
            "the value exists and any array index is in range before using it."
        )
    elif "is not iterable" in e:
        specific = (
            "You looped over or spread a non-array. Ensure the value is an array "
            "(default to []) before iterating."
        )
    elif "unexpected" in e or "syntaxerror" in e or "token" in e:
        specific = (
            "The code did not parse — likely an unbalanced bracket or an "
            "unfinished statement. Return complete, valid JavaScript."
        )
    else:
        specific = "Identify exactly what threw, then fix that specific cause."
    return (
        specific
        + " Make the SMALLEST change that fixes the error: keep every part that "
        "already works, do not rewrite the whole scene, and do not change the "
        "teaching intent."
    )


def repair_with_claude(prompt: str, code: str, error: str) -> dict:
    user_text = (
        "The animation code you wrote threw an error in the sandbox. Fix it and "
        "return the full corrected scene.\n\n"
        f"Original request:\n{prompt}\n\n"
        f"Error:\n{error}\n\n"
        f"How to fix it:\n{_repair_hint(error)}\n\n"
        f"Broken code (function body of scene(ctx, t, H)):\n{code}"
    )
    return claude_call_scene([{"type": "text", "text": user_text}])


# --- Ollama fallback generation (best-effort; lower quality than Claude). ---

OLLAMA_SCENE_PROMPT = (
    SCENE_SYSTEM_PROMPT
    + "\n\nReturn STRICT JSON only with keys: title, tag, dimension, equation, "
    "summary, bullets (array of 3 strings), student_prompts (array of 3 strings), "
    "code (string). No markdown, no commentary."
)


def _extract_json_object(raw_text: str) -> dict:
    text = raw_text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    # Brace-balanced walk: find each complete top-level {...} segment and try
    # to parse it. Handles "prose {a} more {b}" (find+rfind would have sliced
    # both objects into one unparseable blob) and braces inside JSON string
    # values. Raises json.JSONDecodeError so callers (e.g. generate_with_ollama)
    # can decide whether to retry.
    depth = 0
    start = -1
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    try:
                        parsed = json.loads(text[start : i + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        pass  # try the next balanced segment
                    start = -1
    raise json.JSONDecodeError("No parseable JSON object in model output", text, 0)


def generate_with_ollama(prompt: str, preferred_mode: str, fix: dict | None = None) -> dict:
    models = fetch_ollama_models()
    model_name = choose_ollama_model(models)
    if fix:
        user = (
            "Your animation code threw an error. Fix it and return the full scene "
            "as strict JSON.\n\nRequest:\n" + prompt + "\n\nError:\n" + fix["error"]
            + "\n\nHow to fix it:\n" + _repair_hint(fix["error"])
            + "\n\nBroken code:\n" + fix["code"]
        )
    else:
        user = (
            "Create a STEM visualization for this request:\n\n"
            + prompt
            + "\n\n"
            + _mode_hint(preferred_mode)
        )
    resources = resources_context_block()
    if resources:
        user += "\n\n" + resources
    payload = {
        "model": model_name,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": OLLAMA_SCENE_PROMPT},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": 0.2},
        # Tell Ollama to keep the model resident for a while after the
        # call returns. The next visualize/repair won't pay the cold-load.
        "keep_alive": "30m",
    }
    # Retry once on JSON parse failure: `format: json` produces valid JSON
    # most of the time, but sampling occasionally emits unterminated strings
    # / unescaped quotes that break json.loads. A single re-sample at the
    # same temperature usually succeeds and is much cheaper than surfacing
    # a hard "Could not generate" to the user.
    last_parse_err: json.JSONDecodeError | None = None
    for attempt in range(2):
        response = ollama_request(
            "/api/chat",
            payload=payload,
            # Generous timeout: a cold load of a 7B model + a complex JSON-mode
            # generation can take well over 2 minutes the first time. Subsequent
            # calls run in 10-30s.
            timeout=420.0,
        )
        content = response.get("message", {}).get("content")
        if not isinstance(content, str):
            raise RuntimeError("Ollama returned no visualization.")
        try:
            plan = _extract_json_object(content)
        except json.JSONDecodeError as err:
            last_parse_err = err
            continue
        plan["model"] = model_name
        plan["engine"] = "ollama"
        return plan
    # Both attempts produced unparseable JSON — surface the latest parse error.
    raise RuntimeError(
        f"Ollama produced invalid JSON twice in a row: {last_parse_err}"
    )


# ===================================================================== #
# OpenAI / Gemini bridges (optional cloud fallbacks)                    #
# ===================================================================== #
#
# Both speak plain REST via urllib (no SDK needed) and reuse the strict-JSON
# variant of the scene prompt, so adding a key is the only setup required.


def _http_post_json(url: str, payload: dict, headers: dict, timeout: float = 180.0) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace").strip()
        # API error bodies are JSON with a useful "message" — surface just that.
        try:
            parsed = json.loads(details)
            msg = parsed.get("error", {}).get("message") or details
        except (json.JSONDecodeError, AttributeError):
            msg = details
        raise RuntimeError(f"HTTP {error.code}: {msg[:500]}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach {url.split('/', 3)[2]}: {getattr(error, 'reason', error)}") from error


def openai_available() -> dict:
    return {
        "available": bool(os.environ.get("OPENAI_API_KEY")),
        "model": OPENAI_MODEL,
    }


def gemini_available() -> dict:
    return {
        "available": bool(os.environ.get("GEMINI_API_KEY")),
        "model": GEMINI_MODEL,
    }


def _openai_chat(system: str, messages: list[dict], json_mode: bool) -> str:
    payload: dict = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "system", "content": system}] + messages,
        "temperature": 0.3,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    response = _http_post_json(
        f"{OPENAI_BASE_URL}/chat/completions",
        payload,
        {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
    )
    choices = response.get("choices") or []
    content = (choices[0].get("message", {}) or {}).get("content") if choices else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenAI returned no content.")
    return content


def _gemini_generate(system: str, turns: list[dict], json_mode: bool) -> str:
    # Like Claude, Gemini rejects conversations that open with a model turn
    # (the UI seeds chat with one assistant message) — drop leading ones.
    while turns and turns[0].get("role") != "user":
        turns = turns[1:]
    contents = [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in turns
    ]
    payload: dict = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 8192},
    }
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"
    response = _http_post_json(
        f"{GEMINI_BASE_URL}/models/{GEMINI_MODEL}:generateContent",
        payload,
        {"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
    )
    candidates = response.get("candidates") or []
    parts = (candidates[0].get("content", {}) or {}).get("parts", []) if candidates else []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    if not text.strip():
        raise RuntimeError("Gemini returned no content.")
    return text


def _scene_user_text(prompt: str, preferred_mode: str, fix: dict | None) -> str:
    if fix:
        user = (
            "Your animation code threw an error. Fix it and return the full scene "
            "as strict JSON.\n\nRequest:\n" + prompt + "\n\nError:\n" + fix["error"]
            + "\n\nHow to fix it:\n" + _repair_hint(fix["error"])
            + "\n\nBroken code:\n" + fix["code"]
        )
    else:
        user = (
            "Create a STEM visualization for this request:\n\n"
            + prompt
            + "\n\n"
            + _mode_hint(preferred_mode)
        )
    resources = resources_context_block()
    if resources:
        user += "\n\n" + resources
    return user


def generate_with_openai(prompt: str, preferred_mode: str, fix: dict | None = None) -> dict:
    raw = _openai_chat(
        OLLAMA_SCENE_PROMPT,
        [{"role": "user", "content": _scene_user_text(prompt, preferred_mode, fix)}],
        json_mode=True,
    )
    plan = _extract_json_object(raw)
    plan["model"] = OPENAI_MODEL
    plan["engine"] = "openai"
    return plan


def generate_with_gemini(prompt: str, preferred_mode: str, fix: dict | None = None) -> dict:
    raw = _gemini_generate(
        OLLAMA_SCENE_PROMPT,
        [{"role": "user", "content": _scene_user_text(prompt, preferred_mode, fix)}],
        json_mode=True,
    )
    plan = _extract_json_object(raw)
    plan["model"] = GEMINI_MODEL
    plan["engine"] = "gemini"
    return plan


# ===================================================================== #
# Deterministic auto-fixer (no model round-trip)                        #
# ===================================================================== #
#
# The cheapest repair is the one that never calls the model. Local models
# (and occasionally the cloud ones) make a handful of MECHANICAL mistakes that
# we can fix with certainty in microseconds — the biggest being bare math
# calls (`sin(x)` instead of `Math.sin(x)`), the single most common reason a
# 7B scene throws "sin is not defined". Fixing these here means they never
# burn a slow repair attempt.

# Every Math.* function a scene might call bare. Longest names first so the
# alternation never matches a prefix (e.g. `sin` inside `sinh`).
_MATH_FNS = sorted(
    [
        "atan2", "asinh", "acosh", "atanh", "expm1", "log10", "log1p", "log2",
        "cbrt", "sinh", "cosh", "tanh", "asin", "acos", "atan", "sign",
        "trunc", "sqrt", "hypot", "floor", "ceil", "round", "abs", "exp",
        "log", "pow", "min", "max", "sin", "cos", "tan", "random",
    ],
    key=len,
    reverse=True,
)
# A bare math call: the name not preceded by `.`/word-char/`$` (so `Math.sin`
# and `mySin` are skipped) and followed by `(`.
_MATH_FN_RE = re.compile(r"(?<![\w.$])(" + "|".join(_MATH_FNS) + r")(\s*\()")
_BARE_PI_RE = re.compile(r"(?<![\w.$])PI\b")
_BARE_TAU_RE = re.compile(r"(?<![\w.$])TAU\b")

# String literals and comments — code transforms must skip these so a label
# like H.text("compute sin(x)") or a comment isn't rewritten.
_JS_LITERAL_RE = re.compile(
    r'"(?:[^"\\]|\\.)*"'      # double-quoted string
    r"|'(?:[^'\\]|\\.)*'"      # single-quoted string
    r"|`(?:[^`\\]|\\.)*`"      # template literal
    r"|//[^\n]*"               # line comment
    r"|/\*.*?\*/",             # block comment
    re.DOTALL,
)


def _apply_outside_strings(code: str, transform) -> str:
    """Run `transform` only on the code OUTSIDE string literals and comments."""
    out = []
    last = 0
    for m in _JS_LITERAL_RE.finditer(code):
        out.append(transform(code[last : m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(transform(code[last:]))
    return "".join(out)


def _autofix_math(segment: str, declared: frozenset = frozenset()) -> str:
    # Never rewrite a name the scene declares itself: a local `const PI = ...`
    # must not become `const Math.PI = ...` (a syntax error), and a local
    # `function log(){}` must not be rewritten to `Math.log`.
    def _fn(m):
        name = m.group(1)
        return m.group(0) if name in declared else "Math." + name + m.group(2)

    segment = _MATH_FN_RE.sub(_fn, segment)
    if "PI" not in declared:
        segment = _BARE_PI_RE.sub("Math.PI", segment)
    if "TAU" not in declared:
        segment = _BARE_TAU_RE.sub("H.TAU", segment)
    return segment


# Names the scene declares for itself — excluded from the bare-Math rewrite so
# we never corrupt an alias like `const PI = Math.PI` or a local `function sin`.
_DECLARED_RE = re.compile(r"\b(?:const|let|var|function)\s+([A-Za-z_$][\w$]*)")


def autofix_code(code: str) -> str:
    """Mechanically fix high-confidence errors without a model round-trip.

    Currently: prefix bare Math functions/constants (the dominant
    "X is not defined" cause). Applied outside strings/comments so labels and
    comments are never corrupted, and never to a name the scene declares itself
    (so a local `const PI`/`const TAU`/`function log` is left intact rather than
    rewritten into invalid syntax or the wrong call). Idempotent — running it on
    already-correct code is a no-op.
    """
    if not code:
        return code
    try:
        declared = frozenset(_DECLARED_RE.findall(code))
        return _apply_outside_strings(code, lambda seg: _autofix_math(seg, declared))
    except re.error:
        return code


# ===================================================================== #
# Headless scene validator (Node, optional)                             #
# ===================================================================== #
#
# If `node` is on PATH, we run every generated/repaired scene through
# validate_scene.js BEFORE sending it to the browser. That sandboxed run
# (fresh empty V8 context, hard timeout) tells us — in ~50 ms, server-side —
# whether the scene throws, hangs, draws nothing, or lacks labels. This is the
# big latency + reliability win: the browser used to BE the validator, so each
# bad scene cost a full client round-trip + repair. Now we validate and repair
# server-side and hand the browser a scene that already runs.
#
# Degrades gracefully: with no `node`, headless_validate returns None and the
# pipeline falls back to the static gate (scene_problems) + the browser's own
# repair loop, exactly as before.

_NODE_BIN = shutil.which("node")
_VALIDATOR_PATH = BASE_DIR / "validate_scene.js"


def node_validator_available() -> bool:
    return bool(_NODE_BIN) and _VALIDATOR_PATH.exists()


def headless_validate(code: str, timeout: float = 6.0) -> dict | None:
    """Run `code` in the sandboxed Node validator. None = couldn't validate.

    Returns {ok, error, painted, text, paint} on success. None when the
    validator is unavailable or itself failed (so callers skip the gate rather
    than wrongly reject a scene).
    """
    # Rebind to a local so the guard narrows it to `str` for the type checker:
    # Pylance/pyright can't carry the non-None proof across the separate
    # node_validator_available() function (it's a module global). This inline
    # check is De Morgan-equivalent to `not node_validator_available()`.
    node_bin = _NODE_BIN
    if not code or not code.strip() or not node_bin or not _VALIDATOR_PATH.exists():
        return None
    try:
        proc = subprocess.run(
            [node_bin, str(_VALIDATOR_PATH)],
            input=code.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # The validator has its own 2 s in-VM timeout; hitting THIS one means
        # node itself wedged. Treat as a hang so the scene gets repaired.
        return {
            "ok": False,
            "error": "The scene hung (possible infinite loop).",
            "painted": False,
            "text": False,
        }
    except Exception:  # noqa: BLE001 — any spawn failure → "couldn't validate"
        return None
    if proc.returncode != 0:
        return None
    try:
        out = json.loads(proc.stdout.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return out if isinstance(out, dict) else None


_RESERVED_BINDINGS = ("H", "ctx", "t")


def _rewrite_declared_names(span: str) -> str:
    """Inside a `const|let|var ... ;` span, rename reserved binding identifiers.

    Handles all the common forms the model produces:
      const H = ...;
      let H, ctx;
      const W = H.W, H = H.H;       (the multi-decl that causes TDZ)
      const W = H.W,\n      H = H.H;  (multi-line)

    A binding is a reserved name at bracket depth 0 that is either the first
    declarator (right after const/let/var) or follows a top-level comma. This is
    DEPTH-AWARE on purpose: a reserved name used as a VALUE inside ()/[]/{} —
    `H.lerp(a, b, t)`, `[x, t]`, `H.map(x, 0, 10, t)` — is NOT a declarator and
    must be left alone, or it becomes an undefined reference (`_t`). The old
    comma-matching regex renamed those and silently broke very common scenes.
    """
    m = re.match(r"\s*(?:const|let|var)\b", span)
    if not m:
        return span
    reserved = set(_RESERVED_BINDINGS)
    out = [span[: m.end()]]
    i, n = m.end(), len(span)
    depth = 0
    quote = None        # active string/template delimiter, or None
    expect = True       # the next depth-0 identifier is a declarator binding
    while i < n:
        ch = span[i]
        if quote is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(span[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch in "([{":
            depth += 1
            expect = False
            out.append(ch)
            i += 1
            continue
        if ch in ")]}":
            depth -= 1
            out.append(ch)
            i += 1
            continue
        if ch == "," and depth == 0:
            expect = True
            out.append(ch)
            i += 1
            continue
        if expect and depth == 0 and (ch.isalpha() or ch in "_$"):
            j = i
            while j < n and (span[j].isalnum() or span[j] in "_$"):
                j += 1
            ident = span[i:j]
            out.append("_" + ident if ident in reserved else ident)
            expect = False
            i = j
            continue
        if not ch.isspace():
            expect = False
        out.append(ch)
        i += 1
    return "".join(out)


def sanitize_code(code: object) -> str:
    """Coerce model output into a bare scene(ctx, t) function BODY.

    Local 7B models make a few predictable mistakes that break the sandbox:
      1. Wrap the code in `function scene(...) { ... }` despite being told to
         return only the body.
      2. Re-declare `H` / `ctx` / `t` as local variables. The worker exposes
         `H` as a global so simple `const H = ...` shadows are fine, BUT the
         multi-decl form `const W = H.W, H = H.H;` still throws a TDZ
         ReferenceError. We rewrite those bindings to safe names.
      3. Wrap the JSON value in a markdown code fence.
      4. Include `import`/`require` statements (unsupported in the worker).

    Defensive: if any rewrite throws (regex backtracking on adversarial input,
    for example), we fall back to returning the lightly-cleaned code.
    """
    if not isinstance(code, str):
        return ""
    c = code.strip()

    try:
        # Strip a leading/trailing markdown code fence.
        if c.startswith("```"):
            c = re.sub(r"^```[a-zA-Z]*\s*\n?", "", c)
            c = re.sub(r"\n?```$", "", c).strip()

        # Unwrap an explicit `function scene(...) { ... }` declaration.
        match = re.search(r"function\s+scene\s*\([^)]*\)\s*\{", c)
        if match:
            start = match.end()
            end = c.rfind("}")
            if end > start:
                c = c[start:end].strip()

        # Drop unsupported / dangerous top-level constructs.
        c = re.sub(r"^\s*import\s+[^\n]+;?\s*$", "", c, flags=re.MULTILINE)
        c = re.sub(r"^\s*require\s*\([^)]*\)\s*;?\s*$", "", c, flags=re.MULTILINE)

        # Rewrite reserved bindings inside every `const|let|var ... ;` span.
        # Non-greedy match to terminating `;`. Statements without a `;` are
        # tolerated by ASI and we leave them alone (rare in practice).
        c = re.sub(
            r"\b(?:const|let|var)\b[^;]*?;",
            lambda m: _rewrite_declared_names(m.group(0)),
            c,
            flags=re.DOTALL,
        )

        # Deterministically fix bare Math calls / constants. This resolves the
        # most common "X is not defined" throw with ZERO model round-trips.
        c = autofix_code(c)
    except re.error:
        pass

    return c


# Helpers from the worker's `H` library that ACTUALLY paint pixels. If a
# generated scene doesn't call any of them, the canvas stays black no matter
# how long it runs — so we treat that as a generation failure.
_DRAWING_CALLS = (
    "H.background",
    "H.clear",   # only counts if non-default color, but conservatively allow
    "H.text",
    "H.line",
    "H.path",
    "H.circle",
    "H.rect",
    "H.arrow",
    "H.legend",
    # plot2d view methods
    ".grid(",
    ".axes(",
    ".fn(",
    ".dot(",
    # 3D camera + solid-surface helpers
    ".project(",
    ".sphere(",
    ".poly(",
    "H.surface3d",
    "H.mesh3d",
    # Direct canvas calls the model sometimes uses instead of H.*
    "ctx.fillRect",
    "ctx.strokeRect",
    "ctx.fillText",
    "ctx.strokeText",
    "ctx.fill(",
    "ctx.stroke(",
    "ctx.arc(",
)


def code_paints_something(code: str) -> bool:
    """Quick syntactic check that the scene actually calls a drawing helper.

    A 7B model will sometimes emit a scene that sets up variables, runs a
    loop, and computes physics — but never calls any draw helper, leaving
    the canvas black. We can't run JS here, but we can scan for the names
    of every paint-producing helper. If none appear, the scene is blank.
    """
    if not code or not code.strip():
        return False
    return any(needle in code for needle in _DRAWING_CALLS)


# `scene(ctx, t)` is called ~60×/s, but the picture only moves if the code
# actually reads `t`. A bare-word regex is enough: any real use (t * 0.5,
# Math.sin(t), f(x + t)) matches, while identifiers that merely contain a
# t (theta, tris, point) don't.
_T_USAGE_RE = re.compile(r"\bt\b")

# Helpers that put words/numbers on screen. Scenes with zero of these are
# unlabeled pictures — no title, no values — which defeats the teaching goal.
# `.axes(` covers both plot2d and cam3d axes, which render numeric tick labels /
# axis names internally — without it, a correctly-labeled plot that relies on
# axes() and skips a bare H.text title gets a false "unlabeled" flag and a
# wasted regeneration.
_LABEL_CALLS = ("H.text", "H.legend", "fillText", ".axes(")


def code_is_animated(code: str) -> bool:
    return bool(_T_USAGE_RE.search(code or ""))


def code_has_labels(code: str) -> bool:
    return any(needle in (code or "") for needle in _LABEL_CALLS)


def scene_problems(code: str) -> list[str]:
    """Quality gate for generated code: [] means good to ship.

    "blank" is fatal (nothing on screen); "static" and "unlabeled" are
    quality problems worth a regeneration but acceptable as a last resort.
    """
    if not code_paints_something(code):
        return ["blank"]
    problems = []
    if not code_is_animated(code):
        problems.append("static")
    if not code_has_labels(code):
        problems.append("unlabeled")
    return problems


_PROBLEM_HINTS = {
    "blank": (
        "the code never called any drawing helper, so the canvas was BLANK. "
        "You MUST call H.background() first and then several drawing helpers "
        "(H.text/H.line/H.path/H.circle/plot2d/.fn/H.surface3d/...)."
    ),
    "static": (
        "the code never used the time parameter `t`, so NOTHING MOVED. Drive "
        "at least one visible element from `t` every frame — a moving point, "
        "a propagating wave, a sweeping angle, a rotating camera "
        "(cam.yaw = 0.3 * t), or a live numeric readout."
    ),
    "unlabeled": (
        "the scene had NO text labels. Add a title with H.text at the top-left, "
        "label the key quantities on screen, and include at least one live "
        "readout that updates with `t`, e.g. "
        'H.text("v = " + v.toFixed(2), 24, 76, {color: H.colors.sub}).'
    ),
}


def evaluate_scene(code: str) -> dict:
    """Single source of truth for "is this scene good?".

    Prefers the Node validator (authoritative for runtime throws + whether the
    scene actually painted), and falls back to the static gate when node is
    absent. Returns {fatal, error, problems}:
      fatal=True  → the scene throws / hangs / draws nothing. Must be repaired.
      problems=[] → ship it. ['static'|'unlabeled'] → regenerate with feedback.
    """
    val = headless_validate(code)
    if val is None:
        # No runtime validator — fall back to the purely-static gate.
        probs = scene_problems(code)
        if probs == ["blank"]:
            return {
                "fatal": True,
                "error": "The scene didn't call any drawing helper, so the canvas stayed blank.",
                "problems": [],
            }
        return {"fatal": False, "error": None, "problems": probs}
    # Node validator available — authoritative for runtime behaviour.
    if not val.get("ok"):
        return {
            "fatal": True,
            "error": val.get("error") or "The scene threw an error at runtime.",
            "problems": [],
        }
    if not val.get("painted"):
        return {
            "fatal": True,
            "error": (
                "The scene ran but drew nothing (blank canvas). Call H.background() "
                "and then drawing helpers that actually paint."
            ),
            "problems": [],
        }
    if val.get("onscreen") is False:
        return {
            "fatal": True,
            "error": (
                "The content ended up OFF-SCREEN. Two common causes: (1) mixing "
                "coordinate spaces — H.line/H.circle/H.text take PIXEL coords "
                "(0..H.W, 0..H.H), while the plot2d view methods "
                "(v.line/v.text/v.dot/v.path) take DATA coords and map them for "
                "you, so never wrap their args in v.X()/v.Y(); (2) UNBOUNDED "
                "motion that drifts away — e.g. pos = t*4 sails off the edge. "
                "Make motion LOOP: use t % period, Math.sin(t), or keep the "
                "moving subject within the visible range. Keep the main content "
                "on-canvas the whole time."
            ),
            "problems": [],
        }
    problems = []
    if not code_is_animated(code):
        problems.append("static")
    if not (val.get("text") or code_has_labels(code)):
        problems.append("unlabeled")
    return {"fatal": False, "error": None, "problems": problems}


def normalize_scene(plan: dict, prompt: str) -> dict:
    def s(key, default=""):
        v = plan.get(key)
        return v.strip() if isinstance(v, str) else default

    def arr(key, n):
        v = plan.get(key)
        out = [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []
        return out[:n]

    dimension = "3D" if s("dimension").lower().startswith("3") else "2D"
    bullets = arr("bullets", 4) or [
        "This animation was generated for your exact prompt.",
        "It shows the core relationship as something you can watch move.",
        "Ask the tutor to connect the picture to the formula or to a worked example.",
    ]
    prompts = arr("student_prompts", 4) or [
        f"Explain this visualization of: {prompt}",
        "What should I notice first in this animation?",
        "Give me one practice problem about this idea and solve it.",
    ]
    return {
        "title": s("title") or "STEM Visualization",
        "tag": s("tag") or "STEM",
        "dimension": dimension,
        "equation": s("equation"),
        "summary": s("summary") or "An AI-generated animation of your prompt.",
        "bullets": bullets,
        "student_prompts": prompts,
        "code": sanitize_code(plan.get("code")),
        "model": plan.get("model", ""),
        "engine": plan.get("engine", ""),
        "prompt": prompt,
    }


# A handwritten, guaranteed-renderable scene used when every generator and
# every retry produces a blank scene. It draws the prompt text + a calming
# animated diagram so the user never just stares at a black canvas.
_FALLBACK_CODE = r"""
H.background();
const title = "Generation didn't draw anything";
const sub = "The local model produced blank code. Try the prompt again, or use Claude for stronger results.";
H.text(title, 28, 38, { color: H.colors.ink, size: 20, weight: 700 });
H.text(sub, 28, 62, { color: H.colors.sub, size: 13 });
// A breathing circle so the screen isn't static.
const cx = H.W / 2, cy = H.H / 2 + 20;
const r = 60 + 18 * Math.sin(t * 1.5);
H.circle(cx, cy, r, { stroke: H.colors.accent, width: 3 });
H.circle(cx, cy, r * 0.6, { stroke: H.colors.accent2, width: 2 });
H.circle(cx, cy, 6, { fill: H.colors.ink });
H.text("Tip: include words like 'show', 'plot', 'animate' in the prompt.",
  28, H.H - 28, { color: H.colors.sub, size: 12 });
""".strip()


def _fallback_scene(prompt: str, reason: str) -> dict:
    return {
        "title": "Couldn't render this prompt",
        "tag": "Fallback",
        "dimension": "2D",
        "equation": "",
        "summary": reason,
        "bullets": [
            "The model produced code that didn't paint anything visible.",
            "Try rephrasing the prompt to be more concrete and visual.",
            "For best results, set ANTHROPIC_API_KEY to use Claude as the generator.",
        ],
        "student_prompts": [
            "Why did the local model fail on this prompt?",
            "What's a good rephrasing that would produce a better animation?",
            "Explain the concept in plain text since we don't have a visualization.",
        ],
        "code": _FALLBACK_CODE,
        "model": "fallback",
        "engine": "fallback",
        "prompt": prompt,
        "is_fallback": True,
    }


def _repair_feedback(error: str, code: str) -> str:
    """A feedback block that turns the next generation into a targeted repair.

    Folding the runtime error + the broken code into the prompt lets us drive a
    server-side fix through the SAME generate function (keeping _try_generate
    provider-agnostic) without a separate repair call path.
    """
    return (
        "\n\nCRITICAL: your previous code FAILED to run in the sandbox.\n"
        f"Error: {error}\n"
        f"How to fix it: {_repair_hint(error)}\n"
        "Return a corrected, complete scene. Broken code was:\n" + (code or "")
    )


def _try_generate(
    fn, prompt: str, preferred_mode: str, label: str, max_attempts: int = 3
) -> dict:
    """Generate, validate server-side, and retry with targeted feedback.

    Every candidate is run through evaluate_scene (the Node validator when
    available, else the static gate), which classifies it as:
      fatal      — throws / hangs / draws nothing. We regenerate with the exact
                   runtime error + the broken code folded into the prompt, so
                   the model performs a precise fix. After max_attempts we raise.
      static     — never reads `t`, so it's a still image.
      unlabeled  — no title / values / readouts.
    static/unlabeled regenerate with a hint naming what was missing; if the
    last attempt still trips them, we ship it anyway, annotated, so the user
    gets a working (if imperfect) scene instead of an error.

    The deterministic auto-fixer runs inside normalize_scene, so mechanically
    fixable faults (bare Math.*) are resolved here with ZERO extra model calls.

    max_attempts is generator-aware: strong cloud models almost never trip the
    gate, so 2 keeps a single corrective retry; weak local models keep 3.
    """
    best_imperfect = None  # most recent paints-but-imperfect scene
    scene = normalize_scene(fn(prompt, preferred_mode), prompt)
    last_error = None
    for attempt in range(max_attempts):
        ev = evaluate_scene(scene.get("code", ""))
        if not ev["fatal"] and not ev["problems"]:
            if attempt > 0:
                scene["recovered_after_retry"] = attempt
            return scene
        if not ev["fatal"]:
            scene["quality_warnings"] = ev["problems"]
            best_imperfect = scene
        if attempt == max_attempts - 1:
            break
        # Regenerate with feedback. Fatal → repair the exact fault; quality →
        # name what was missing. Always feed back off the ORIGINAL prompt so
        # complaints don't pile up across attempts.
        if ev["fatal"]:
            last_error = ev["error"]
            feedback = _repair_feedback(ev["error"], scene.get("code", ""))
        else:
            complaints = " ALSO, ".join(_PROBLEM_HINTS[p] for p in ev["problems"])
            feedback = "\n\nCRITICAL FEEDBACK on your previous attempt: " + complaints
        scene = normalize_scene(fn(prompt + feedback, preferred_mode), prompt)
    if best_imperfect is not None:
        return best_imperfect
    raise RuntimeError(
        f"{label} couldn't produce a runnable scene after {max_attempts} attempts"
        + (f" (last error: {last_error})" if last_error else "")
        + ". Try a different prompt, or use a stronger model (ANTHROPIC_API_KEY)."
    )


def _cloud_generators() -> list[tuple[str, object]]:
    """Available cloud generators, best-first: Claude > OpenAI > Gemini."""
    chain: list[tuple[str, object]] = []
    if claude_available()["available"]:
        chain.append(("Claude", generate_with_claude))
    if openai_available()["available"]:
        chain.append(("OpenAI", generate_with_openai))
    if gemini_available()["available"]:
        chain.append(("Gemini", generate_with_gemini))
    return chain


# ===================================================================== #
# Curated STEM scene library + validated-scene cache                    #
# ===================================================================== #
#
# The fastest, most reliable scene is one we don't have to generate. Two
# layers sit in front of the model:
#   1. An exact-prompt cache of scenes that already passed validation, so a
#      repeated prompt (or a shared link) renders instantly.
#   2. A curated library of hand-verified scenes across STEM domains. A strong
#      keyword match short-circuits to an instant, known-correct animation —
#      this is the practical, retrieval-augmented version of "feed it STEM
#      data": a vetted corpus the matcher draws on instead of training a model.

try:
    from scene_library import SCENE_LIBRARY  # type: ignore
except Exception:  # noqa: BLE001 — library is optional; never block startup
    SCENE_LIBRARY = []

# Parameterized "interactive textbook" demos (Algebra 1 -> Precalculus). When a
# prompt classifies to a curriculum topic, we show one of these — the student
# edits its values live (the `params`) and reads the explanation — instead of
# generating code. This is the retrieval-first, fill-in-the-values path.
try:
    from demo_library import DEMO_LIBRARY  # type: ignore
except Exception:  # noqa: BLE001 — optional; never block startup
    DEMO_LIBRARY = []

_scene_cache_lock = threading.Lock()
_scene_cache: dict[tuple, dict] = {}
_SCENE_CACHE_MAX = 256


def _cache_key(prompt: str, mode: str) -> tuple:
    return (mode, re.sub(r"\s+", " ", prompt.strip().lower()))


def scene_cache_get(prompt: str, mode: str) -> dict | None:
    with _scene_cache_lock:
        hit = _scene_cache.get(_cache_key(prompt, mode))
        return dict(hit) if hit else None


def scene_cache_put(prompt: str, mode: str, scene: dict) -> None:
    # Only cache CLEAN scenes: never a fallback or a known-imperfect one, so a
    # later retry still gets a chance at something better.
    if not scene or scene.get("is_fallback") or scene.get("quality_warnings"):
        return
    with _scene_cache_lock:
        if len(_scene_cache) >= _SCENE_CACHE_MAX:
            _scene_cache.pop(next(iter(_scene_cache)))
        _scene_cache[_cache_key(prompt, mode)] = dict(scene)


def _tokenize(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


# Common words that shouldn't drive a topic match on their own.
_MATCH_STOPWORDS = frozenset(
    "the a an of in on to and or is are show me how visualize animate explain "
    "draw plot with for as its it this that what why over time using see".split()
)


def _scene_score(sc: dict, ptext: str, ptoks: set, mode: str) -> float:
    score = 0.0
    for kw in sc.get("keywords", []):
        k = kw.lower().strip()
        if not k:
            continue
        if " " in k:  # multi-word phrase: a contiguous hit is a strong signal
            if k in ptext:
                score += 2.0
        elif k in ptoks:
            score += 1.0
    # Title and tag words are strong topic signals (minus generic stopwords).
    title_toks = _tokenize(sc.get("title", "")) - _MATCH_STOPWORDS
    tag_toks = _tokenize(sc.get("tag", "")) - _MATCH_STOPWORDS
    score += 1.0 * len(title_toks & ptoks)
    score += 0.5 * len(tag_toks & ptoks)
    # Respect an explicit 2D/3D preference.
    if mode in ("2d", "3d") and sc.get("dimension", "").lower() != mode:
        score -= 1.5
    return score


def _library_scored(prompt: str, mode: str) -> list[tuple[dict, float]]:
    """All library scenes scored against the prompt, best first (score > 0)."""
    if not SCENE_LIBRARY:
        return []
    ptext = " " + re.sub(r"\s+", " ", (prompt or "").lower()) + " "
    ptoks = _tokenize(prompt) - _MATCH_STOPWORDS
    scored = [(sc, _scene_score(sc, ptext, ptoks, mode)) for sc in SCENE_LIBRARY]
    scored = [t for t in scored if t[1] > 0]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


def library_match(prompt: str, mode: str) -> tuple[dict | None, float]:
    """Best curated scene for this prompt + its match score (0 = no match)."""
    scored = _library_scored(prompt, mode)
    return scored[0] if scored else (None, 0.0)


def _library_scene(sc: dict, prompt: str) -> dict:
    return {
        "title": sc.get("title", "STEM Visualization"),
        "tag": sc.get("tag", "STEM"),
        "dimension": "3D" if str(sc.get("dimension", "")).lower().startswith("3") else "2D",
        "equation": sc.get("equation", ""),
        "summary": sc.get("summary", ""),
        "bullets": [str(b) for b in sc.get("bullets", [])][:4],
        "student_prompts": [str(p) for p in sc.get("student_prompts", [])][:4],
        "code": sanitize_code(sc.get("code", "")),
        "model": "curated",
        "engine": "library",
        "prompt": prompt,
        "from_library": True,
    }


def _has_cloud() -> bool:
    return bool(_cloud_generators())


# --- Parameterized demo classification (the "fill in the values" path) -------

def _demo_scored(prompt: str) -> list[tuple[dict, float]]:
    """All demos scored against the prompt, best first (score > 0). Reuses the
    library scorer; mode is 'auto' so a 2D demo isn't penalized by a 3D hint."""
    if not DEMO_LIBRARY:
        return []
    ptext = " " + re.sub(r"\s+", " ", (prompt or "").lower()) + " "
    ptoks = _tokenize(prompt) - _MATCH_STOPWORDS
    scored = [(d, _scene_score(d, ptext, ptoks, "auto")) for d in DEMO_LIBRARY]
    scored = [t for t in scored if t[1] > 0]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


def demo_match(prompt: str) -> tuple[dict | None, float]:
    """Classify a prompt to its best curriculum demo (None = no clear topic)."""
    scored = _demo_scored(prompt)
    return scored[0] if scored else (None, 0.0)


def _demo_scene(demo: dict, prompt: str) -> dict:
    """Shape a demo into a scene response carrying its editable `params` and the
    teaching `explanation` the UI renders alongside the live graph."""
    expl = demo.get("explanation", "")
    bullets = [str(b) for b in demo.get("bullets", [])][:4] or [
        "Drag the sliders on the right and watch the graph respond.",
        "The picture updates live as you change each value.",
    ]
    return {
        "title": demo.get("title", "Interactive demo"),
        "tag": demo.get("area", "STEM"),
        "dimension": "3D" if str(demo.get("dimension", "")).lower().startswith("3") else "2D",
        "equation": demo.get("equation", ""),
        "summary": expl,
        "bullets": bullets,
        "student_prompts": [str(p) for p in demo.get("student_prompts", [])][:4] or [
            "Why does changing this value have that effect on the graph?",
            "What happens at the extreme settings?",
            "How does the picture connect back to the formula?",
        ],
        "code": sanitize_code(demo.get("code", "")),
        "params": [dict(p) for p in demo.get("params", [])],
        "explanation": expl,
        "topic": demo.get("topic", ""),
        "area": demo.get("area", ""),
        "demo_id": demo.get("id", ""),
        "model": "demo",
        "engine": "demo",
        "prompt": prompt,
        "from_demo": True,
    }


# Demo fires on a clear topic hit (a couple of keyword/title matches). Below
# this, fall through to the scene library / generative path.
_DEMO_THRESHOLD = 2.0


def plan_visualization(prompt: str, preferred_mode: str) -> dict:
    # 1. Exact-prompt cache — instant repeat for an already-validated scene.
    cached = scene_cache_get(prompt, preferred_mode)
    if cached:
        cached["cached"] = True
        return cached

    # 1.5 Curriculum demo — the interactive "fill in the values" path. If the
    #     prompt clearly names an Algebra-1..Precalc topic, show its parameterized
    #     demo (editable + explained) rather than generating code. Takes priority
    #     over the static library so an interactive version wins when both exist.
    demo, demo_score = demo_match(prompt)
    if demo is not None and demo_score >= _DEMO_THRESHOLD:
        return _demo_scene(demo, prompt)

    # 2. Strong curated match — instant, known-correct. The bar is high when a
    #    cloud model is available (the user likely wants a custom take), and
    #    lower when we'd otherwise lean on the slow/weak local model. A
    #    "dominance" gap guards against ambiguous matches: the top scene must
    #    clearly beat the runner-up before we short-circuit to it.
    scored = _library_scored(prompt, preferred_mode)
    lib_scene, lib_score = scored[0] if scored else (None, 0.0)
    runner_up = scored[1][1] if len(scored) > 1 else 0.0
    strong_threshold = 6.0 if _has_cloud() else 2.5
    # A clearly on-topic match (high absolute score) fast-paths regardless of
    # ties — a 9-point Fourier match is right even if a second Fourier scene
    # also scores high. The dominance gap only guards BORDERLINE matches from
    # firing on an ambiguous near-tie between unrelated scenes. Base scenes are
    # ordered first, so they win ties.
    confident = lib_score >= 5.0 or (lib_score - runner_up) >= 1.5
    if lib_scene is not None and lib_score >= strong_threshold and confident:
        result = _library_scene(lib_scene, prompt)
        scene_cache_put(prompt, preferred_mode, result)
        return result

    # 3. Generate with the provider chain (each validated + repaired server-side).
    errors = []
    for label, fn in _cloud_generators():
        try:
            scene = _try_generate(fn, prompt, preferred_mode, label, max_attempts=2)
            scene_cache_put(prompt, preferred_mode, scene)
            return scene
        except Exception as error:  # noqa: BLE001
            errors.append(f"{label}: {error}")
    try:
        scene = _try_generate(
            lambda p, m: generate_with_ollama(p, m),
            prompt,
            preferred_mode,
            "Ollama",
            max_attempts=3,
        )
        scene_cache_put(prompt, preferred_mode, scene)
        return scene
    except Exception as error:  # noqa: BLE001
        errors.append(f"Ollama: {error}")

    # 4. Every generator failed. A RELEVANT curated scene beats a dead canvas —
    #    but a wrong-topic one is worse than an honest placeholder, so require a
    #    moderate match (not just any score > 0).
    if lib_scene is not None and lib_score >= 2.0:
        result = _library_scene(lib_scene, prompt)
        result["fallback_reason"] = (
            "The live generator couldn't produce a runnable scene, so here's the "
            "closest curated STEM animation."
        )
        return result

    detail = " | ".join(errors) if errors else "no backend available"
    # A backend that was REACHABLE but produced unrunnable code is "soft" — show
    # the animated placeholder + an explanation rather than a hard error.
    # UNREACHABLE backends (connection/timeout/auth) are "hard" — surface them.
    def _is_hard(e: str) -> bool:
        e = e.lower()
        return any(
            k in e
            for k in (
                "timed out", "timeout", "connection", "could not reach",
                "no content", "http ", "api key", "invalid json", "not configured",
            )
        )

    if errors and not all(_is_hard(e) for e in errors):
        return _fallback_scene(
            prompt,
            "The generator's code kept failing to run. Rephrase the prompt, or "
            "enable a stronger model (ANTHROPIC_API_KEY / OPENAI_API_KEY / "
            "GEMINI_API_KEY) for more reliable results.",
        )
    if any("timed out" in e.lower() or "timeout" in e.lower() for e in errors):
        hint = (
            "The local model probably hit a cold-start timeout. Try again — "
            "the model is loaded now and the next call will be much faster."
        )
    elif any("connection" in e.lower() or "could not reach" in e.lower() for e in errors):
        hint = "Start Ollama (`ollama serve`) or set ANTHROPIC_API_KEY for Claude."
    else:
        hint = (
            "Set ANTHROPIC_API_KEY (and `pip install anthropic`), "
            "OPENAI_API_KEY, or GEMINI_API_KEY — or run Ollama locally."
        )
    raise RuntimeError(f"Generator failed ({detail}). {hint}")


def repair_visualization(prompt: str, code: str, error: str, where: str = "") -> dict:
    errors = []
    # `where` is the offending source line the sandbox pulled from the stack
    # trace (see sandbox-worker.js offendingLine). Folding it into the error text
    # points every repair provider straight at the failing line.
    error_ctx = error + (f"\n\nThe error was thrown at: {where}" if where else "")
    if claude_available()["available"]:
        try:
            return normalize_scene(repair_with_claude(prompt, code, error_ctx), prompt)
        except Exception as e:  # noqa: BLE001
            errors.append(f"Claude: {e}")
    for label, avail, fn in (
        ("OpenAI", openai_available, generate_with_openai),
        ("Gemini", gemini_available, generate_with_gemini),
    ):
        if not avail()["available"]:
            continue
        try:
            return normalize_scene(
                fn(prompt, "auto", fix={"code": code, "error": error_ctx}), prompt
            )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{label}: {e}")
    try:
        return normalize_scene(
            generate_with_ollama(prompt, "auto", fix={"code": code, "error": error_ctx}),
            prompt,
        )
    except Exception as e:  # noqa: BLE001
        errors.append(f"Ollama: {e}")
    raise RuntimeError("Repair failed. " + " | ".join(errors))


# ===================================================================== #
# Tutor chat (Ollama primary, Claude fallback)                          #
# ===================================================================== #


def normalize_history(history: object) -> list[dict]:
    if not isinstance(history, list):
        return []
    out = []
    for item in history[-6:]:
        if not isinstance(item, dict):
            continue
        role, content = item.get("role"), item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content.strip()[:3000]})
    return out


def build_tutor_system_prompt(viz: dict) -> str:
    bullets = viz.get("bullets") or []
    bullet_lines = "\n".join(f"- {b}" for b in bullets[:4]) or "- (none provided)"
    base = textwrap.dedent(
        f"""
        You are VisualLM Tutor, a patient STEM tutor helping a student understand
        a live animation that is on screen right now.

        Teaching style:
        - Warm, clear, and student-friendly. Tie explanations to the animation.
        - Short step-by-step reasoning for math/physics.
        - End with one short follow-up question or practice suggestion.

        SOLVING A PROBLEM — when the student asks you to solve, find, calculate,
        derive, or "how do I do this", do NOT just give the final answer. Walk
        through the METHOD so they could repeat it themselves, using exactly
        these labeled sections (each label on its own line, plain text):

        Goal: one line naming what we solve for — its symbol and unit.

        What you need: the relationship(s)/formula(s) that apply, plus every
        known quantity. For each known, give symbol = value (with unit) and say
        WHERE it comes from: stated in the problem, a known constant, or read
        off the animation on screen. Call out anything still unknown.

        Steps: numbered. Each step does ONE thing — say what you do and WHY,
        substitute the specific values you need RIGHT THERE, and show the
        intermediate result with units. When a step corresponds to something on
        screen, point to it (e.g. "this is the slope of the tangent line you
        see sweeping the curve").

        Answer: the final result with units, then a one-line sanity check (does
        the sign/size make sense?).

        If the student gave no numbers, solve it symbolically and show exactly
        where each quantity would be plugged in. Keep it focused; still end with
        one short follow-up question.

        Output format — STRICT. The chat window shows plain text only.
        - NO LaTeX of any kind. Do not write \\(...\\), \\[...\\], $...$,
          \\frac{{a}}{{b}}, \\sqrt{{x}}, \\sum, \\int, \\alpha, \\theta, \\pi,
          or any other backslash command. They render as literal junk.
        - NO Markdown bold (no **foo**), italics (no *foo*), headers (no ###),
          or tables.
        - Write equations as plain text on their own line. Examples:
            GOOD:  dF/dt = -30
            BAD:   \\frac{{dF}}{{dt}} = -30
            GOOD:  F(t) = F0 - 30 * t
            BAD:   $F(t) = F_0 - 30t$
            GOOD:  theta = pi / 4
            BAD:   \\theta = \\frac{{\\pi}}{{4}}
        - Use ^ for exponents (x^2), / for division (a/b), * for multiplication.
        - Greek letters: spell them out as words (alpha, theta, omega, Delta).
        - Numbered steps and bulleted lists are fine — write them as
          "1. Sentence." or "- Sentence." but do NOT bold the leading words.

        Current visualization:
        - Title: {viz.get('title') or 'STEM concept'}
        - Subject: {viz.get('tag') or 'STEM'}  ({viz.get('dimension') or '2D'})
        - Equation: {viz.get('equation') or 'none given'}
        - Summary: {viz.get('summary') or 'n/a'}
        - Student's original prompt: {viz.get('prompt') or 'n/a'}
        - Key teaching points:
        {bullet_lines}
        """
    ).strip()
    resources = resources_context_block()
    if resources:
        base += "\n\n" + resources
    return base


def chat_with_ollama(question: str, viz: dict, history: list[dict]) -> dict:
    models = fetch_ollama_models()
    model_name = choose_ollama_model(models)
    messages = [{"role": "system", "content": build_tutor_system_prompt(viz)}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})
    response = ollama_request(
        "/api/chat",
        payload={
            "model": model_name,
            "stream": False,
            "messages": messages,
            "options": {"temperature": 0.3},
            "keep_alive": "30m",
        },
        timeout=240.0,
    )
    raw = response.get("message", {}).get("content")
    answer = raw.strip() if isinstance(raw, str) else ""
    if not answer:
        raise RuntimeError("Ollama returned an empty response.")
    return {"answer": answer, "model": model_name, "engine": "ollama"}


def chat_with_claude(question: str, viz: dict, history: list[dict]) -> dict:
    client = anthropic_client()
    if client is None:
        raise RuntimeError("Claude is not configured.")
    # Claude's Messages API requires the conversation to start with a `user`
    # turn. seedTutorForScene seeds the UI with a single assistant message, so
    # the first follow-up question arrives with history=[assistant]; we must
    # drop any leading assistant turns or the API rejects the call.
    trimmed = list(history)
    while trimmed and trimmed[0].get("role") != "user":
        trimmed.pop(0)
    messages = trimmed + [{"role": "user", "content": question}]
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2000,
        system=build_tutor_system_prompt(viz),
        messages=messages,
    )
    answer = next((b.text for b in response.content if b.type == "text"), "").strip()
    if not answer:
        raise RuntimeError("Claude returned an empty response.")
    return {"answer": answer, "model": ANTHROPIC_MODEL, "engine": "claude"}


def tutor_chat(question: str, viz: dict, history: list[dict]) -> dict:
    errors = []
    # Previously did ollama_available() (probe /api/tags) THEN chat_with_ollama()
    # (which also fetches /api/tags) — same duplicate-call issue as Bug #45.
    # Trying chat_with_ollama directly fails just as fast on a refused
    # connection because fetch_ollama_models has its own 10 s timeout.
    try:
        return chat_with_ollama(question, viz, history)
    except Exception as e:  # noqa: BLE001
        errors.append(f"Ollama: {e}")
    if claude_available()["available"]:
        try:
            return chat_with_claude(question, viz, history)
        except Exception as e:  # noqa: BLE001
            errors.append(f"Claude: {e}")
    if openai_available()["available"]:
        try:
            answer = _openai_chat(
                build_tutor_system_prompt(viz),
                history + [{"role": "user", "content": question}],
                json_mode=False,
            )
            return {"answer": answer.strip(), "model": OPENAI_MODEL, "engine": "openai"}
        except Exception as e:  # noqa: BLE001
            errors.append(f"OpenAI: {e}")
    if gemini_available()["available"]:
        try:
            answer = _gemini_generate(
                build_tutor_system_prompt(viz),
                history + [{"role": "user", "content": question}],
                json_mode=False,
            )
            return {"answer": answer.strip(), "model": GEMINI_MODEL, "engine": "gemini"}
        except Exception as e:  # noqa: BLE001
            errors.append(f"Gemini: {e}")
    if not errors:
        # No backend is configured. Give the same actionable hint that
        # plan_visualization gives, otherwise the user sees a dead end.
        raise RuntimeError(
            "No tutor backend is available. Start Ollama (`ollama serve`) "
            "or set ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY."
        )
    raise RuntimeError("Tutor unavailable. " + " | ".join(errors))


# ===================================================================== #
# HTTP handler                                                          #
# ===================================================================== #


def get_health() -> dict:
    # Single Ollama probe — was making 2 HTTP calls per request: ollama_available()
    # calls fetch_ollama_models() internally, then we called it AGAIN to populate
    # the model list. With Bug #19's refresh-on-error this fired often enough to
    # matter. Now we fetch once and derive availability from success/failure.
    ollama_status = {"available": False, "url": OLLAMA_URL, "error": None}
    try:
        models = fetch_ollama_models()
        ollama_status["available"] = True
        ollama_status["selected_model"] = choose_ollama_model(models)
        ollama_status["models"] = [m.get("name") for m in models]
    except RuntimeError as error:
        ollama_status["error"] = str(error)
    # claude_available() does no I/O (env var + import probe) but was still
    # called twice — once for the dict, once for the generator switch.
    claude_info = claude_available()
    openai_info = openai_available()
    gemini_info = gemini_available()
    if claude_info["available"]:
        generator = "claude"
    elif openai_info["available"]:
        generator = "openai"
    elif gemini_info["available"]:
        generator = "gemini"
    elif ollama_status["available"]:
        generator = "ollama"
    else:
        generator = "none"
    return {
        "ollama": ollama_status,
        "claude": claude_info,
        "openai": openai_info,
        "gemini": gemini_info,
        "generator": generator,
        "access_code_required": bool(ACCESS_CODE),
        # Reliability/speed layers, surfaced so the UI (and ops) can see them.
        "validator": node_validator_available(),
        "library_size": len(SCENE_LIBRARY),
    }


class VisualLMHandler(SimpleHTTPRequestHandler):
    # Cap per-request socket reads so a malicious / hung client that declares
    # Content-Length: N but only sends part of it can't pin a worker thread
    # forever on rfile.read(N). 30 s is far more than any legitimate body
    # (the slow path is a Claude/Ollama call, which happens server-side after
    # the body is fully read). Without this, ThreadingHTTPServer's default
    # socket timeout is None — the thread hangs until TCP keepalive expires.
    timeout = 30

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def end_headers(self) -> None:
        # Local development: never let the browser cache the UI. This avoids
        # the classic "I shipped new CSS but you're seeing the old gradient"
        # problem when iterating quickly. send_json() builds its own response
        # so this only applies to static-file serving from SimpleHTTPRequestHandler.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        # frame-ancestors via the meta-tag CSP (Bug #23) is silently IGNORED
        # by browsers per the CSP spec — it only takes effect as a response
        # header. Without this, an attacker page could iframe us for a
        # clickjacking attack. X-Frame-Options: DENY is the legacy form
        # supported even in older browsers.
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            send_json(self, HTTPStatus.OK, get_health())
            return
        if parsed.path == "/api/resources":
            send_json(self, HTTPStatus.OK, {"resources": list_resources()})
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if not rate_limit_ok(self.client_ip()):
            send_json(self, HTTPStatus.TOO_MANY_REQUESTS, {"error": "Rate limit exceeded."})
            return
        if not access_code_ok(self.headers.get("X-Access-Code")):
            send_json(
                self,
                HTTPStatus.UNAUTHORIZED,
                {"error": "Access code required.", "code_required": True},
            )
            return
        if parsed.path.startswith("/api/resources/"):
            resource_id = parsed.path.split("/", 3)[3]
            ok = delete_resource(resource_id)
            if not ok:
                send_json(self, HTTPStatus.NOT_FOUND, {"error": "Resource not found."})
                return
            send_json(self, HTTPStatus.OK, {"resources": list_resources()})
            return
        send_json(self, HTTPStatus.NOT_FOUND, {"error": "Unknown route."})

    def client_ip(self) -> str:
        # Cloud hosts (Render, Fly, etc.) terminate TLS at a proxy, so the
        # socket peer is the proxy and the real client is in X-Forwarded-For.
        # Locally there's no proxy and the header is absent.
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        routes = {"/api/visualize", "/api/repair", "/api/chat", "/api/resources"}
        if parsed.path not in routes:
            send_json(self, HTTPStatus.NOT_FOUND, {"error": "Unknown API route."})
            return
        if not rate_limit_ok(self.client_ip()):
            send_json(
                self,
                HTTPStatus.TOO_MANY_REQUESTS,
                {"error": f"Rate limit exceeded ({RATE_LIMIT_PER_MIN} requests/min). Wait a moment and try again."},
            )
            return
        if not access_code_ok(self.headers.get("X-Access-Code")):
            send_json(
                self,
                HTTPStatus.UNAUTHORIZED,
                {"error": "Access code required.", "code_required": True},
            )
            return
        try:
            payload = read_json_body(self)
        except (json.JSONDecodeError, UnicodeDecodeError):
            send_json(self, HTTPStatus.BAD_REQUEST, {"error": "Body must be valid UTF-8 JSON."})
            return
        if not isinstance(payload, dict):
            # A bare JSON list / string / null would slip past the parser and
            # later AttributeError on payload.get(...) — return a clear 400.
            send_json(self, HTTPStatus.BAD_REQUEST, {"error": "Body must be a JSON object."})
            return

        # Last-resort guard. Handlers catch their own *expected* errors (bad
        # input -> 400, generator failure -> 503). An UNEXPECTED exception (a
        # bug, a new SDK error type) must not escape do_POST — that drops the
        # client connection with a bare stderr traceback and no response. Log
        # it and return a clean 500. Handlers do their heavy work before
        # sending anything, so no response has started when we land here.
        try:
            if parsed.path == "/api/visualize":
                self._handle_visualize(payload)
            elif parsed.path == "/api/repair":
                self._handle_repair(payload)
            elif parsed.path == "/api/resources":
                self._handle_resource_upload(payload)
            else:
                self._handle_chat(payload)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            send_json(
                self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Internal server error."}
            )

    def _handle_resource_upload(self, payload: dict) -> None:
        name = payload.get("name", "")
        content = payload.get("content", "")
        try:
            entry = add_resource(name, content)
        except ValueError as err:
            send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(err)})
            return
        send_json(
            self,
            HTTPStatus.OK,
            {"resource": entry, "resources": list_resources()},
        )

    def _handle_visualize(self, payload: dict) -> None:
        prompt = payload.get("prompt", "")
        mode = payload.get("preferred_mode", "auto")
        if mode not in {"auto", "2d", "3d"}:
            mode = "auto"
        if not isinstance(prompt, str) or not prompt.strip():
            send_json(self, HTTPStatus.BAD_REQUEST, {"error": "A non-empty prompt is required."})
            return
        try:
            result = plan_visualization(prompt.strip()[:4000], mode)
        except RuntimeError as error:
            send_json(self, HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(error)})
            return
        send_json(self, HTTPStatus.OK, result)

    def _handle_repair(self, payload: dict) -> None:
        prompt = payload.get("prompt", "")
        code = payload.get("code", "")
        error = payload.get("error", "")
        where = payload.get("where", "")
        if not isinstance(prompt, str) or not isinstance(code, str) or not code.strip():
            send_json(self, HTTPStatus.BAD_REQUEST, {"error": "prompt and code are required."})
            return
        try:
            result = repair_visualization(
                prompt.strip()[:4000], code[:20000], str(error)[:2000], str(where)[:300]
            )
        except RuntimeError as err:
            send_json(self, HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(err)})
            return
        send_json(self, HTTPStatus.OK, result)

    def _handle_chat(self, payload: dict) -> None:
        question = payload.get("question", "")
        # Pull once, then narrow. Calling .get() twice confuses Pylance into
        # thinking the second access could still be None.
        raw_viz = payload.get("visualization")
        viz: dict = raw_viz if isinstance(raw_viz, dict) else {}
        history = normalize_history(payload.get("history"))
        if not isinstance(question, str) or not question.strip():
            send_json(self, HTTPStatus.BAD_REQUEST, {"error": "A non-empty question is required."})
            return
        try:
            result = tutor_chat(question.strip()[:4000], viz, history)
        except RuntimeError as error:
            send_json(self, HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(error)})
            return
        send_json(self, HTTPStatus.OK, result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the VisualLM app.")
    # Cloud hosts (Render, Railway, Fly, Heroku) inject PORT and require
    # binding 0.0.0.0; locally we stay on the loopback interface by default.
    cloud_port = os.environ.get("PORT")
    default_port = int(os.environ.get("VISUALLM_PORT", cloud_port or "4173"))
    default_host = os.environ.get(
        "VISUALLM_HOST", "0.0.0.0" if cloud_port else "127.0.0.1"
    )
    parser.add_argument("--host", default=default_host)
    parser.add_argument("--port", type=int, default=default_port)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), VisualLMHandler)
    health = get_health()
    print(f"VisualLM running at http://{args.host}:{args.port}")
    print(f"Primary generator: {health['generator']}")
    if not health["claude"]["available"]:
        if not health["claude"]["has_key"]:
            print("  Claude: set ANTHROPIC_API_KEY for best-quality animations.")
        elif not health["claude"]["has_sdk"]:
            print("  Claude: run `pip install anthropic` to enable cloud generation.")
    if not health["openai"]["available"]:
        print("  OpenAI: set OPENAI_API_KEY to enable the ChatGPT fallback.")
    if not health["gemini"]["available"]:
        print("  Gemini: set GEMINI_API_KEY to enable the Gemini fallback.")
    print(
        "  Access code: "
        + ("REQUIRED (VISUALLM_ACCESS_CODE is set)" if ACCESS_CODE else "off — anyone who can reach this server can generate")
    )
    print(f"  Rate limit: {RATE_LIMIT_PER_MIN}/min per IP" if RATE_LIMIT_PER_MIN > 0 else "  Rate limit: disabled")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping VisualLM.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
