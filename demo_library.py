"""Curated, parameterized DEMO library for VisualLM (Algebra 1 -> Precalculus).

The "interactive textbook" path: instead of generating code per prompt, the
server classifies the prompt to a topic (demo_match in main.py), shows a
hand-built demo, lets the student edit its values live (the `params` become the
`P` global the scene reads each frame), and explains the idea/theorem.

Each entry:
  id          - stable identifier
  area        - curriculum band (Algebra 1 / Algebra 2 / Geometry & Trig / Precalculus)
  topic       - short topic name
  title       - scene title
  equation    - the central relationship, plain text
  keywords    - synonym-rich terms used to classify a prompt to this demo
  explanation - the idea/theorem, written to BUILD UNDERSTANDING (not just state
                an answer): what each parameter does and why.
  bullets     - 3 short teaching points
  params      - editable controls: {name, label, min, max, step, value}; the
                scene reads them as P.<name>, updated live by the UI sliders
  code        - scene body (uses P.<name>, t, and the H helper API)

Every `code` follows the H API contract and is checked by validate_scene.js
(which supplies a permissive `P`). Keep them animated (read `t`) and labeled.
"""
from __future__ import annotations

_BASE: list[dict] = [
    {
        "id": "linear-slope-intercept",
        "area": "Algebra 1",
        "topic": "Linear functions",
        "title": "Slope–intercept form: y = mx + b",
        "equation": "y = m·x + b",
        "keywords": [
            "slope", "intercept", "slope intercept", "linear", "linear function",
            "line", "y=mx+b", "mx+b", "rise over run", "gradient", "straight line",
        ],
        "explanation": (
            "A line's slope m is its steepness — the rise over the run. Increase m "
            "and the line tilts up faster; make it negative and the line goes "
            "downhill. The intercept b slides the whole line up or down, and is "
            "exactly where it crosses the y-axis (x = 0). Watch the rise/run "
            "triangle change as you drag m."
        ),
        "bullets": [
            "m = rise / run: the change in y for a 1-unit change in x.",
            "b is the y-value where the line crosses the y-axis (x = 0).",
            "Two points, or a point and a slope, fully determine a line.",
        ],
        "params": [
            {"name": "m", "label": "slope  m", "min": -4, "max": 4, "step": 0.1, "value": 1},
            {"name": "b", "label": "y-intercept  b", "min": -6, "max": 6, "step": 0.5, "value": 1},
        ],
        "code": r"""
H.background();
const v = H.plot2d({ xMin: -8, xMax: 8, yMin: -8, yMax: 8 });
v.grid(); v.axes();
const m = P.m, b = P.b;
v.fn(x => m * x + b, { color: H.colors.accent, width: 3 });
v.dot(0, b, { r: 6, fill: H.colors.warn });
v.line(0, b, 2, b, { color: H.colors.good, width: 2, dash: [5, 5] });
v.line(2, b, 2, m * 2 + b, { color: H.colors.violet, width: 2, dash: [5, 5] });
const xs = 6 * Math.sin(t * 0.6);
v.dot(xs, m * xs + b, { r: 6, fill: H.colors.accent2 });
H.text("y = m·x + b", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("m = " + m.toFixed(2) + "    b = " + b.toFixed(2), 24, 52, { color: H.colors.sub, size: 14 });
H.legend([{ label: "rise", color: H.colors.violet }, { label: "run", color: H.colors.good }], H.W - 150, 28);
""".strip(),
    },
    {
        "id": "systems-linear",
        "area": "Algebra 1",
        "topic": "Systems of equations",
        "title": "System of two linear equations",
        "equation": "y = m1·x + b1,  y = m2·x + b2",
        "keywords": [
            "system", "systems of equations", "two equations", "intersection",
            "simultaneous", "solve system", "elimination", "substitution",
            "point of intersection", "two lines",
        ],
        "explanation": (
            "The solution of a system is the point that lies on BOTH lines at once "
            "— where they cross. Slide the slopes and intercepts: when the lines "
            "have different slopes there's exactly one crossing; give them the same "
            "slope and they're parallel (no solution) or identical (infinitely "
            "many). The pulsing dot marks the solution."
        ),
        "bullets": [
            "A solution satisfies every equation at the same time.",
            "Different slopes -> one intersection; equal slopes -> parallel or identical.",
            "Graphing finds it visually; elimination/substitution find it exactly.",
        ],
        "params": [
            {"name": "m1", "label": "slope 1", "min": -4, "max": 4, "step": 0.1, "value": 1},
            {"name": "b1", "label": "intercept 1", "min": -6, "max": 6, "step": 0.5, "value": 2},
            {"name": "m2", "label": "slope 2", "min": -4, "max": 4, "step": 0.1, "value": -1},
            {"name": "b2", "label": "intercept 2", "min": -6, "max": 6, "step": 0.5, "value": -1},
        ],
        "code": r"""
H.background();
const v = H.plot2d({ xMin: -8, xMax: 8, yMin: -8, yMax: 8 });
v.grid(); v.axes();
const m1 = P.m1, b1 = P.b1, m2 = P.m2, b2 = P.b2;
v.fn(x => m1 * x + b1, { color: H.colors.accent, width: 3 });
v.fn(x => m2 * x + b2, { color: H.colors.accent2, width: 3 });
H.text("System: two lines", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
if (Math.abs(m1 - m2) > 1e-6) {
  const xi = (b2 - b1) / (m1 - m2), yi = m1 * xi + b1;
  H.circle(v.X(xi), v.Y(yi), 6 + Math.sin(t * 3), { fill: H.colors.warn });
  H.text("solution  (" + xi.toFixed(2) + ", " + yi.toFixed(2) + ")", 24, 52, { color: H.colors.good, size: 14 });
} else {
  H.text(Math.abs(b1 - b2) < 1e-6 ? "same line — infinitely many solutions" : "parallel lines — no solution", 24, 52, { color: H.colors.warn, size: 14 });
}
H.legend([{ label: "line 1", color: H.colors.accent }, { label: "line 2", color: H.colors.accent2 }], H.W - 150, 28);
""".strip(),
    },
    {
        "id": "abs-value-transform",
        "area": "Algebra 1",
        "topic": "Absolute value",
        "title": "Absolute value: y = a|x − h| + k",
        "equation": "y = a·|x − h| + k",
        "keywords": [
            "absolute value", "abs", "modulus", "v shape", "vertex", "piecewise",
            "|x|", "absolute value function", "translation",
        ],
        "explanation": (
            "The graph of |x| is a V with its corner at the origin. h slides the "
            "corner left/right, k slides it up/down, and a controls how steep the "
            "arms are (negative a flips the V upside-down). The corner sits exactly "
            "at the vertex (h, k) — drag the sliders and watch it move."
        ),
        "bullets": [
            "|x − h| shifts the corner to x = h; + k shifts it up by k.",
            "a stretches the arms (|a| > 1 steeper); a < 0 opens it downward.",
            "The vertex (h, k) is the minimum (or maximum if a < 0).",
        ],
        "params": [
            {"name": "a", "label": "steepness  a", "min": -3, "max": 3, "step": 0.1, "value": 1},
            {"name": "h", "label": "shift right  h", "min": -5, "max": 5, "step": 0.5, "value": 0},
            {"name": "k", "label": "shift up  k", "min": -3, "max": 6, "step": 0.5, "value": 0},
        ],
        "code": r"""
H.background();
const v = H.plot2d({ xMin: -8, xMax: 8, yMin: -4, yMax: 10 });
v.grid(); v.axes();
const a = P.a, h = P.h, k = P.k;
v.fn(x => a * Math.abs(x - h) + k, { color: H.colors.accent, width: 3 });
v.dot(h, k, { r: 7, fill: H.colors.warn });
const xs = h + 5 * Math.sin(t * 0.7);
v.dot(xs, a * Math.abs(xs - h) + k, { r: 6, fill: H.colors.accent2 });
H.text("y = a|x − h| + k", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("vertex (" + h.toFixed(1) + ", " + k.toFixed(1) + ")    slope ±" + Math.abs(a).toFixed(1), 24, 52, { color: H.colors.sub, size: 14 });
""".strip(),
    },
    {
        "id": "exponential-growth-decay",
        "area": "Algebra 1",
        "topic": "Exponential functions",
        "title": "Exponential growth & decay: y = a·bˣ",
        "equation": "y = a · b^x",
        "keywords": [
            "exponential", "growth", "decay", "compound", "b^x", "exponential function",
            "half life", "doubling", "exponential growth", "exponential decay",
        ],
        "explanation": (
            "Exponential change multiplies by the same factor b every step (unlike "
            "linear change, which adds). When b > 1 the curve shoots up (growth); "
            "when 0 < b < 1 it decays toward zero. a is the starting value at x = 0. "
            "Notice how a small change in b dramatically changes how fast it rises."
        ),
        "bullets": [
            "Each unit of x multiplies y by b (constant ratio, not constant difference).",
            "b > 1 grows; 0 < b < 1 decays; a is the value at x = 0.",
            "Growth eventually outpaces ANY straight line.",
        ],
        "params": [
            {"name": "a", "label": "start  a", "min": 0.2, "max": 6, "step": 0.2, "value": 1},
            {"name": "b", "label": "base  b", "min": 0.2, "max": 2.5, "step": 0.05, "value": 1.5},
        ],
        "code": r"""
H.background();
const v = H.plot2d({ xMin: -1, xMax: 8, yMin: -1, yMax: 12 });
v.grid(); v.axes();
const a = P.a, b = Math.max(0.05, P.b);
v.fn(x => a * Math.pow(b, x), { color: H.colors.accent, width: 3 });
const xs = (t % 8);
v.dot(xs, a * Math.pow(b, xs), { r: 6, fill: H.colors.warn });
H.text("y = a · bˣ", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("a = " + a.toFixed(2) + "   b = " + b.toFixed(2) + (b > 1 ? "   (growth)" : "   (decay)"), 24, 52, { color: H.colors.sub, size: 14 });
""".strip(),
    },
    {
        "id": "quadratic-vertex",
        "area": "Algebra 2",
        "topic": "Quadratic functions",
        "title": "Quadratic (vertex form): y = a(x − h)² + k",
        "equation": "y = a(x − h)² + k",
        "keywords": [
            "quadratic", "parabola", "vertex", "vertex form", "axis of symmetry",
            "completing the square", "x squared", "quadratic function",
        ],
        "explanation": (
            "Every parabola is a stretched, shifted version of y = x². The vertex "
            "(h, k) is its turning point, and the parabola is mirror-symmetric "
            "across the vertical line x = h. a sets how narrow it is and which way "
            "it opens (a < 0 opens down). Vertex form lets you read the vertex off "
            "directly — no algebra needed."
        ),
        "bullets": [
            "Vertex (h, k) is the turning point; x = h is the axis of symmetry.",
            "|a| > 1 narrows the parabola; a < 0 opens it downward.",
            "Vertex form is y = x² shifted by (h, k) and scaled by a.",
        ],
        "params": [
            {"name": "a", "label": "shape  a", "min": -3, "max": 3, "step": 0.1, "value": 1},
            {"name": "h", "label": "vertex x  h", "min": -5, "max": 5, "step": 0.5, "value": 0},
            {"name": "k", "label": "vertex y  k", "min": -3, "max": 8, "step": 0.5, "value": 0},
        ],
        "code": r"""
H.background();
const v = H.plot2d({ xMin: -8, xMax: 8, yMin: -4, yMax: 12 });
v.grid(); v.axes();
const a = P.a, h = P.h, k = P.k;
v.fn(x => a * (x - h) * (x - h) + k, { color: H.colors.accent, width: 3 });
v.line(h, -4, h, 12, { color: H.colors.violet, width: 1.5, dash: [4, 4] });
v.dot(h, k, { r: 7, fill: H.colors.warn });
const xs = h + 4 * Math.sin(t * 0.7);
v.dot(xs, a * (xs - h) * (xs - h) + k, { r: 6, fill: H.colors.accent2 });
H.text("y = a(x − h)² + k", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("vertex (" + h.toFixed(1) + ", " + k.toFixed(1) + ")    a = " + a.toFixed(2), 24, 52, { color: H.colors.sub, size: 14 });
""".strip(),
    },
    {
        "id": "quadratic-discriminant",
        "area": "Algebra 2",
        "topic": "Quadratic formula",
        "title": "Roots & the discriminant: y = ax² + bx + c",
        "equation": "x = (−b ± √(b² − 4ac)) / 2a",
        "keywords": [
            "quadratic formula", "discriminant", "roots", "zeros", "x intercepts",
            "ax2+bx+c", "factoring", "solutions", "real roots", "b^2-4ac",
            "quadratic",
        ],
        "explanation": (
            "The roots are where the parabola crosses the x-axis (y = 0). The "
            "discriminant b² − 4ac (the part under the square root) tells you how "
            "many real roots there are BEFORE you solve: positive -> two, zero -> "
            "one (the vertex touches the axis), negative -> none (it floats above "
            "or below). Watch the green roots appear and merge as you change c."
        ),
        "bullets": [
            "Roots are the x-intercepts: where ax² + bx + c = 0.",
            "Discriminant b² − 4ac: >0 two roots, =0 one, <0 none (real).",
            "The two roots are symmetric about the axis x = −b/2a.",
        ],
        "params": [
            {"name": "a", "label": "a", "min": -2, "max": 2, "step": 0.1, "value": 1},
            {"name": "b", "label": "b", "min": -6, "max": 6, "step": 0.5, "value": 0},
            {"name": "c", "label": "c", "min": -8, "max": 8, "step": 0.5, "value": -4},
        ],
        "code": r"""
H.background();
const v = H.plot2d({ xMin: -8, xMax: 8, yMin: -10, yMax: 10 });
v.grid(); v.axes();
const a = P.a, b = P.b, c = P.c;
v.fn(x => a * x * x + b * x + c, { color: H.colors.accent, width: 3 });
const disc = b * b - 4 * a * c;
if (disc >= 0 && Math.abs(a) > 1e-6) {
  const r1 = (-b + Math.sqrt(disc)) / (2 * a), r2 = (-b - Math.sqrt(disc)) / (2 * a);
  v.dot(r1, 0, { r: 6, fill: H.colors.good });
  v.dot(r2, 0, { r: 6, fill: H.colors.good });
}
const xs = 5 * Math.sin(t * 0.6);
v.dot(xs, a * xs * xs + b * xs + c, { r: 5, fill: H.colors.accent2 });
H.text("y = ax² + bx + c", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
const verdict = disc > 1e-9 ? " → 2 real roots" : Math.abs(disc) <= 1e-9 ? " → 1 real root" : " → no real roots";
H.text("b² − 4ac = " + disc.toFixed(2) + verdict, 24, 52, { color: H.colors.sub, size: 13 });
""".strip(),
    },
    {
        "id": "polynomial-end-behavior",
        "area": "Algebra 2",
        "topic": "Polynomials",
        "title": "Power functions & end behavior: y = a·xⁿ",
        "equation": "y = a · x^n",
        "keywords": [
            "polynomial", "end behavior", "degree", "power function", "x^n",
            "even odd degree", "leading coefficient", "cubic", "quartic",
        ],
        "explanation": (
            "The highest-power term controls what a polynomial does at the far left "
            "and right. Even degree makes both ends go the same way (both up, or "
            "both down if a < 0); odd degree sends the ends in opposite directions. "
            "The sign of the leading coefficient a flips them. Step n through whole "
            "numbers to feel the even/odd pattern."
        ),
        "bullets": [
            "Even n: both ends point the same way; odd n: opposite ends.",
            "a > 0 lifts the right end; a < 0 flips the whole picture.",
            "Only the leading term matters for the far-left/far-right behavior.",
        ],
        "params": [
            {"name": "a", "label": "leading coef  a", "min": -2, "max": 2, "step": 0.1, "value": 1},
            {"name": "n", "label": "degree  n", "min": 1, "max": 5, "step": 1, "value": 3},
        ],
        "code": r"""
H.background();
const v = H.plot2d({ xMin: -3, xMax: 3, yMin: -10, yMax: 10 });
v.grid(); v.axes();
const a = P.a, n = Math.max(1, Math.round(P.n));
v.fn(x => a * Math.pow(x, n), { color: H.colors.accent, width: 3 });
const xs = 2.5 * Math.sin(t * 0.6);
v.dot(xs, a * Math.pow(xs, n), { r: 6, fill: H.colors.warn });
const even = n % 2 === 0;
H.text("y = a · xⁿ   (end behavior)", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("a = " + a.toFixed(1) + "   n = " + n + (even ? "   even: ends match" : "   odd: ends oppose"), 24, 52, { color: H.colors.sub, size: 13 });
""".strip(),
    },
    {
        "id": "log-exp-inverse",
        "area": "Algebra 2",
        "topic": "Logarithms",
        "title": "Logarithm as the inverse of bˣ",
        "equation": "y = b^x   ⇔   y = log_b(x)",
        "keywords": [
            "logarithm", "log", "inverse function", "exponential inverse", "log base",
            "ln", "natural log", "reflection", "logarithmic",
        ],
        "explanation": (
            "A logarithm undoes an exponential: log_b(x) answers 'b to what power "
            "gives x?'. Because they're inverses, their graphs are mirror images "
            "across the line y = x — every (x, y) on bˣ becomes (y, x) on log_b. "
            "That's why the log grows so slowly: it's the exponential turned on its "
            "side."
        ),
        "bullets": [
            "log_b(x) is the exponent: b^(log_b x) = x.",
            "bˣ and log_b(x) are reflections across y = x (inverse functions).",
            "The log is only defined for x > 0 and rises ever more slowly.",
        ],
        "params": [
            {"name": "b", "label": "base  b", "min": 1.2, "max": 4, "step": 0.1, "value": 2},
        ],
        "code": r"""
H.background();
const v = H.plot2d({ xMin: -6, xMax: 6, yMin: -6, yMax: 6 });
v.grid(); v.axes();
const b = Math.min(5, Math.max(1.2, P.b));
v.line(-6, -6, 6, 6, { color: H.colors.violet, width: 1.5, dash: [5, 5] });
v.fn(x => Math.pow(b, x), { color: H.colors.accent, width: 3 });
v.fn(x => (x > 0 ? Math.log(x) / Math.log(b) : NaN), { color: H.colors.accent2, width: 3 });
const xs = 2.4 * Math.sin(t * 0.6);
v.dot(xs, Math.pow(b, xs), { r: 5, fill: H.colors.warn });
H.text("y = bˣ  and its inverse  y = log_b(x)", 24, 30, { color: H.colors.ink, size: 17, weight: 700 });
H.text("base b = " + b.toFixed(2) + "  —  mirror images across y = x", 24, 52, { color: H.colors.sub, size: 13 });
H.legend([{ label: "bˣ", color: H.colors.accent }, { label: "log_b x", color: H.colors.accent2 }, { label: "y = x", color: H.colors.violet }], H.W - 150, 28);
""".strip(),
    },
    {
        "id": "function-transformations",
        "area": "Algebra 2",
        "topic": "Transformations",
        "title": "Transformations: y = a·f(b(x − h)) + k",
        "equation": "y = a · f(b(x − h)) + k",
        "keywords": [
            "transformation", "shift", "stretch", "translate", "reflect", "compress",
            "parent function", "horizontal vertical shift", "scaling", "transformations",
        ],
        "explanation": (
            "Every function family shares the same four moves applied to a parent "
            "f(x). k shifts it up/down and h shifts it left/right (note: x − h moves "
            "RIGHT by h). a stretches it vertically (and flips it if negative); b "
            "stretches it horizontally — and bigger b actually SQUEEZES it. Compare "
            "the faint parent curve to the bold transformed one."
        ),
        "bullets": [
            "Outside the function (a, k): vertical stretch and shift.",
            "Inside (b, h): horizontal — and they work 'backwards' (x − h moves right).",
            "Negative a or b reflects across the x- or y-axis.",
        ],
        "params": [
            {"name": "a", "label": "vert stretch  a", "min": -3, "max": 3, "step": 0.1, "value": 1},
            {"name": "b", "label": "horiz squeeze  b", "min": 0.2, "max": 3, "step": 0.1, "value": 1},
            {"name": "h", "label": "shift right  h", "min": -4, "max": 4, "step": 0.5, "value": 0},
            {"name": "k", "label": "shift up  k", "min": -4, "max": 6, "step": 0.5, "value": 0},
        ],
        "code": r"""
H.background();
const v = H.plot2d({ xMin: -8, xMax: 8, yMin: -6, yMax: 10 });
v.grid(); v.axes();
const a = P.a, b = Math.max(0.1, P.b), h = P.h, k = P.k;
const base = (x) => Math.sin(x);
v.fn(base, { color: H.colors.sub, width: 1.5 });
v.fn(x => a * base(b * (x - h)) + k, { color: H.colors.accent, width: 3 });
const xs = 6 * Math.sin(t * 0.6);
v.dot(xs, a * base(b * (xs - h)) + k, { r: 6, fill: H.colors.warn });
H.text("y = a · f(b(x − h)) + k", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("a=" + a.toFixed(1) + "  b=" + b.toFixed(1) + "  h=" + h.toFixed(1) + "  k=" + k.toFixed(1), 24, 52, { color: H.colors.sub, size: 13 });
H.legend([{ label: "parent  f(x)=sin x", color: H.colors.sub }, { label: "transformed", color: H.colors.accent }], H.W - 230, 28);
""".strip(),
    },
    {
        "id": "unit-circle",
        "area": "Geometry & Trig",
        "topic": "Unit circle",
        "title": "Unit circle: (cos θ, sin θ)",
        "equation": "(x, y) = (cos θ, sin θ)",
        "keywords": [
            "unit circle", "cosine", "sine", "trig", "angle", "radians", "degrees",
            "cos sin", "reference angle", "trigonometry",
        ],
        "explanation": (
            "Spin the angle θ and the point rides a circle of radius 1. Its shadow "
            "on the x-axis IS cos θ and its height above the x-axis IS sin θ — that's "
            "the definition of cosine and sine. The dashed legs show exactly those "
            "two lengths. One full trip around is 360° (2π radians)."
        ),
        "bullets": [
            "cos θ is the x-coordinate; sin θ is the y-coordinate, on radius 1.",
            "cos²θ + sin²θ = 1 — it's the Pythagorean theorem on the circle.",
            "360° = 2π radians; the signs flip by quadrant.",
        ],
        "params": [
            {"name": "deg", "label": "angle θ (degrees)", "min": 0, "max": 360, "step": 1, "value": 45},
        ],
        "code": r"""
H.background();
const cx = H.W * 0.5, cy = H.H * 0.52, R = Math.min(H.W, H.H) * 0.3;
const ang = P.deg * Math.PI / 180;
H.circle(cx, cy, R, { stroke: H.colors.grid, width: 1.5 });
H.line(cx - R - 12, cy, cx + R + 12, cy, { color: H.colors.axis, width: 1 });
H.line(cx, cy - R - 12, cx, cy + R + 12, { color: H.colors.axis, width: 1 });
const px = cx + R * Math.cos(ang), py = cy - R * Math.sin(ang);
H.line(cx, cy, px, py, { color: H.colors.accent2, width: 2 });
H.line(px, py, px, cy, { color: H.colors.good, width: 2, dash: [4, 4] });
H.line(px, py, cx, py, { color: H.colors.accent, width: 2, dash: [4, 4] });
H.circle(px, py, 6 + Math.sin(t * 3), { fill: H.colors.warn });
H.text("Unit circle: (cos θ, sin θ)", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("θ = " + P.deg.toFixed(0) + "°    cos θ = " + Math.cos(ang).toFixed(2) + "    sin θ = " + Math.sin(ang).toFixed(2), 24, 52, { color: H.colors.sub, size: 13 });
H.legend([{ label: "cos θ", color: H.colors.accent }, { label: "sin θ", color: H.colors.good }], H.W - 150, 28);
""".strip(),
    },
    {
        "id": "sine-wave",
        "area": "Precalculus",
        "topic": "Sinusoids",
        "title": "Sine wave: y = A·sin(B(x − C)) + D",
        "equation": "y = A·sin(B(x − C)) + D",
        "keywords": [
            "sine", "sinusoid", "amplitude", "period", "phase shift", "frequency",
            "trig graph", "cosine wave", "midline", "sine function", "wave",
        ],
        "explanation": (
            "Four knobs shape every sinusoid. A is the amplitude (how tall above and "
            "below the midline). B sets the frequency — the period is 2π/B, so "
            "bigger B means tighter waves. C is the phase shift (slides the wave "
            "left/right) and D is the midline (slides it up/down). Watch the dot "
            "ride the wave as you tune them."
        ),
        "bullets": [
            "Amplitude A = half the peak-to-trough height.",
            "Period = 2π / B (bigger B -> shorter period).",
            "C shifts horizontally; D is the midline the wave oscillates about.",
        ],
        "params": [
            {"name": "A", "label": "amplitude  A", "min": 0.2, "max": 4, "step": 0.1, "value": 2},
            {"name": "B", "label": "frequency  B", "min": 0.2, "max": 4, "step": 0.1, "value": 1},
            {"name": "C", "label": "phase shift  C", "min": -3, "max": 3, "step": 0.1, "value": 0},
            {"name": "D", "label": "midline  D", "min": -3, "max": 3, "step": 0.5, "value": 0},
        ],
        "code": r"""
H.background();
const v = H.plot2d({ xMin: -Math.PI, xMax: 3 * Math.PI, yMin: -6, yMax: 6 });
v.grid(); v.axes();
const A = P.A, B = Math.max(0.1, P.B), C = P.C, D = P.D;
v.line(-Math.PI, D, 3 * Math.PI, D, { color: H.colors.violet, width: 1.5, dash: [5, 5] });
v.fn(x => A * Math.sin(B * (x - C)) + D, { color: H.colors.accent, width: 3 });
const xs = -Math.PI + ((t * 0.8) % (4 * Math.PI));
v.dot(xs, A * Math.sin(B * (xs - C)) + D, { r: 6, fill: H.colors.warn });
H.text("y = A·sin(B(x − C)) + D", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("A = " + A.toFixed(1) + "   period = " + (2 * Math.PI / B).toFixed(2) + "   C = " + C.toFixed(1) + "   D = " + D.toFixed(1), 24, 52, { color: H.colors.sub, size: 12 });
""".strip(),
    },
    {
        "id": "ellipse",
        "area": "Precalculus",
        "topic": "Conic sections",
        "title": "Ellipse: x²/a² + y²/b² = 1",
        "equation": "x²/a² + y²/b² = 1",
        "keywords": [
            "ellipse", "conic", "conic section", "foci", "major axis", "minor axis",
            "oval", "eccentricity", "semi axis",
        ],
        "explanation": (
            "An ellipse is the set of points whose distances to two fixed foci add "
            "to a constant. a and b are the semi-axes (half-widths) along x and y; "
            "when a = b you get a circle. The foci sit on the longer axis at "
            "distance c = √|a² − b²| from the center — the more a and b differ, the "
            "more stretched (eccentric) the ellipse."
        ),
        "bullets": [
            "a and b are the semi-axis lengths along x and y; a = b is a circle.",
            "Foci lie on the major axis at c = √|a² − b²| from the center.",
            "Sum of distances to the two foci is constant for every point.",
        ],
        "params": [
            {"name": "a", "label": "semi-axis  a", "min": 0.5, "max": 7, "step": 0.5, "value": 5},
            {"name": "b", "label": "semi-axis  b", "min": 0.5, "max": 5, "step": 0.5, "value": 3},
        ],
        "code": r"""
H.background();
const v = H.plot2d({ xMin: -8, xMax: 8, yMin: -6, yMax: 6 });
v.grid(); v.axes();
const a = Math.max(0.5, P.a), b = Math.max(0.5, P.b);
const pts = [];
for (let i = 0; i <= 90; i++) { const th = i / 90 * H.TAU; pts.push([a * Math.cos(th), b * Math.sin(th)]); }
v.path(pts, { color: H.colors.accent, width: 3, close: true });
const c = Math.sqrt(Math.abs(a * a - b * b));
if (a >= b) { v.dot(c, 0, { r: 5, fill: H.colors.warn }); v.dot(-c, 0, { r: 5, fill: H.colors.warn }); }
else { v.dot(0, c, { r: 5, fill: H.colors.warn }); v.dot(0, -c, { r: 5, fill: H.colors.warn }); }
const th = t * 0.8;
v.dot(a * Math.cos(th), b * Math.sin(th), { r: 6, fill: H.colors.accent2 });
H.text("Ellipse:  x²/a² + y²/b² = 1", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("a = " + a.toFixed(1) + "   b = " + b.toFixed(1) + "   foci at c = " + c.toFixed(2), 24, 52, { color: H.colors.sub, size: 13 });
""".strip(),
    },
]

# Demos authored + validated by the algebra-precalc-demos workflow (one per
# Algebra 1 / Algebra 2 / Precalculus topic), re-checked through
# validate_scene.js so every code runs, paints on-screen, animates, and is
# labeled. Stored as data in demo_library_generated.json and merged here. Kept
# separate from _BASE so the hand-verified baseline is always present.
import json as _json
from pathlib import Path as _Path

_GENERATED: list[dict] = []
_gen_path = _Path(__file__).resolve().parent / "demo_library_generated.json"
try:
    _loaded = _json.loads(_gen_path.read_text(encoding="utf-8"))
    if isinstance(_loaded, list):
        _GENERATED = _loaded
except (OSError, ValueError):
    _GENERATED = []

# Hand-written demos first so they win id/keyword ties over generated ones.
DEMO_LIBRARY: list[dict] = _BASE + _GENERATED
