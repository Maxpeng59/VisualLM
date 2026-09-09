# Helper API (`H`) — full reference

The renderer hands your `scene(ctx, t)` body a global `H`. Everything below is a
method or constant on `H` (or on the `view`/`cam` objects it returns). Coordinates
are **pixels**, origin top-left, **y grows downward**, unless a method says
otherwise. This mirrors `runtime/sandbox-worker.js` exactly — if you change the
runtime, update this file.

## Contents
- [Constants](#constants)
- [Math helpers](#math-helpers)
- [2D drawing (pixel space)](#2d-drawing-pixel-space)
- [2D graphing — `H.plot2d`](#2d-graphing--hplot2d)
- [3D camera — `H.cam3d`](#3d-camera--hcam3d)
- [Solid 3D surfaces — `H.surface3d` / `H.mesh3d`](#solid-3d-surfaces)
- [Resilience: invented helpers no-op](#resilience)
- [Output JSON schema](#output-json-schema)

## Constants
- `H.W`, `H.H` — logical canvas width / height in pixels.
- `H.TAU` = 2π, `H.PI` = π.
- `H.colors` — themed palette. Use ONLY these names: `bg`, `panel`, `ink` (bright
  text), `sub` (dim text), `grid`, `axis`, `accent`, `accent2`, `good`, `warn`,
  `violet`, `yellow`. For any other color use a CSS string (`"#ffaa00"`),
  `H.hsl(h,s,l,a)`, or `H.color(i)`.
- `H.palette` — array of 8 distinct CSS colors; `H.color(i)` indexes it (wraps).

## Math helpers
- `H.clamp(x, lo, hi)` — constrain x to `[lo, hi]`.
- `H.lerp(a, b, t)` — linear blend; `t=0`→a, `t=1`→b.
- `H.map(x, inMin, inMax, outMin, outMax)` — remap a range (used for data→pixel).
- `H.ease(t)` — smoothstep on `[0,1]` (eased 0→1), good for transitions.
- `H.color(i)` — pick palette color i (wraps).
- `H.hsl(h, s, l, a?)` — `"hsla(h,s%,l%,a)"` string; h in degrees, s/l in percent.

## 2D drawing (pixel space)
Every option bag is optional; sensible defaults apply.
- `H.clear(color?)` — fill the whole canvas with a solid color.
- `H.background(top?, bottom?)` — vertical gradient background. **Call this first.**
- `H.text(str, x, y, {size, color, align, baseline, weight, maxWidth, font})`.
- `H.line(x1, y1, x2, y2, {color, width, dash, cap})`.
- `H.path(points, {color, width, fill, close, dash})` — `points = [[x,y], ...]`.
  Set `color:"none"` to fill only; `fill:"#.."` fills the polygon.
- `H.circle(x, y, r, {fill, stroke, width})`.
- `H.rect(x, y, w, h, {fill, stroke, width, radius})` — `radius` rounds corners.
- `H.arrow(x1, y1, x2, y2, {color, width, head})` — line with an arrowhead at the
  end; `head` sets arrowhead size.
- `H.legend([{label, color}, ...], x, y)` — color-swatch legend; counts as labels.

## 2D graphing — `H.plot2d`
`const view = H.plot2d({ xMin, xMax, yMin, yMax, pad, box })` returns a `view`
that maps DATA coordinates to pixels for you. Defaults: x∈[-10,10], y∈[-6,6],
`pad:46`. Pass an explicit `box:{x,y,w,h}` (pixels) to place multiple plots.

**Scaffold + functions:**
- `view.grid()` — light reference grid.
- `view.axes()` — x/y axes **with numeric tick labels** (satisfies Rule 2 for
  coordinates).
- `view.fn(f, {color, width, steps})` — plot `y = f(x)` across the domain.
- `view.dot(x, y, {r, fill, stroke})` — marker at a **data** point.
- `view.X(v)` / `view.Y(v)` — map a single data x/y to a pixel; `view.box` is the
  pixel box.

**Data-space drawing** (arguments are in MATH units; the view maps them):
- `view.line(x1, y1, x2, y2, opts)`
- `view.arrow(x1, y1, x2, y2, opts)`
- `view.text(str, x, y, opts)`
- `view.circle(x, y, rPx, opts)` — center in data units, radius in **pixels**.
- `view.path([[x,y], ...], opts)`
- `view.rect(x, y, w, h, opts)` — lower-left corner + size, all in data units.

> **Coordinate trap:** with a `view`, pass RAW math coords to the data-space
> methods — `view.line(x1, y1, x2, y2)`, NOT `view.line(view.X(x1), ...)`. Double
> transforming draws far off-screen (validator → `onscreen:false`). Use the
> pixel-space `H.*` methods only for chrome that isn't tied to graph coordinates.

Methods chain: `const v = H.plot2d({xMin:-6,xMax:6}); v.grid(); v.axes(); v.fn(Math.sin);`

## 3D camera — `H.cam3d`
`const cam = H.cam3d({ yaw, pitch, scale, dist, cx, cy })`. Convention: **+y is UP**
on screen; the ground plane is x/z. Larger `depth` = farther from camera, so for
correct overlap **sort polygons/spheres DESCENDING by depth and draw far first**.
The user can drag to orbit and scroll to zoom automatically — still set a slow
default spin `cam.yaw = 0.3 * t` so it reads as 3D before they touch it.

- `cam.project([x, y, z])` → `{ x, y, depth, f }` (screen point + depth + scale).
- `cam.yaw`, `cam.pitch` — settable; drive with `t` to rotate.
- `cam.line(a, b, opts)` — segment between two `[x,y,z]` points.
- `cam.path(points, opts)` — 3D polyline (orbits, trajectories, curves).
- `cam.poly(points, {fill, stroke, width})` — filled 3D polygon (you depth-sort).
- `cam.sphere([x,y,z], r, {color})` — **shaded** ball, world-unit radius, any CSS
  color. Returns its projection. For many: sort by `cam.project(p).depth`
  descending, then draw (atoms, planets, particles).
- `cam.grid(size, step)` — ground-plane grid at y=0 (depth perception).
- `cam.axes(len)` — labeled x/y/z axes.

## Solid 3D surfaces
Use these instead of point clouds — they render filled, light-shaded,
depth-sorted meshes that genuinely look 3D.

- `H.surface3d(cam, (x, y) => height, { xMin, xMax, yMin, yMax, nx, ny, alpha, wire, hueMin, hueMax })`
  — THE way to draw any height function `z = f(x,y)`. The returned height is drawn
  along the screen-up axis; color maps from height (override with `hueMin`/`hueMax`).
- `H.mesh3d(cam, (u, v) => [x, y, z], { uMin, uMax, vMin, vMax, nu, nv, hue, alpha, wire })`
  — parametric surface: spheres, tori, cylinders, tubes, ribbons, Möbius strips.
  `u`/`v` default to `[0, TAU]`; use a fixed `hue` (0–360).
  Sphere of radius R: `(u, v) => [Math.cos(u)*Math.sin(v)*R, Math.cos(v)*R, Math.sin(u)*Math.sin(v)*R]`
  with `vMin: 0, vMax: Math.PI`.

Keep `nx`/`ny`/`nu`/`nv` ≤ ~40 each (hard-capped at 64) for smooth framerate.

## Resilience
The runtime wraps `H`, every `view`, and every `cam` in a proxy: calling a helper
that does NOT exist returns a **chainable no-op** instead of throwing, so a single
typo (`H.spinner()`, `cam.glow()`) degrades to "that one thing didn't draw" rather
than blanking the frame. Don't rely on this — use only the documented helpers —
but it means an invented method is a quality bug, not a crash.

## Output JSON schema
When emitting a full scene record, this is the exact shape (all fields required):

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "title":           { "type": "string" },
    "tag":             { "type": "string" },
    "dimension":       { "type": "string", "enum": ["2D", "3D"] },
    "equation":        { "type": "string" },
    "summary":         { "type": "string" },
    "bullets":         { "type": "array", "items": { "type": "string" } },
    "student_prompts": { "type": "array", "items": { "type": "string" } },
    "code":            { "type": "string" }
  },
  "required": ["title", "tag", "dimension", "equation", "summary", "bullets", "student_prompts", "code"]
}
```
`bullets` should be exactly 3; `student_prompts` 3. `code` is the validated
`scene` body.
