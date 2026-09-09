---
name: stem-viz
description: >-
  Generate animated 2D/3D STEM visualizations as self-contained sandboxed-JavaScript
  scene(ctx, t, H) code — math, physics, chemistry, biology, CS/algorithms, and
  machine-learning concepts rendered as something you can watch move. Use this
  whenever the user wants to visualize, animate, illustrate, simulate, or "show"
  a STEM concept, equation, function, algorithm, or data idea (e.g. "animate
  gradient descent", "visualize a Fourier series", "show projectile motion",
  "plot z = f(x,y) as a 3D surface", "explain the derivative with a moving
  tangent line", "draw the electric field of a dipole"), even when they don't say
  the word "animation". Also use it to RUN a scene (bundled browser runtime), to
  VALIDATE scene code headlessly before shipping (bundled Node validator), and to
  REPAIR scene code that throws. Prefer this skill over hand-rolling canvas code.
---

# STEM Visualization — scene generator + runtime

This skill produces **animated explanations of STEM ideas**. You write the body of
a `scene(ctx, t, H)` function in JavaScript; a small sandboxed renderer (bundled
in `runtime/`) calls it ~60×/second and paints the result on a canvas. The same
code can be validated headlessly (`scripts/validate_scene.js`) and run for real
(`runtime/host.html`) — so a scene you generate here is portable: it runs anywhere
the runtime goes, with no server and no dependencies beyond a browser (to render)
or Node (to validate).

## Teach the mechanism, don't solve their problem

This is the goal above all the rules below. These animations exist to help a
learner **understand** a concept — to make it *visible* — not to act as an
answer key. When a prompt is really a specific problem ("a ball thrown at
22 m/s at 58°, find the range"), don't just compute the number and display it as
*the answer* — that does the student's work for them. Show the **mechanism**
that produces it (the parabola forming, the velocity components, why it peaks
where it does) so the learner can see the structure and reason to the result.

- **Show the relationship, not one instance.** Sweep a parameter with `t` (the
  point of tangency, the angle, the harmonic count) so they watch *how* it
  behaves across cases — not just the value at their number.
- **Make labels explain, not just state.** `"slope = f'(a): watch it flip sign
  at the peak"` teaches; a bare `"answer = 41.2"` doesn't.
- **Provoke, don't spoon-feed.** Use `bullets` and `student_prompts` to invite
  prediction ("where is the slope zero?"), not to hand over the solution.

Not a license to be vague: scenes stay concrete, runnable, and labeled, and a
**live readout of a changing quantity is good** — it makes the relationship
visible. The line is between *illuminating the mechanism* (teach) and
*delivering the one specific answer to their assigned problem* (solve).

## Workflow

1. **Understand the concept** and what should *move*. The goal is teaching, not
   decoration — decide the one mechanism the animation should reveal (a sweeping
   tangent, a propagating wave, a descending optimizer, a rotating molecule).
   Reveal that mechanism — don't just compute the prompt's specific answer (see
   *Teach the mechanism, don't solve their problem* above).
2. **Pick 2D or 3D.** 3D when the idea lives in space (surfaces `z=f(x,y)`,
   orbits, molecules, fields in space, multivariable calculus, rotations); 2D for
   single-variable functions, time series, circuits, graphs/algorithms, planar
   geometry. Honor an explicit user preference.
3. **Check the playbook.** For common topics, `references/concepts.md` maps the
   concept to a proven visual recipe (and links a complete worked scene). Reuse
   the recipe rather than inventing one.
4. **Write the scene body** following the contract below. Keep it a pure function
   of `(ctx, t)` — drive *all* motion from `t`, never keep outer state.
5. **Validate before you ship.** Run `scripts/validate_scene.js` (see below). It
   catches throws, blank output, missing labels, and off-screen drawing in ~1s
   without a browser.
6. **If it throws or is blank, repair it** using `references/repair.md` — make the
   *smallest* change that fixes the reported error; don't rewrite a working scene.
7. **Emit the result** in the output format below (or just the `code` body if the
   caller only wants runnable code).

## The rendering contract

`code` is the BODY of a function with this exact signature — provide only the
statements that go *inside* it, do not write `function scene(...)` yourself:

```js
function scene(ctx, t) {
  // your code here
}
```

- `ctx` — a Canvas 2D context. The canvas is cleared before each call.
- `t` — elapsed time in **seconds** (a float; respects pause/speed). Drive all
  motion from `t` so the animation loops smoothly. `scene` is called ~60×/s and
  must be a **pure function of (ctx, t)** — no frame counters, no outer-state
  mutation.
- `H` — the helper library, available as a **global** in the renderer scope.
  Reference it directly (`H.text(...)`); never declare it.
- `H.W`, `H.H` — logical width/height of the drawing area (pixels).
- Only these globals exist: `Math`, `Number`, `Array`, `Object`, `JSON`,
  `console`, and `H`. Call math through `Math.*` (`Math.sin(x)`, not `sin(x)`).
- **Never** use: unbounded loops, `while(true)`, `setTimeout`/`setInterval`/
  `requestAnimationFrame`, network, DOM, `import`, or `eval`. Keep every loop
  finite and cheap (≤ a few hundred iterations per frame).

### Three hard rules (code that breaks these is treated as a failed scene)

**Rule 0 — every scene MUST PAINT.** The #1 failure is code that computes but
never draws.
1. Call `H.background()` (or `H.clear()`) on the **first line**.
2. Call **≥ 3 drawing helpers per frame** (a `for` loop calling one counts):
   `H.text/line/path/circle/rect/arrow/legend/surface3d/mesh3d`, any `plot2d`
   view method (`.grid/.axes/.fn/.dot`), or any `cam` method
   (`.line/.path/.poly/.sphere/.grid/.axes`).
3. Use real **pixel** coordinates in `[0, H.W] × [0, H.H]`. Do **not** draw at
   math coordinates like `(-3, 0.5)` directly — go through `H.plot2d` (which maps
   for you) or scale with `H.map(...)`. Mixing the two (e.g. `v.line(v.X(x), ...)`)
   double-transforms and draws off-screen — the validator flags this as
   `onscreen: false`.

**Rule 1 — every scene MUST MOVE.** It only animates if your code reads `t`.
Drive at least one primary element from `t`. If the concept is static (a
structure, a proof), animate the *explanation*: sweep a highlight, pulse the
region under discussion, orbit the camera (`cam.yaw = 0.3 * t`), or step through
stages with `const phase = Math.floor(t % 9 / 3);`.

**Rule 2 — every scene MUST BE LABELED with real values.** A picture without
numbers teaches nothing.
- A title (`H.text`, size 18, weight 700) top-left + a one-line caption under it
  (size 13, `H.colors.sub`).
- `view.axes()` (2D) and `cam.axes(len)` (3D) auto-draw numeric ticks — use them
  whenever the scene has coordinates.
- At least one **live readout** that changes with `t`, e.g.
  `H.text("E = " + E.toFixed(2) + " J", 24, 76, { color: H.colors.sub, size: 13 });`
- With 2+ colored elements, add `H.legend([{label, color}, ...], x, y)`.

### Minimal complete skeleton

```js
H.background();
const v = H.plot2d({ xMin: -6, xMax: 6, yMin: -2, yMax: 2 });
v.grid(); v.axes();
v.fn(x => Math.sin(x + t), { color: H.colors.accent, width: 3 });
H.text("Your title", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("one-line caption", 24, 52, { color: H.colors.sub, size: 13 });
```

## Helper essentials

Enough to write most 2D scenes; **full API in `references/helper-api.md`** (read it
for `plot2d` data-space methods, all `cam3d`/`surface3d`/`mesh3d` options, and the
exact option bags).

- **Constants:** `H.W`, `H.H`, `H.TAU` (2π), `H.PI`, `H.colors`, `H.palette`.
- **Colors:** `H.colors.{bg,panel,ink,sub,grid,axis,accent,accent2,good,warn,violet,yellow}`.
  For anything else use a CSS string (`"#ffaa00"`) or `H.hsl(h,s,l,a)` / `H.color(i)`.
- **Math:** `H.clamp`, `H.lerp`, `H.map(x,inMin,inMax,outMin,outMax)`, `H.ease`.
- **Draw (pixels):** `H.background()`, `H.text(s,x,y,opts)`, `H.line(x1,y1,x2,y2,opts)`,
  `H.path([[x,y],...],opts)`, `H.circle(x,y,r,opts)`, `H.rect(x,y,w,h,opts)`,
  `H.arrow(x1,y1,x2,y2,opts)`, `H.legend(items,x,y)`.
- **2D graph:** `const v = H.plot2d({xMin,xMax,yMin,yMax,pad})` → `v.grid()`,
  `v.axes()`, `v.fn(x=>..., opts)`, `v.dot(x,y,opts)`, `v.X(v)`/`v.Y(v)`, plus
  data-space `v.line/v.arrow/v.text/v.circle/v.path/v.rect` (args in **math**
  units).
- **3D:** `const cam = H.cam3d({yaw,pitch,scale,dist,cx,cy})`; set `cam.yaw = 0.3*t`;
  `cam.grid()`, `cam.axes(len)`, `cam.line/path/poly/sphere`; and the **solid**
  surfaces `H.surface3d(cam, (x,y)=>height, opts)` and `H.mesh3d(cam, (u,v)=>[x,y,z], opts)`.
  Make 3D solid (lit, depth-sorted) — never a cloud of flat dots.

## Validate before shipping

The bundled validator runs the scene against a faithful mock of `H` in a locked
V8 sandbox at several values of `t` and reports JSON — no browser needed:

```bash
node scripts/validate_scene.js <<'SCENE'
H.background();
const v = H.plot2d({ xMin: -6, xMax: 6, yMin: -2, yMax: 2 });
v.grid(); v.axes();
v.fn(x => Math.sin(x + t), { color: H.colors.accent, width: 3 });
H.text("sine", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
SCENE
# → {"ok":true,"error":null,"painted":true,"text":true,"paint":N,"onscreen":true}
```

A scene is ready to ship only when `ok:true`, `painted:true`, `text:true`, and
`onscreen:true`. If `ok:false`, read `error` and repair (next). If `painted` or
`text` is false, you broke Rule 0/2. If `onscreen:false`, you mixed data and
pixel coordinates (Rule 0.3).

## If it throws: repair

`references/repair.md` maps each error class to a targeted fix and the guiding
principle: **make the smallest change that fixes the reported error — keep
everything that already works.** Re-validate after every repair. Most failures
are a tiny set: an undeclared name, an invented helper, a property read off
`undefined`, or a syntax slip from truncation.

## Run it for real

`runtime/` is the actual rendering engine, portable and dependency-free:
- `runtime/sandbox-worker.js` — the Web Worker that compiles and runs scene code
  in an OffscreenCanvas sandbox (no DOM/network; watchdog kills runaways). It
  exposes the real `H` library.
- `runtime/host.html` — a minimal standalone page: paste a scene, watch it render,
  drag to orbit 3D. Open it in a browser, no build step.
- `runtime/README.md` — how to embed the runtime in your own app.

## Output format

When the caller wants a full scene record (the VisualLM shape), emit these fields
(JSON schema in `references/helper-api.md`):

- `title` — short scene title (≤ 60 chars)
- `tag` — subject label ("Calculus", "Electromagnetism", "Algorithms")
- `dimension` — `"2D"` or `"3D"`
- `equation` — the central equation in plain text, or `""`
- `summary` — one or two sentences on what the animation shows
- `bullets` — exactly 3 short teaching points tied to what's on screen
- `student_prompts` — 3 good follow-up questions
- `code` — the `scene` body: self-contained, runnable, validated

If the caller only asked for "an animation of X", returning just the validated
`code` body is fine.

## Correctness rules that are easy to get wrong

- **Defensive code.** Guard against divide-by-zero, NaN, and out-of-range values.
  The animation must never throw — `+1e-6` denominators, `Math.max(0, ...)` for
  physical floors, `H.clamp` for bounded quantities.
- **Physical quantities stay physical.** Lengths, radii, masses, probabilities,
  energies must never display negative. Don't animate them with a bare
  `Math.sin(t)` — use `2 + Math.sin(t)` or `Math.abs(...)`.
- **Numbers must match the picture.** If a readout says `a = 3.0`, the drawn
  length must be 3 units.
- **No fake interactivity.** Generated code receives no mouse/keyboard input.
  Never claim "drag the vertices" / "click to…" in code, summary, or bullets. The
  only built-in interaction is camera orbit on 3D scenes (automatic).

## Reference files

| File | Read it when |
|---|---|
| `references/helper-api.md` | You need the full helper API — `plot2d` data-space methods, every `cam3d`/`surface3d`/`mesh3d` option, the color list, the output JSON schema. |
| `references/concepts.md` | The user named a common STEM topic — get a proven concept→visual recipe and a link to a complete worked scene. |
| `references/examples.md` | You want complete, validated end-to-end scenes (2D and 3D) to adapt. |
| `references/repair.md` | A generated scene threw or came back blank — error-class → minimal-change fix. |
| `runtime/README.md` | You need to actually render/host scenes, or embed the engine elsewhere. |
