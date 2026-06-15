# Repair protocol — fixing a scene that throws or comes back blank

When `scripts/validate_scene.js` (or the live runtime) reports a problem, fix it
with the **smallest change that addresses the reported error**. The most common
mistake is rewriting the whole scene — that usually trades the original bug for a
new one. Keep everything that already works; touch only the failing line.

## Loop
1. Run `node scripts/validate_scene.js <<'SCENE' … SCENE`.
2. Read the JSON: `ok`, `error`, `painted`, `text`, `onscreen`.
3. Apply the targeted fix for that signal (tables below).
4. **Re-validate.** Repeat only while it's making progress — if two repairs hit
   the *same* error, stop and rethink the approach rather than looping.

## `ok:false` — the scene threw. Fix by error class.

| Error contains | What it means | Minimal fix |
|---|---|---|
| `is not defined` | A name was used before it was declared (usually a typo). | Declare it with `const`/`let`, or fix the misspelling. Do **not** add other new names. |
| `is not a function` | You called something that isn't a real helper (invented method, or a non-function value). | Use only the documented helpers (`references/helper-api.md`). Delete or replace the invalid call. |
| `Cannot read properties of undefined` / `… of null` | You read a property off `undefined`/`null` — an out-of-range array index, or a value that wasn't created. | Guard the access: check the value exists and any index is in range before use. |
| `is not iterable` | You spread or looped over a non-array. | Ensure the value is an array (default to `[]`) before iterating. |
| `Unexpected token` / `SyntaxError` | The code didn't parse — usually an unbalanced bracket or a statement cut off mid-way. | Return complete, valid JavaScript; check brackets/quotes balance. |
| `hung` / `timed out` | An unbounded or huge loop. | Bound every loop; drive animation from `t`, never a `while`-until-condition. Cap mesh `nx/ny/nu/nv` ≤ 40. |

The error message names *what* threw; if you also have a line (the live runtime
reports `where: "line N: <source>"`), fix exactly that line.

## `painted:false` — nothing drew (Rule 0)
The body computed but never issued a content draw. Ensure `H.background()` is the
first line **and** at least three real drawing calls run every frame (a `for` loop
calling one counts). Setup-only code (`const`s, math, no `H.*` draw) renders a
blank canvas.

## `text:false` — no labels (Rule 2)
Add a title (`H.text`, size 18, weight 700), a caption, and at least one live
readout. `view.axes()`/`cam.axes()` also count as labels.

## `onscreen:false` — drawn off-canvas (the coordinate trap)
Content was drawn but none landed on the canvas — almost always **data vs pixel
coordinate mixing**. Symptoms and fixes:
- You called a `view` *data-space* method with already-mapped pixels:
  `v.line(v.X(x1), v.Y(y1), …)` double-transforms. Pass **raw math coords**:
  `v.line(x1, y1, x2, y2)`.
- You drew with pixel-space `H.line/H.circle` using math coordinates like
  `(-3, 0.5)`. Either go through a `view`, or map with `H.map(...)` / `v.X`/`v.Y`
  first.
- Your data range doesn't contain what you're plotting — widen `xMin/xMax`,
  `yMin/yMax` to include the values.

## When stuck
If the same error survives two minimal fixes, the approach is wrong, not the line.
Re-read the relevant recipe in `references/concepts.md`, or adapt the nearest
working scene in `references/examples.md` instead of patching further. A correct
scene built from a known-good template beats a heavily-patched broken one.
