# Concept → visualization playbook

How to turn a STEM/ML topic into a scene that *teaches*. The hard part is rarely
the code — it's choosing **what should move** so the animation reveals the
mechanism. This file gives proven recipes for common topics and a general method
for anything not listed.

Throughout, the goal is **understanding, not an answer key**: reveal the
*mechanism* and the *general relationship* (sweep the parameter with `t`) rather
than just computing the one specific number a prompt asks for. See *Teach the
mechanism, don't solve their problem* in SKILL.md.

## The general method (use this for any concept)

1. **Name the mechanism.** What is the one idea? ("the derivative is the tangent's
   slope", "adding harmonics sharpens the wave", "the optimizer follows the
   negative gradient"). The animation exists to show *that*.
2. **Choose the moving variable.** Map the mechanism to something driven by `t`:
   a swept parameter, an accumulating sum, a propagating front, an integrated
   trajectory, a rotating viewpoint.
3. **Pick the representation:**
   - one-variable function / time series / signal → **2D `plot2d` + `fn`**
   - geometry, vectors, planar fields, circuits, graphs → **2D pixel or `plot2d`
     data-space**
   - `z = f(x,y)`, optimization landscapes → **3D `surface3d`**
   - parametric shapes (sphere, torus, tube, helix) → **3D `mesh3d`**
   - discrete bodies in space (atoms, planets, particles) → **3D `cam.sphere`,
     depth-sorted**
4. **Make the invisible legible.** Add a live readout of the key quantity, a
   legend for multiple series, axes with units. If the steady-state is static,
   animate the *construction* (sweep, accumulate, step through stages).
5. **Adapt the nearest worked scene** in `references/examples.md` rather than
   starting blank.

## Recipes by topic

Each row: the visual idea, the technique, and the closest example to adapt.

### Calculus & analysis
- **Derivative / tangent / rate of change** → plot `f`, sweep the point of
  tangency, draw the tangent in data space, print the live slope. → example 1.
- **Integral / area under a curve** → plot `f`, fill Riemann rectangles whose
  count grows with `t`, print the running sum vs the true integral.
- **Limit / secant → tangent** → draw a secant between `a` and `a+h`, shrink `h`
  with `t`, show the slope converging.
- **Taylor / power series** → plot the target faintly, overlay the partial sum
  with a breathing term count `N` (same shape as Fourier, example 2).
- **Multivariable / partial derivatives / gradient** → `surface3d` for `f(x,y)`,
  draw the gradient arrow on the surface or a contour slice. → example 7.

### Signals & linear algebra
- **Fourier series / harmonics / decomposition** → partial sums of sines with a
  breathing `N`, target behind, legend. → example 2.
- **Sine/cosine / phase / radians** → unit circle with dropped perpendiculars +
  linked sin/cos plot. → example 3.
- **Vectors / dot & cross product / projection** → 2D arrows from origin, show the
  projection foot and the angle; animate one vector rotating.
- **Matrix transform / eigenvectors** → a grid of dots under `A`, interpolate from
  identity to `A` with `t`; eigenvectors stay on their line.

### Mechanics & physics
- **Projectile / kinematics / trajectory** → faint full path + moving point +
  velocity arrow; floor physical quantities at 0. → example 4.
- **Oscillation / SHM / pendulum / spring** → position `= A*Math.cos(ω*t)`, draw
  the body + a phase plot; keep amplitude positive.
- **Waves / interference / standing waves** → 2D `fn` of `sin(kx − ωt)`, or two
  sources with summed displacement; for 3D ripples use `surface3d` (example 7's
  cousin: `sin(r − t)/r`).
- **Orbits / gravity / planetary motion** → 3D `cam.path` ellipse + a `cam.sphere`
  body moving along it, central sphere for the star.

### Electromagnetism
- **Field lines / dipole / point charges** → a `field(x,y)` function, streamlines
  by integration, a test charge advected with `t`. → example 5.
- **RC / RL / circuits / time constant** → `plot2d` of the exponential + a drawn
  component whose fill/level tracks the value. → example 6.
- **EM wave** → 3D: oscillating E (one axis) and B (perpendicular) along a
  propagation axis, both driven by `sin(kz − ωt)` via `cam.path`.

### Machine learning & optimization
- **Gradient descent / loss surface / training** → `surface3d` loss + a sphere
  stepping down the negative gradient, re-released each cycle, live loss readout.
  → example 7. (Too-large learning rate = make the steps overshoot for a variant.)
- **Linear/logistic regression fit** → 2D scatter (fixed seed via a formula, not
  randomness) + a line/curve whose parameters animate toward the fit; show the
  loss dropping.
- **Neural net / perceptron** → 2D nodes as circles, edges as lines with
  width ∝ |weight|, a pulse traveling forward; label the activation.
- **k-means / clustering** → 2D points colored by nearest centroid; move centroids
  to the mean each cycle.

### CS & algorithms
- **Graph traversal (BFS/DFS)** → fixed node positions, edges as lines, a frontier
  that expands by stage `Math.floor(t * rate)`; color visited vs frontier; legend.
- **Sorting** → bars (`H.rect`) whose heights are a fixed array; animate compares/
  swaps by stage; highlight the active pair.
- **Recursion / trees** → draw a tree by depth; reveal levels with `t`.

### Chemistry & biology
- **Molecules / crystal structure / DNA** → 3D `cam.sphere` atoms, depth-sorted,
  `cam.line` bonds, slow spin. → example 8.
- **Reaction / rate / equilibrium** → 2D concentrations vs time as `plot2d` curves
  approaching equilibrium; live readout of the ratio.

### Probability & statistics
- **Distributions / CLT / sampling** → 2D histogram (`H.rect` bars from a
  closed-form density, not RNG) + the limiting curve overlaid; grow the sample
  with `t`.
- **Bayes / conditional probability** → area/tree diagram with regions sized to
  probabilities; highlight the conditioning event.

## Notes that keep scenes correct

- **No randomness.** `scene` must be a pure function of `t` and is called every
  frame, so `Math.random()` would jitter. Use deterministic formulas, or a fixed
  hash like `frac(Math.sin(i*12.9898)*43758.5)` for "scattered" points.
- **Stage with `t`.** For discrete steps, `const stage = Math.floor(t % period / step)`
  cycles cleanly and loops.
- **Keep physical quantities physical** (lengths, probabilities, energies ≥ 0) and
  make displayed numbers match the drawing. See SKILL.md → "Correctness rules".
- **3D must look 3D.** Prefer `surface3d`/`mesh3d`/`cam.sphere` (lit, depth-sorted)
  over flat dot clouds, add `cam.grid()` + `cam.axes()` + a slow `cam.yaw = 0.3*t`.
