# VisualLM — User Evaluation Form

> A hands-on evaluation done by using the app as a student would, then filling out
> this form. Each finding is grounded in something actually typed/clicked, with a
> concrete fix and a code reference where one applies.

---

## 1. Session details

| Field | Value |
|---|---|
| Tester role | Student (first-time-ish user) |
| Edition tested | Browser edition (client-side, no server/key) |
| URL / build | `http://localhost:4179` (web/, `parameterized-demos` branch) |
| Viewports | Desktop (1280×800) + Mobile (375×812) |
| Date | 2026-06-26 |
| Console errors seen | None |

## 2. What I actually tested

`2H2 + O2 -> 2H2O` (balance) · `x^2 - 5x + 6 = 0` (quadratic) ·
`triangle with a=5, b=7, C=40 degrees` (solver) · `benzene` (3D molecule) ·
"Surprise me" · `how does a transformer neural network work` (out-of-scope) ·
"Solve it step by step" button · mobile layout.

## 3. Overall impression

**★★★☆☆ — Strong, correct, instant content; weak bridge from a user's words to it.**

The deterministic engine (triangle solver, molecules, balancing, slider demos) is
genuinely good and fast. The weak link is routing: a plain typed equation or a
casual question frequently lands on a confidently-wrong demo, and one headline
feature ("step-by-step solver") promises more than the browser edition delivers.

## 4. What works well (keep it)

- [x] **3D molecules** (`benzene`) — ball-and-stick, CPK colors, double bonds as
      parallel sticks, drag-to-orbit / scroll-zoom. Excellent.
- [x] **Triangle solver** — auto-advancing "Slide 2 of 4", Law of Cosines worked
      through *your* numbers, triangle drawn to scale. Best feature in the app.
- [x] **Chemistry balancing** — the atom-balance tally (H 4=4 ✓, O 2=2) makes
      conservation visible.
- [x] **Instant render + live sliders**, clean dark/light theming, zero console
      errors, and a populated demo on landing.

## 5. Findings by severity

### P0 — Topic routing confidently serves the wrong demo

The matcher is keyword-only, with no sense of equation *structure* or common-word
stopwords. The 2.0 "serve confidently" threshold lets false positives through with
**no "closest match" caveat**.

| Typed | Got | Cause |
|---|---|---|
| `x^2 - 5x + 6 = 0` | **0/0 limit by factoring** (Calculus, score 3) | "quadratic" never spelled out; correct demos (Quadratic formula, Completing the square) sit at 2.5 and lose |
| `how does a transformer neural network work` | **Work done by a force** (score 2) | everyday word "work" |
| `explain how vaccines work` | **Work done by a force** (score 2) | same |
| `power dynamics in a relationship` | **Electrical power P=V·I** (score 2) | "power" |

Verified via the scorer: adding the literal word "quadratic" lifts the right demo
from 2.5 → 4.5. The content exists; the engine just can't read a typed equation's shape.

**Fixes (in order of payoff):**
1. **Structural recognition of typed equations** — you already do this for triangles
   in `web/js/solver.js`. Extend it: degree-2 polynomial `= 0` → quadratic;
   `ax+b=0` → linear; a single unknown with `=` → equation-solve. Route those
   *before* keyword scoring.
2. **Stopword list** in `web/js/matching.js` so "work", "power", "field",
   "function", "how", "of", "real" don't carry full topic weight.
3. **Calibrate confidence + a "did you mean…?" affordance.** On a marginal/tied top
   score, offer the runner-up as a chip instead of silently committing. Today the
   honest "free-form AI is in the desktop app" help card almost never fires, because
   nearly any English sentence keyword-matches *something*.

### P0 — "Step-by-step solver" over-promises in the browser edition

Header advertises "…**step-by-step solver**…" and the most prominent tutor CTA is
**"Solve it step by step."** But in the browser edition:

- The local solver (`web/js/solver.js`) only handles **triangles**.
- The button just **fills the chat box** (no submit, no scroll), and that box is
  below the fold — so to the user *nothing happens*. (`web/app.js:1018`)
- If they then click "Ask", `/api/chat` **always** returns "the AI tutor runs in
  the desktop app." (`web/js/browser-backend.js:67`)

So the headline CTA is a dead end for anything but triangles.

**Fix:** relabel honestly ("Triangle solver" / "Worked solutions"), or have the
button run the local solver for supported inputs and **disable/relabel** itself
when no solver applies.

### P1 — Mobile buries the primary action

At 375px the stack is Explanation → Canvas → Prompt. Measured positions: canvas at
**864px**, prompt box + Visualize at **~1580–1800px** — two-plus screens below the
fold, behind a wall of text about the default scene. A first-time mobile user can't
find where to type.

**Fix:** on mobile, reorder to **Prompt → Canvas → Explanation**.

### P1 — Two tutor markdown bugs mangle the text

- **"left"/"right" deleted from prose.** `web/app.js:93`
  `s.replace(/\b(left|right)\b/g, "")` is meant to strip LaTeX `\left`/`\right` but
  nukes the English words. "Reactants **(left)** … products **(right)**" rendered as
  "Reactants **()** … **()**". Fix: require the backslash — `/\\(left|right)\b/g`.
- **Multiplication `*` rendered as italics.** `web/app.js:109`'s emphasis regex
  matches `* m *`, so `gamma * m * c^2` renders with "m" italicized and the asterisks
  eaten. Per CommonMark, `* x *` (spaces inside) isn't emphasis — tighten the regex
  to not match space-flanked `*`.

### P2 — Polish

- **Overlapping badges** on the 3D-molecule canvas: the green status pill collides
  with the "drag to orbit · scroll to zoom · double-click to reset" hint at bottom-left.
- **Desktop dead space**: the asymmetric grid leaves a tall empty area below the
  short right column; aligning panel heights (or moving the tutor up) tightens it.

## 6. Recommended next steps

| Priority | Item | Effort | Risk |
|---|---|---|---|
| 1 | Structural equation recognition + stopwords (P0 routing) | Medium | Low–med |
| 2 | Honest labeling / wiring of the "step-by-step solver" (P0) | Small | Low |
| 3 | Mobile reorder Prompt → Canvas → Explanation (P1) | Small | Low |
| 4 | Two tutor regex fixes (P1) | Tiny | Low |
| 5 | Badge overlap + desktop dead space (P2) | Tiny | Low |

**Biggest lever:** P0 #1. The single highest-impact change is teaching the router
to read a typed equation's structure, because that's the input a student is most
likely to paste.
