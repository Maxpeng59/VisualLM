# Worked scenes (complete, validated)

Eight end-to-end scenes across domains. Every one passes
`scripts/validate_scene.js` (`ok`, `painted`, `text`, `onscreen` all true) and
follows the three hard rules. Adapt the closest one rather than starting from a
blank file — match the *technique* (function plot, vector field, 3D surface,
sphere cloud) to your concept.

Each block is the `scene` body — paste it straight into the validator or
`runtime/host.html`.

---

## 1. Derivative as a moving tangent line — 2D, `plot2d` + data-space
Technique: plot `y=f(x)`, sweep the point of tangency with `t`, draw the tangent
in data space, print the live slope.

```js
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
```

## 2. Fourier series → square wave — 2D, partial sums + legend
Technique: a breathing harmonic count `N`, a partial-sum function, the target
drawn faintly behind it, a legend.

```js
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
```

## 3. Unit circle generates sine & cosine — 2D, two linked panels
Technique: a pixel-space circle with dropped perpendiculars on the left, a
`plot2d` of sin/cos on the right, sharing the angle `th`.

```js
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
```

## 4. Projectile motion — 2D, trajectory + velocity vector + live readout
Technique: precompute the full parabola as a faint dashed `path`, animate the
moving point and its velocity `arrow`, keep physical quantities non-negative
(`Math.max(0, y)`).

```js
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
```

## 5. Electric field of a dipole — 2D, vector field + streamlines (pixel space)
Technique: a `field(x,y)` function, streamlines integrated by following the field,
a test charge advected with `t`. Pure pixel space (no `plot2d`) because the field
is over the whole canvas.

```js
H.background();
const w = H.W, h = H.H;
const q1 = { x: w * 0.38, y: h * 0.52, s: +1 };
const q2 = { x: w * 0.62, y: h * 0.52, s: -1 };
function field(x, y) {
  let ex = 0, ey = 0;
  for (const q of [q1, q2]) {
    const dx = x - q.x, dy = y - q.y;
    const r2 = dx * dx + dy * dy + 80;
    const r = Math.sqrt(r2);
    const e = q.s / r2;
    ex += e * dx / r; ey += e * dy / r;
  }
  return [ex, ey];
}
for (let k = 0; k < 16; k++) {
  const a0 = (k / 16) * H.TAU;
  let x = q1.x + 16 * Math.cos(a0), y = q1.y + 16 * Math.sin(a0);
  const pts = [[x, y]];
  for (let i = 0; i < 220; i++) {
    const [ex, ey] = field(x, y);
    const m = Math.hypot(ex, ey) + 1e-9;
    x += 3 * ex / m; y += 3 * ey / m;
    if (x < 0 || x > w || y < 0 || y > h) break;
    if (Math.hypot(x - q2.x, y - q2.y) < 14) break;
    pts.push([x, y]);
  }
  H.path(pts, { color: H.colors.accent, width: 1.4 });
}
const tt = (t % 6) / 6;
let tx = H.lerp(q1.x, q2.x, 0.15), ty = q1.y - 70;
for (let i = 0; i < Math.floor(tt * 200); i++) {
  const [ex, ey] = field(tx, ty); const m = Math.hypot(ex, ey) + 1e-9;
  tx += 2.4 * ex / m; ty += 2.4 * ey / m;
}
H.circle(tx, ty, 6, { fill: H.colors.yellow, stroke: H.colors.bg, width: 2 });
H.circle(q1.x, q1.y, 13, { fill: H.colors.warn });
H.circle(q2.x, q2.y, 13, { fill: H.colors.accent2 });
H.text("+", q1.x - 5, q1.y + 5, { color: H.colors.bg, size: 16, weight: 700 });
H.text("-", q2.x - 4, q2.y + 5, { color: H.colors.bg, size: 18, weight: 700 });
H.text("Electric field of a dipole", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text("test charge along the field, t = " + (t % 6).toFixed(1) + "s", 24, 52, { color: H.colors.sub, size: 13 });
```

## 6. RC circuit charging a capacitor — 2D, plot + schematic with live fill
Technique: a `plot2d` of the exponential on the left, a drawn capacitor whose fill
height tracks `V` on the right, a charge/discharge cycle from `t`.

```js
H.background();
const RC = 1.6, V0 = 5;
const cycle = t % 8;
const charging = cycle < 5;
const tau = charging ? cycle : cycle - 5;
const V = charging ? V0 * (1 - Math.exp(-tau / RC)) : V0 * Math.exp(-tau / RC);
const v = H.plot2d({ xMin: 0, xMax: 5, yMin: 0, yMax: 5.5, box: { x: 70, y: 70, w: H.W * 0.5, h: H.H - 150 } });
v.grid(); v.axes();
v.fn((x) => V0 * (1 - Math.exp(-x / RC)), { color: H.colors.sub, width: 1.5 });
v.line(RC, 0, RC, V0, { color: H.colors.violet, width: 1.5, dash: [5, 5] });
v.dot(tau, V, { r: 7, fill: H.colors.good });
v.text("t = RC", RC + 0.1, 0.5, { color: H.colors.violet, size: 12 });
const bx = H.W * 0.68, by = 120, bw = 220, bh = 260;
H.rect(bx, by, bw, bh, { stroke: H.colors.axis, width: 2, radius: 8 });
H.text("battery", bx + 10, by + 24, { color: H.colors.sub, size: 12 });
const capX = bx + bw - 60, capY = by + 60, capH = 140;
H.rect(capX, capY, 36, capH, { stroke: H.colors.accent, width: 2 });
H.rect(capX + 3, capY + capH - capH * (V / V0) + 3, 30, capH * (V / V0) - 6, { fill: H.colors.accent });
H.text("Q", capX + 44, capY + capH / 2, { color: H.colors.accent, size: 14 });
H.text("RC circuit: charging a capacitor", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
H.text((charging ? "charging" : "discharging") + "   V = " + V.toFixed(2) + " V", 24, 52, { color: H.colors.sub, size: 14 });
```

## 7. Gradient descent on a loss surface — 3D, `surface3d` + descending sphere
Technique: `H.surface3d` for the loss, an optimizer point re-released from a corner
each cycle and stepped along the negative gradient, `cam.yaw = 0.3*t` spin.

```js
H.background();
const cam = H.cam3d({ scale: 70, dist: 16, pitch: -0.5, cy: H.H * 0.56 });
cam.yaw = 0.3 * t;
const loss = (x, y) => 0.6 * (x * x + y * y) - 1.1 * Math.exp(-((x - 1) ** 2 + (y - 1) ** 2));
cam.grid(3, 1);
H.surface3d(cam, loss, { xMin: -2.6, xMax: 2.6, yMin: -2.6, yMax: 2.6, nx: 34, ny: 34, alpha: 0.9 });
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
```

## 8. DNA double helix — 3D, sphere cloud + depth sort + bonds
Technique: build two antiparallel strands of spheres, **depth-sort descending**
before drawing so near atoms occlude far ones, bonds via `cam.line`.

```js
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
```
