# Runtime — render scenes anywhere

This folder is the actual VisualLM rendering engine, extracted so generated
scenes run **without the VisualLM server** and with **no dependencies** beyond a
browser. It is what makes a scene from this skill *portable*: ship `runtime/`
alongside the `code` and any host can render it.

## Files
- **`sandbox-worker.js`** — a Web Worker that compiles a `scene(ctx, t, H)` body
  and runs it ~60×/s in an **OffscreenCanvas sandbox**. It defines the real `H`
  helper library (the one `references/helper-api.md` documents). Hardened: no DOM,
  no network, a watchdog kills runaway frames, invented helpers degrade to chainable
  no-ops, and a transient throwing frame doesn't kill a running scene.
- **`host.html`** — a minimal, self-contained host page: paste a scene, press Run,
  watch it render; drag to orbit 3D and scroll to zoom. No build step.

## Quick start
Serve the folder over HTTP (workers don't load from `file://`) and open the host:

```bash
cd runtime
python3 -m http.server 8000
# open http://localhost:8000/host.html
```

## Embed in your own app
The worker speaks a small message protocol. Wire it to a canvas:

```js
const canvas = document.querySelector("canvas");
const offscreen = canvas.transferControlToOffscreen();
const worker = new Worker("./sandbox-worker.js");

worker.onmessage = (e) => {
  const m = e.data;
  if (m.type === "ready")        worker.postMessage({ type: "run", code: sceneBody, resetTime: true });
  if (m.type === "heartbeat")    {/* a frame rendered — scene is live */}
  if (m.type === "runtime-error" || m.type === "compile-error") {
    console.error(m.message, m.where);   // m.where = "line N: <source>" when available
  }
};

const dpr = Math.min(2, devicePixelRatio || 1);
worker.postMessage({ type: "init", canvas: offscreen, width: 900, height: 560, dpr }, [offscreen]);
```

**Messages you send:**
| type | payload | effect |
|---|---|---|
| `init` | `{canvas, width, height, dpr}` (transfer `canvas`) | one-time setup |
| `run` | `{code, resetTime}` | compile + run a scene body |
| `pause` / `resume` | — | freeze / continue |
| `speed` | `{value}` | time multiplier |
| `resize` | `{width, height, dpr}` | re-fit the canvas |
| `orbit` | `{dyaw, dpitch, dzoom}` | nudge the 3D camera (drag/scroll) |
| `orbit-reset` | — | reset the camera |

**Messages you receive:** `ready`, `running`, `heartbeat` (every ~20 frames),
`compile-error` / `runtime-error` (`{message, stack, where}`).

## Headless validation
To check a scene *without* a browser (CI, an agent loop), use
`../scripts/validate_scene.js` (Node only) — see SKILL.md → "Validate before
shipping". The validator mirrors this runtime's `H` surface; if you add a helper
to `sandbox-worker.js`, mirror it in the validator's mock too.
