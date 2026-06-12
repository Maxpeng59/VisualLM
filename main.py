from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import textwrap
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import defaultdict, deque
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


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
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


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
        max_tokens=32000,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
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


def repair_with_claude(prompt: str, code: str, error: str) -> dict:
    user_text = (
        "The animation code you wrote threw an error in the sandbox. Fix it and "
        "return the full corrected scene. Keep the same teaching intent.\n\n"
        f"Original request:\n{prompt}\n\n"
        f"Error:\n{error}\n\n"
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


_RESERVED_BINDINGS = ("H", "ctx", "t")


def _rewrite_declared_names(span: str) -> str:
    """Inside a `const|let|var ... ;` span, rename reserved binding identifiers.

    Handles all the common forms the model produces:
      const H = ...;
      let H, ctx;
      const W = H.W, H = H.H;       (the multi-decl that causes TDZ)
      const W = H.W,\n      H = H.H;  (multi-line)

    A binding identifier is one that appears either:
      - right after `const|let|var ` (the first declarator), or
      - right after a comma at the top level of the statement.
    """
    pattern = re.compile(
        r"(\b(?:const|let|var)\s+|,\s*)(" + "|".join(_RESERVED_BINDINGS) + r")\b"
    )
    return pattern.sub(lambda m: f"{m.group(1)}_{m.group(2)}", span)


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
_LABEL_CALLS = ("H.text", "H.legend", "fillText")


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


def _try_generate(fn, prompt: str, preferred_mode: str, label: str) -> dict:
    """Generate once, run the quality gate, and retry with targeted feedback.

    Three failure tiers, detected syntactically (we can't run JS here):
      blank      — no drawing call at all. Never shippable; after three
                   blank attempts we raise (caller may fall back).
      static     — never reads `t`, so the "animation" is a still image.
      unlabeled  — no text anywhere: no title, no values, no readouts.
    static/unlabeled trigger a regeneration with a hint naming exactly what
    was missing; if the last attempt still has them, we ship it anyway and
    annotate the scene so the UI can tell the user.
    """
    best_imperfect = None  # most recent paints-but-imperfect scene
    for attempt in range(3):
        scene = normalize_scene(fn(prompt, preferred_mode), prompt)
        problems = scene_problems(scene.get("code", ""))
        if not problems:
            if attempt > 0:
                # Annotate so the UI can surface what happened.
                scene["recovered_after_retry"] = attempt
            return scene
        if problems != ["blank"]:
            scene["quality_warnings"] = problems
            best_imperfect = scene
        # Reprompt with feedback naming exactly what was wrong. Models
        # reliably do better on the second try with a targeted hint.
        complaints = " ALSO, ".join(_PROBLEM_HINTS[p] for p in problems)
        prompt = prompt + "\n\nCRITICAL FEEDBACK on your previous attempt: " + complaints
    if best_imperfect is not None:
        return best_imperfect
    raise RuntimeError(
        f"{label} produced a blank scene three times — the code didn't call "
        f"any drawing helper. Try a different prompt, or use Claude for "
        f"more reliable generation."
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


def plan_visualization(prompt: str, preferred_mode: str) -> dict:
    errors = []
    for label, fn in _cloud_generators():
        try:
            return _try_generate(fn, prompt, preferred_mode, label)
        except Exception as error:  # noqa: BLE001
            errors.append(f"{label}: {error}")
    try:
        return _try_generate(
            lambda p, m: generate_with_ollama(p, m), prompt, preferred_mode, "Ollama"
        )
    except Exception as error:  # noqa: BLE001
        errors.append(f"Ollama: {error}")
    detail = " | ".join(errors) if errors else "no backend available"
    # Connection / timeout / no-backend failures are unrecoverable here — let
    # the frontend show a real error. But "blank scene three times" failures
    # are recoverable: we return a fallback scene that at least renders
    # something visible plus a clear explanation.
    blank_failure = any("blank scene" in e.lower() for e in errors)
    fatal_failure = any(
        ("timed out" in e.lower())
        or ("timeout" in e.lower())
        or ("connection" in e.lower())
        or ("could not reach" in e.lower())
        for e in errors
    ) or not blank_failure
    if blank_failure and not fatal_failure:
        return _fallback_scene(
            prompt,
            "The local model produced code that didn't draw anything three "
            "times in a row. Rephrase the prompt or enable Claude for stronger "
            "results.",
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


def repair_visualization(prompt: str, code: str, error: str) -> dict:
    errors = []
    if claude_available()["available"]:
        try:
            return normalize_scene(repair_with_claude(prompt, code, error), prompt)
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
                fn(prompt, "auto", fix={"code": code, "error": error}), prompt
            )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{label}: {e}")
    try:
        return normalize_scene(
            generate_with_ollama(prompt, "auto", fix={"code": code, "error": error}),
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

        if parsed.path == "/api/visualize":
            self._handle_visualize(payload)
        elif parsed.path == "/api/repair":
            self._handle_repair(payload)
        elif parsed.path == "/api/resources":
            self._handle_resource_upload(payload)
        else:
            self._handle_chat(payload)

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
        if not isinstance(prompt, str) or not isinstance(code, str) or not code.strip():
            send_json(self, HTTPStatus.BAD_REQUEST, {"error": "prompt and code are required."})
            return
        try:
            result = repair_visualization(
                prompt.strip()[:4000], code[:20000], str(error)[:2000]
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
