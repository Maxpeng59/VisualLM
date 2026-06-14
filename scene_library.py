"""Curated, hand-verified STEM scene library for VisualLM.

This is the retrieval corpus behind the "instant + always correct" fast path:
a prompt that strongly matches an entry's `keywords` renders one of these
vetted scenes immediately, with no model call (see library_match in main.py).

Each entry is a complete scene the renderer can run as-is. Every `code` here
is validated by validate_scene.js (run `python3 -m unittest tests.test_main`,
which checks the whole library). Scenes authored/verified by the
stem-scene-library workflow are appended to `_GENERATED` at the bottom.

To add a scene by hand: follow the H API contract in sandbox-worker.js /
main.py's SCENE_SYSTEM_PROMPT, give it broad synonym-rich keywords, and keep
it animated + labeled.
"""
from __future__ import annotations

_BASE: list[dict] = [
    {
        "id": "fourier-square-wave",
        "title": "Fourier series → square wave",
        "tag": "Signals",
        "dimension": "2D",
        "equation": "f(x) = (4/pi) * sum sin((2k-1)x)/(2k-1)",
        "summary": "Odd harmonics add up to approximate a square wave; more terms = sharper edges.",
        "keywords": [
            "fourier", "fourier series", "square wave", "harmonics", "sine",
            "sum of sines", "signal", "decomposition", "approximation",
        ],
        "bullets": [
            "Each term is an odd harmonic: sin(x), sin(3x)/3, sin(5x)/5, ...",
            "Adding more harmonics sharpens the corners toward a true square wave.",
            "The ripple near the jump never fully vanishes (Gibbs phenomenon).",
        ],
        "student_prompts": [
            "Why only odd harmonics?",
            "What is the Gibbs phenomenon?",
            "How many terms to get within 1% of a square wave?",
        ],
        "code": r"""
H.background();
const v = H.plot2d({ xMin: -Math.PI, xMax: Math.PI, yMin: -1.5, yMax: 1.5, pad: 50 });
v.grid(); v.axes();
const N = 1 + Math.floor((1 + Math.sin(t * 0.5)) * 5);   // 1..11 harmonics, breathing
const partial = (x) => {
  let s = 0;
  for (let k = 1; k <= N; k++) s += Math.sin((2 * k - 1) * x) / (2 * k - 1);
  return (4 / Math.PI) * s;
};
v.fn((x) => Math.sign(Math.sin(x)) || 0, { color: H.colors.sub, width: 1.5 });
v.fn(partial, { color: H.colors.accent, width: 3 });
H.text("Fourier series of a square wave", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("harmonics N = " + N, 24, 52, { color: H.colors.accent, size: 14 });
H.legend([{ label: "target square", color: H.colors.sub }, { label: "partial sum", color: H.colors.accent }], H.W - 170, 28);
""".strip(),
    },
    {
        "id": "unit-circle-sin-cos",
        "title": "Unit circle generates sine and cosine",
        "tag": "Trigonometry",
        "dimension": "2D",
        "equation": "(cos t, sin t)",
        "summary": "A point sweeping the unit circle traces cosine on x and sine on y.",
        "keywords": [
            "unit circle", "sine", "cosine", "trig", "trigonometry", "angle",
            "radians", "sin", "cos", "rotation",
        ],
        "bullets": [
            "The angle theta grows with time; the point is at (cos theta, sin theta).",
            "Its height above the axis IS sin(theta); its horizontal offset is cos(theta).",
            "One full revolution is 2*pi radians.",
        ],
        "student_prompts": [
            "Why is the radius always 1?",
            "How do radians relate to degrees?",
            "Where is cosine negative on the circle?",
        ],
        "code": r"""
H.background();
const cx = H.W * 0.28, cy = H.H * 0.52, R = Math.min(H.W, H.H) * 0.28;
const th = t * 0.8;
H.circle(cx, cy, R, { stroke: H.colors.grid, width: 1.5 });
H.line(cx - R - 10, cy, cx + R + 10, cy, { color: H.colors.axis, width: 1 });
H.line(cx, cy - R - 10, cx, cy + R + 10, { color: H.colors.axis, width: 1 });
const px = cx + R * Math.cos(th), py = cy - R * Math.sin(th);
H.line(cx, cy, px, py, { color: H.colors.accent2, width: 2 });
H.line(px, py, px, cy, { color: H.colors.good, width: 2, dash: [4, 4] });
H.line(px, py, cx, py, { color: H.colors.accent, width: 2, dash: [4, 4] });
H.circle(px, py, 6, { fill: H.colors.warn });
const v = H.plot2d({ xMin: 0, xMax: 12, yMin: -1.3, yMax: 1.3, box: { x: H.W * 0.56, y: 70, w: H.W * 0.4, h: H.H - 150 } });
v.grid(); v.axes();
v.fn((x) => Math.sin(x), { color: H.colors.good, width: 2.5 });
v.fn((x) => Math.cos(x), { color: H.colors.accent, width: 2.5 });
v.dot(th % 12, Math.sin(th));
H.text("Unit circle → sine & cosine", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("theta = " + (th % (2 * Math.PI)).toFixed(2) + " rad", 24, 52, { color: H.colors.sub, size: 14 });
H.legend([{ label: "sin", color: H.colors.good }, { label: "cos", color: H.colors.accent }], H.W * 0.56, 50);
""".strip(),
    },
    {
        "id": "projectile-motion",
        "title": "Projectile motion",
        "tag": "Mechanics",
        "dimension": "2D",
        "equation": "x = v0 cos(a) t,  y = v0 sin(a) t - g t^2 / 2",
        "summary": "A launched projectile follows a parabola; horizontal speed is constant, vertical speed changes under gravity.",
        "keywords": [
            "projectile", "projectile motion", "parabola", "trajectory", "launch",
            "gravity", "kinematics", "ballistic", "range", "velocity",
        ],
        "bullets": [
            "Horizontal velocity stays constant; only gravity acts vertically.",
            "The path is a parabola; peak height is where vertical velocity is zero.",
            "Range is maximized at a 45 degree launch angle (no air resistance).",
        ],
        "student_prompts": [
            "Why is 45 degrees the optimal angle?",
            "How long is the projectile in the air?",
            "What is the speed at the peak?",
        ],
        "code": r"""
H.background();
const g = 9.8, v0 = 22, ang = 58 * Math.PI / 180;
const flight = 2 * v0 * Math.sin(ang) / g;
const tau = (t % (flight + 1));
const xr = v0 * Math.cos(ang) * tau;
const yr = Math.max(0, v0 * Math.sin(ang) * tau - 0.5 * g * tau * tau);
const v = H.plot2d({ xMin: 0, xMax: 60, yMin: 0, yMax: 26, pad: 50 });
v.grid(); v.axes();
const path = [];
for (let i = 0; i <= 60; i++) {
  const tt = i / 60 * flight;
  path.push([v0 * Math.cos(ang) * tt, v0 * Math.sin(ang) * tt - 0.5 * g * tt * tt]);
}
v.path(path, { color: H.colors.sub, width: 1.5, dash: [6, 5] });
const vx = v0 * Math.cos(ang), vy = v0 * Math.sin(ang) - g * tau;
v.arrow(xr, yr, xr + vx * 0.25, yr + vy * 0.25, { color: H.colors.good, width: 2 });
v.dot(xr, yr, { r: 7, fill: H.colors.warn });
H.text("Projectile: 22 m/s at 58 deg", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("x = " + xr.toFixed(1) + " m   y = " + yr.toFixed(1) + " m", 24, 52, { color: H.colors.sub, size: 14 });
""".strip(),
    },
    {
        "id": "derivative-tangent",
        "title": "Derivative as a moving tangent line",
        "tag": "Calculus",
        "dimension": "2D",
        "equation": "f'(a) = slope of the tangent at x = a",
        "summary": "The derivative at a point is the slope of the tangent line there; watch it sweep along the curve.",
        "keywords": [
            "derivative", "tangent", "tangent line", "slope", "calculus",
            "differentiation", "rate of change", "instantaneous",
        ],
        "bullets": [
            "The tangent line touches the curve at one point and matches its slope.",
            "Slope = f'(a); it changes as the point of tangency moves.",
            "Where the curve is flat the derivative is zero.",
        ],
        "student_prompts": [
            "What does a negative slope mean here?",
            "Where is the derivative zero?",
            "How is this the limit of a secant line?",
        ],
        "code": r"""
H.background();
const v = H.plot2d({ xMin: -3.2, xMax: 3.2, yMin: -3, yMax: 5, pad: 50 });
v.grid(); v.axes();
const f = (x) => 0.15 * x * x * x - x;
const df = (x) => 0.45 * x * x - 1;
v.fn(f, { color: H.colors.accent, width: 3 });
const a = 2.6 * Math.sin(t * 0.6);
const slope = df(a);
const tx = (x) => f(a) + slope * (x - a);
v.line(-3.2, tx(-3.2), 3.2, tx(3.2), { color: H.colors.accent2, width: 2.4, dash: [7, 6] });
v.dot(a, f(a), { r: 7 });
H.text("Derivative = slope of the tangent", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("a = " + a.toFixed(2) + "    f'(a) = " + slope.toFixed(2), 24, 52, { color: H.colors.sub, size: 14 });
""".strip(),
    },
    {
        "id": "gradient-descent-3d",
        "title": "Gradient descent on a loss surface",
        "tag": "Machine Learning",
        "dimension": "3D",
        "equation": "x <- x - lr * grad f(x)",
        "summary": "A ball rolls downhill along the negative gradient of a 3D loss surface toward the minimum.",
        "keywords": [
            "gradient descent", "loss surface", "optimization", "machine learning",
            "minimum", "gradient", "training", "cost function", "3d surface",
        ],
        "bullets": [
            "The surface height is the loss; lower is better.",
            "Each step moves opposite the gradient — the steepest downhill direction.",
            "The learning rate sets the step size; too big overshoots, too small crawls.",
        ],
        "student_prompts": [
            "What happens if the learning rate is too large?",
            "How do local minima trap gradient descent?",
            "What is the gradient, intuitively?",
        ],
        "code": r"""
H.background();
const cam = H.cam3d({ scale: 70, dist: 16, pitch: -0.5, cy: H.H * 0.56 });
cam.yaw = 0.3 * t;
const loss = (x, y) => 0.6 * (x * x + y * y) - 1.1 * Math.exp(-((x - 1) ** 2 + (y - 1) ** 2));
cam.grid(3, 1);
H.surface3d(cam, loss, { xMin: -2.6, xMax: 2.6, yMin: -2.6, yMax: 2.6, nx: 34, ny: 34, alpha: 0.9 });
// A descending point, re-released every few seconds from a corner.
let px = 2.2, py = 2.2;
const steps = Math.floor((t % 6) * 14);
for (let i = 0; i < steps; i++) {
  const gx = 1.2 * px + 1.1 * 2 * (px - 1) * Math.exp(-((px - 1) ** 2 + (py - 1) ** 2));
  const gy = 1.2 * py + 1.1 * 2 * (py - 1) * Math.exp(-((px - 1) ** 2 + (py - 1) ** 2));
  px -= 0.06 * gx; py -= 0.06 * gy;
}
cam.sphere([px, loss(px, py) + 0.15, py], 0.18, { color: H.colors.warn });
cam.axes(3);
H.text("Gradient descent on a loss surface", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("loss = " + loss(px, py).toFixed(3), 24, 52, { color: H.colors.sub, size: 14 });
""".strip(),
    },
    {
        "id": "dna-double-helix",
        "title": "DNA double helix",
        "tag": "Biology",
        "dimension": "3D",
        "equation": "two antiparallel strands + base pairs",
        "summary": "Two sugar-phosphate backbones twist around a common axis, joined by base pairs.",
        "keywords": [
            "dna", "double helix", "helix", "genetics", "base pairs", "nucleotide",
            "molecular biology", "strands", "chromosome",
        ],
        "bullets": [
            "Two strands run in opposite (antiparallel) directions.",
            "Base pairs (the rungs) hold the strands together.",
            "The whole structure twists into a right-handed double helix.",
        ],
        "student_prompts": [
            "Which bases pair with which?",
            "What does antiparallel mean?",
            "How is DNA copied?",
        ],
        "code": r"""
H.background();
const cam = H.cam3d({ scale: 34, dist: 18, pitch: -0.2 });
cam.yaw = 0.5 * t;
const balls = [];
const N = 34;
for (let i = 0; i < N; i++) {
  const s = i / (N - 1);
  const ang = s * H.TAU * 2.1 + t * 0.3;
  const ypos = (s - 0.5) * 9;
  const a = [2.1 * Math.cos(ang), ypos, 2.1 * Math.sin(ang)];
  const b = [-2.1 * Math.cos(ang), ypos, -2.1 * Math.sin(ang)];
  balls.push({ p: a, color: H.colors.accent, r: 0.32 });
  balls.push({ p: b, color: H.colors.accent2, r: 0.32 });
  if (i % 3 === 0) cam.line(a, b, { color: H.colors.sub, width: 1.6 });
}
balls
  .map((o) => ({ ...o, depth: cam.project(o.p).depth }))
  .sort((a, b) => b.depth - a.depth)
  .forEach((o) => cam.sphere(o.p, o.r, { color: o.color }));
H.text("DNA double helix", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("two antiparallel strands joined by base pairs", 24, 52, { color: H.colors.sub, size: 13 });
""".strip(),
    },
]

# Scenes authored + adversarially verified by the stem-scene-library workflow
# are appended here. Kept separate from _BASE so the hand-verified baseline is
# always present even if the generated batch is regenerated.
_GENERATED: list[dict] = []

SCENE_LIBRARY: list[dict] = _BASE + _GENERATED
