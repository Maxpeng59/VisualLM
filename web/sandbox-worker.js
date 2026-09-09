/*
 * VisualLM sandbox worker.
 *
 * Runs AI-generated animation code inside a dedicated Web Worker with an
 * OffscreenCanvas. The worker has no DOM access and no same-origin window, so
 * generated code cannot touch the page, cookies, or storage. Network access is
 * additionally blocked by the page CSP (connect-src 'none'). If generated code
 * hangs (e.g. `while (true)`), the worker stops emitting heartbeats and the main
 * thread terminates and recreates it.
 *
 * Contract for generated code: it is the *body* of
 *     function scene(ctx, t, H) { ... }
 * called once per frame. `t` is elapsed seconds (honoring pause + speed). The
 * function must fully redraw each frame. `H` is the helper library below.
 */

// Defense in depth: strip network / module APIs from the worker scope before
// any generated code runs. The worker already has no DOM and no same-origin
// window; removing these closes the remaining exfiltration paths.
try {
  self.fetch = undefined;
  self.XMLHttpRequest = undefined;
  self.WebSocket = undefined;
  self.EventSource = undefined;
  self.indexedDB = undefined;
  // Block sub-workers: without this, generated code could spawn a sub-worker
  // from a Blob URL (`new Worker(URL.createObjectURL(new Blob([...])))`) and
  // get a fresh global scope with fetch/XHR re-enabled — escaping the strip
  // we just did. The page also has no CSP `worker-src`, so the browser would
  // not block it on its own.
  self.Worker = undefined;
  self.SharedWorker = undefined;
  // sendBeacon and WebTransport are alternate POST/UDP channels available in
  // worker scope; BroadcastChannel can leak to other same-origin tabs.
  self.WebTransport = undefined;
  self.BroadcastChannel = undefined;
  if (self.navigator) {
    try {
      self.navigator.sendBeacon = undefined;
    } catch (e) {
      /* ignore */
    }
  }
  self.importScripts = function () {
    throw new Error("importScripts is disabled in the sandbox.");
  };
} catch (e) {
  /* ignore */
}

let canvas = null;
let ctx = null;
let dpr = 1;
let logicalW = 0;
let logicalH = 0;

let sceneFn = null;
let running = false;
let paused = false;
let speed = 1;
let suspended = false; // true when the tab is hidden — stop drawing to save CPU
let needsRender = false; // repaint paused scenes only when their visible state changes

// User-driven camera orbit, applied on top of whatever yaw/pitch the scene
// sets. Updated by "orbit" messages from the main thread (canvas drag/wheel),
// reset when a new scene loads. Every cam3d instance reads these, so dragging
// rotates any 3D scene without the generated code having to cooperate.
const orbit = { yaw: 0, pitch: 0, zoom: 1 };

let simTime = 0; // accumulated, speed-scaled seconds passed to scene()
let lastWall = 0; // last wall-clock timestamp (ms)
let frameCount = 0;
// Per-frame error tolerance. A scene that has rendered at least one clean frame
// (everRendered) is kept alive through an occasional throwing frame rather than
// being killed and shipped to the slow repair loop. Only a first-frame failure
// or a sustained run of throwing frames escalates to a real runtime-error.
let consecutiveErrors = 0;
let everRendered = false;
let lastCode = ""; // raw source of the running scene, for offending-line lookup
let curParams = {}; // user-set demo parameters, exposed to the scene as `P`
let loopTimer = null;

const FRAME_MS = 1000 / 60;

function post(msg) {
  self.postMessage(msg);
}

/* ------------------------------------------------------------------ */
/* Helper library handed to generated code as `H`.                     */
/* ------------------------------------------------------------------ */

const TAU = Math.PI * 2;

// Two palettes so the animation canvas can follow the app's light/dark toggle.
// COLORS and PALETTE are mutated IN PLACE by applyTheme() — their object/array
// identity never changes, so `H.colors`/`H.palette` (and any running scene that
// reads them each frame) pick up a theme switch live, with no recompile.
const THEMES = {
  dark: {
    bg: "#0e1525", bgTop: "#101a31", panel: "#16203a",
    ink: "#eef2ff", sub: "#9fb0d4", grid: "#26314f", axis: "#566087",
    accent: "#7cc4ff", accent2: "#f4a259", good: "#67e8b0", warn: "#ff8aa0",
    violet: "#c4a7ff", yellow: "#ffe08a", quadEdge: "rgba(10,14,30,0.35)",
    palette: ["#7cc4ff", "#f4a259", "#67e8b0", "#c4a7ff", "#ff8aa0", "#ffe08a", "#5eead4", "#fca5f1"],
  },
  light: {
    bg: "#f4f6fb", bgTop: "#ffffff", panel: "#e7ecf6",
    ink: "#16203a", sub: "#4a5578", grid: "#d4dbea", axis: "#9aa6c4",
    accent: "#2f7fd1", accent2: "#d9772b", good: "#1aa06a", warn: "#e0506a",
    violet: "#8b5cf6", yellow: "#c79214", quadEdge: "rgba(40,50,80,0.22)",
    palette: ["#2f7fd1", "#d9772b", "#1aa06a", "#8b5cf6", "#e0506a", "#c79214", "#0e9aa7", "#d83f87"],
  },
};

const COLORS = {};
const PALETTE = [];
let THEME_NAME = "dark";
function applyTheme(name) {
  THEME_NAME = name === "light" ? "light" : "dark";
  const t = THEMES[THEME_NAME];
  for (const k in COLORS) delete COLORS[k];
  for (const k in t) if (k !== "palette") COLORS[k] = t[k];
  PALETTE.length = 0;
  for (const c of t.palette) PALETTE.push(c);
}
applyTheme("dark");

function clamp(x, lo, hi) {
  return x < lo ? lo : x > hi ? hi : x;
}
function lerp(a, b, t) {
  return a + (b - a) * t;
}
function map(x, inMin, inMax, outMin, outMax) {
  if (inMax === inMin) return outMin;
  return outMin + ((x - inMin) * (outMax - outMin)) / (inMax - inMin);
}
function ease(t) {
  t = clamp(t, 0, 1);
  return t * t * (3 - 2 * t);
}

function makeHelpers() {
  const H = {
    TAU,
    PI: Math.PI,
    colors: COLORS,
    palette: PALETTE,
    get theme() {
      return THEME_NAME;
    },
    clamp,
    lerp,
    map,
    ease,
    get W() {
      return logicalW;
    },
    get H() {
      return logicalH;
    },
    clear(color) {
      ctx.save();
      ctx.fillStyle = color || COLORS.bg;
      ctx.fillRect(0, 0, logicalW, logicalH);
      ctx.restore();
    },
    background(top, bottom) {
      const g = ctx.createLinearGradient(0, 0, 0, logicalH);
      g.addColorStop(0, top || COLORS.bgTop);
      g.addColorStop(1, bottom || COLORS.bg);
      ctx.save();
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, logicalW, logicalH);
      ctx.restore();
    },
    text(str, x, y, opts) {
      opts = opts || {};
      ctx.save();
      const size = opts.size || 16;
      const weight = opts.weight || 500;
      const family =
        opts.font || "system-ui, -apple-system, 'Segoe UI', sans-serif";
      ctx.font = `${weight} ${size}px ${family}`;
      ctx.fillStyle = opts.color || COLORS.ink;
      ctx.textAlign = opts.align || "left";
      ctx.textBaseline = opts.baseline || "alphabetic";
      if (opts.maxWidth) ctx.fillText(String(str), x, y, opts.maxWidth);
      else ctx.fillText(String(str), x, y);
      ctx.restore();
    },
    line(x1, y1, x2, y2, opts) {
      opts = opts || {};
      ctx.save();
      ctx.strokeStyle = opts.color || COLORS.axis;
      ctx.lineWidth = opts.width || 1.5;
      ctx.lineCap = opts.cap || "round";
      if (opts.dash) ctx.setLineDash(opts.dash);
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      ctx.restore();
    },
    path(points, opts) {
      if (!points || points.length < 2) return;
      opts = opts || {};
      ctx.save();
      ctx.strokeStyle = opts.color || COLORS.accent;
      ctx.lineWidth = opts.width || 2.5;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      if (opts.dash) ctx.setLineDash(opts.dash);
      ctx.beginPath();
      ctx.moveTo(points[0][0], points[0][1]);
      for (let i = 1; i < points.length; i++)
        ctx.lineTo(points[i][0], points[i][1]);
      if (opts.close) ctx.closePath();
      if (opts.fill) {
        ctx.fillStyle = opts.fill;
        ctx.fill();
      }
      if (opts.color !== "none") ctx.stroke();
      ctx.restore();
    },
    circle(x, y, r, opts) {
      opts = opts || {};
      ctx.save();
      ctx.beginPath();
      ctx.arc(x, y, Math.max(0, r), 0, TAU);
      if (opts.fill) {
        ctx.fillStyle = opts.fill;
        ctx.fill();
      }
      if (opts.stroke) {
        ctx.strokeStyle = opts.stroke;
        ctx.lineWidth = opts.width || 2;
        ctx.stroke();
      }
      ctx.restore();
    },
    rect(x, y, w, h, opts) {
      opts = opts || {};
      ctx.save();
      const r = opts.radius || 0;
      ctx.beginPath();
      if (r > 0) {
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + w, y, x + w, y + h, r);
        ctx.arcTo(x + w, y + h, x, y + h, r);
        ctx.arcTo(x, y + h, x, y, r);
        ctx.arcTo(x, y, x + w, y, r);
      } else {
        ctx.rect(x, y, w, h);
      }
      if (opts.fill) {
        ctx.fillStyle = opts.fill;
        ctx.fill();
      }
      if (opts.stroke) {
        ctx.strokeStyle = opts.stroke;
        ctx.lineWidth = opts.width || 1.5;
        ctx.stroke();
      }
      ctx.restore();
    },
    arrow(x1, y1, x2, y2, opts) {
      opts = opts || {};
      const color = opts.color || COLORS.accent;
      const width = opts.width || 2.5;
      const head = opts.head || 9;
      ctx.save();
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = width;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      const ang = Math.atan2(y2 - y1, x2 - x1);
      ctx.beginPath();
      ctx.moveTo(x2, y2);
      ctx.lineTo(
        x2 - head * Math.cos(ang - 0.4),
        y2 - head * Math.sin(ang - 0.4)
      );
      ctx.lineTo(
        x2 - head * Math.cos(ang + 0.4),
        y2 - head * Math.sin(ang + 0.4)
      );
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    },
    // Map an HSL-ish index to a palette color.
    color(i) {
      return PALETTE[((i % PALETTE.length) + PALETTE.length) % PALETTE.length];
    },
    hsl(h, s, l, a) {
      return `hsla(${h}, ${s}%, ${l}%, ${a == null ? 1 : a})`;
    },

    /* 2D plotting view. Maps data coordinates to pixels with a padded box. */
    plot2d(o) {
      o = o || {};
      const pad = o.pad == null ? 46 : o.pad;
      const box = o.box || {
        x: pad,
        y: pad * 0.6,
        w: logicalW - pad * 2,
        h: logicalH - pad * 1.6,
      };
      const xMin = o.xMin == null ? -10 : o.xMin;
      const xMax = o.xMax == null ? 10 : o.xMax;
      const yMin = o.yMin == null ? -6 : o.yMin;
      const yMax = o.yMax == null ? 6 : o.yMax;
      const X = (v) => box.x + map(v, xMin, xMax, 0, box.w);
      const Y = (v) => box.y + map(v, yMin, yMax, box.h, 0);
      let view = {
        box,
        xMin,
        xMax,
        yMin,
        yMax,
        X,
        Y,
        grid(opts) {
          opts = opts || {};
          const stepX = opts.stepX || niceStep(xMax - xMin);
          const stepY = opts.stepY || niceStep(yMax - yMin);
          ctx.save();
          ctx.strokeStyle = opts.color || COLORS.grid;
          ctx.lineWidth = 1;
          ctx.fillStyle = COLORS.sub;
          ctx.font = "12px system-ui, -apple-system, 'Segoe UI', sans-serif";
          for (let gx = Math.ceil(xMin / stepX) * stepX; gx <= xMax + 1e-9; gx += stepX) {
            ctx.beginPath();
            ctx.moveTo(X(gx), box.y);
            ctx.lineTo(X(gx), box.y + box.h);
            ctx.stroke();
          }
          for (let gy = Math.ceil(yMin / stepY) * stepY; gy <= yMax + 1e-9; gy += stepY) {
            ctx.beginPath();
            ctx.moveTo(box.x, Y(gy));
            ctx.lineTo(box.x + box.w, Y(gy));
            ctx.stroke();
          }
          ctx.restore();
          return view;
        },
        axes(opts) {
          opts = opts || {};
          const x0 = clamp(0, xMin, xMax);
          const y0 = clamp(0, yMin, yMax);
          ctx.save();
          ctx.strokeStyle = opts.color || COLORS.axis;
          ctx.lineWidth = 1.6;
          ctx.beginPath();
          ctx.moveTo(box.x, Y(y0));
          ctx.lineTo(box.x + box.w, Y(y0));
          ctx.moveTo(X(x0), box.y);
          ctx.lineTo(X(x0), box.y + box.h);
          ctx.stroke();
          // Numeric tick labels. Scenes without axis values read as a vague
          // picture instead of a graph, so these are on by default
          // (opts.ticks === false disables them for stylized scenes).
          if (opts.ticks !== false) {
            const stepX = opts.stepX || niceStep(xMax - xMin);
            const stepY = opts.stepY || niceStep(yMax - yMin);
            const fmt = (v) =>
              Math.abs(v) >= 1000 || (Math.abs(v) < 0.01 && v !== 0)
                ? v.toExponential(0)
                : +v.toFixed(2) + "";
            ctx.fillStyle = opts.tickColor || COLORS.sub;
            ctx.font = "11px system-ui, -apple-system, 'Segoe UI', sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            for (let gx = Math.ceil(xMin / stepX) * stepX; gx <= xMax + 1e-9; gx += stepX) {
              if (Math.abs(gx) < stepX * 1e-6) continue; // skip 0 (origin clutter)
              ctx.fillText(fmt(gx), X(gx), Y(y0) + 5);
            }
            ctx.textAlign = "right";
            ctx.textBaseline = "middle";
            for (let gy = Math.ceil(yMin / stepY) * stepY; gy <= yMax + 1e-9; gy += stepY) {
              if (Math.abs(gy) < stepY * 1e-6) continue;
              ctx.fillText(fmt(gy), X(x0) - 6, Y(gy));
            }
          }
          ctx.restore();
          return view;
        },
        fn(f, opts) {
          opts = opts || {};
          const steps = opts.steps || 240;
          const pts = [];
          for (let i = 0; i <= steps; i++) {
            const xv = lerp(xMin, xMax, i / steps);
            let yv;
            try {
              yv = f(xv);
            } catch (e) {
              yv = NaN;
            }
            if (Number.isFinite(yv) && yv >= yMin - 2 && yv <= yMax + 2) {
              pts.push([X(xv), Y(yv)]);
            } else if (pts.length) {
              H.path(pts.splice(0), { color: opts.color || COLORS.accent, width: opts.width || 2.6 });
            }
          }
          if (pts.length)
            H.path(pts, { color: opts.color || COLORS.accent, width: opts.width || 2.6 });
          return view;
        },
        dot(xv, yv, opts) {
          H.circle(X(xv), Y(yv), (opts && opts.r) || 5, {
            fill: (opts && opts.fill) || COLORS.accent2,
            stroke: (opts && opts.stroke) || COLORS.bg,
            width: 2,
          });
          return view;
        },
        /* Data-space drawing. Models naturally write `v.line(x1,y1,x2,y2)`
         * meaning math coordinates — these make that correct instead of a
         * fatal "not a function". */
        line(x1, y1, x2, y2, opts) {
          H.line(X(x1), Y(y1), X(x2), Y(y2), opts);
          return view;
        },
        arrow(x1, y1, x2, y2, opts) {
          H.arrow(X(x1), Y(y1), X(x2), Y(y2), opts);
          return view;
        },
        text(str, xv, yv, opts) {
          H.text(str, X(xv), Y(yv), opts);
          return view;
        },
        circle(xv, yv, r, opts) {
          H.circle(X(xv), Y(yv), r, opts); // r stays in pixels
          return view;
        },
        path(points, opts) {
          if (!points || !points.length) return view;
          H.path(points.map((p) => [X(p[0]), Y(p[1])]), opts);
          return view;
        },
        rect(xv, yv, w, h, opts) {
          // (xv, yv) is the lower-left corner in data coords; w/h in data units.
          H.rect(X(xv), Y(yv + h), X(xv + w) - X(xv), Y(yv) - Y(yv + h), opts);
          return view;
        },
      };
      // Same tolerance as H itself: an invented view method becomes a no-op
      // instead of killing the whole frame with "v.foo is not a function".
      // Reassign the `view` binding to the proxy so every `return view` inside
      // the methods above yields the wrapped object — that keeps invented
      // helpers no-op-able even mid-chain (e.g. view.fn(...).annotate(...)).
      view = wrapHelpers(view);
      return view;
    },

    /* 3D camera. project([x,y,z]) -> {x, y, depth, f}. Larger depth = farther
     * from the camera, so painter's algorithm = sort DESCENDING by depth and
     * draw in order. User drag/zoom (the `orbit` worker global) is layered on
     * top of the scene's own yaw/pitch automatically. Convention: y is UP. */
    cam3d(o) {
      o = o || {};
      let yaw = o.yaw || 0;
      let pitch = o.pitch == null ? -0.5 : o.pitch;
      const scale = o.scale || 60;
      const dist = o.dist || 9;
      const cx = o.cx == null ? logicalW / 2 : o.cx;
      const cy = o.cy == null ? logicalH / 2 : o.cy;
      let cam = {
        set yaw(v) {
          yaw = v;
        },
        get yaw() {
          return yaw;
        },
        set pitch(v) {
          pitch = v;
        },
        get pitch() {
          return pitch;
        },
        project(p) {
          let x = p[0],
            y = p[1],
            z = p[2];
          const ya = yaw + orbit.yaw;
          const pa = clamp(pitch + orbit.pitch, -1.45, 1.45);
          // yaw about Y
          let xz = x * Math.cos(ya) - z * Math.sin(ya);
          let zz = x * Math.sin(ya) + z * Math.cos(ya);
          x = xz;
          z = zz;
          // pitch about X
          let yz = y * Math.cos(pa) - z * Math.sin(pa);
          let zp = y * Math.sin(pa) + z * Math.cos(pa);
          y = yz;
          z = zp;
          const f = (dist / (dist + z)) * orbit.zoom;
          return { x: cx + x * scale * f, y: cy - y * scale * f, depth: z, f };
        },
        /* Straight 3D segment. */
        line(a, b, opts) {
          const p1 = cam.project(a);
          const p2 = cam.project(b);
          H.line(p1.x, p1.y, p2.x, p2.y, opts);
          return cam;
        },
        /* Polyline through 3D points: [[x,y,z], ...]. */
        path(points, opts) {
          if (!points || points.length < 2) return cam;
          const px = [];
          for (let i = 0; i < points.length; i++) {
            const p = cam.project(points[i]);
            px.push([p.x, p.y]);
          }
          H.path(px, opts);
          return cam;
        },
        /* Filled/stroked 3D polygon (caller is responsible for depth order). */
        poly(points, opts) {
          if (!points || points.length < 3) return cam;
          opts = opts || {};
          const px = [];
          for (let i = 0; i < points.length; i++) {
            const p = cam.project(points[i]);
            px.push([p.x, p.y]);
          }
          H.path(px, {
            color: opts.stroke || opts.color || "none",
            width: opts.width || 1,
            fill: opts.fill,
            close: true,
          });
          return cam;
        },
        /* Shaded ball at a 3D point. Radius is in WORLD units (scales with
         * perspective). Works with any CSS base color. Returns the projected
         * point so callers can depth-sort before drawing. */
        sphere(p, r, opts) {
          opts = opts || {};
          const q = cam.project(p);
          const rr = Math.max(0.5, r * scale * q.f);
          const base = opts.color || COLORS.accent;
          ctx.save();
          ctx.beginPath();
          ctx.arc(q.x, q.y, rr, 0, TAU);
          ctx.fillStyle = base;
          ctx.fill();
          // Highlight toward the light, darkened rim away from it. Layered
          // gradients shade any base color without parsing it.
          const hx = q.x - rr * 0.35;
          const hy = q.y - rr * 0.4;
          let g = ctx.createRadialGradient(hx, hy, rr * 0.05, hx, hy, rr * 1.25);
          g.addColorStop(0, "rgba(255,255,255,0.65)");
          g.addColorStop(0.45, "rgba(255,255,255,0.08)");
          g.addColorStop(1, "rgba(8,10,24,0.55)");
          ctx.fillStyle = g;
          ctx.fill();
          if (opts.stroke) {
            ctx.strokeStyle = opts.stroke;
            ctx.lineWidth = opts.width || 1;
            ctx.stroke();
          }
          ctx.restore();
          return q;
        },
        /* Ground-plane grid at y=0 for depth perception. Inputs come from
         * generated code, so both are sanitized: a zero/negative/NaN step or
         * a huge size would otherwise hang the worker. */
        grid(size, step, opts) {
          size = Number.isFinite(size) && size > 0 ? Math.min(size, 1000) : 4;
          step = Number.isFinite(step) && step > 0 ? step : 1;
          if (size / step > 80) step = size / 80; // cap at 161 lines per axis
          opts = opts || {};
          const color = opts.color || COLORS.grid;
          const width = opts.width || 1;
          for (let v = -size; v <= size + 1e-9; v += step) {
            cam.line([v, 0, -size], [v, 0, size], { color, width });
            cam.line([-size, 0, v], [size, 0, v], { color, width });
          }
          return cam;
        },
        axes(len, opts) {
          len = Number.isFinite(len) && len > 0 ? Math.min(len, 1000) : 3;
          opts = opts || {};
          const o0 = cam.project([0, 0, 0]);
          const ax = [
            [[len, 0, 0], COLORS.accent, "x"],
            [[0, len, 0], COLORS.good, "y"],
            [[0, 0, len], COLORS.accent2, "z"],
          ];
          ax.forEach(([v, c, label]) => {
            const p = cam.project(v);
            H.arrow(o0.x, o0.y, p.x, p.y, { color: c, width: 2 });
            H.text(label, p.x + 4, p.y - 4, { color: c, size: 13 });
          });
          // Unit tick marks + numbers so 3D scenes have a readable scale.
          // Skipped for long axes (labels would smear together).
          if (opts.ticks !== false && len <= 12) {
            const step = len > 6 ? 2 : 1;
            for (let v = step; v <= len - step * 0.5; v += step) {
              ax.forEach(([dir, c]) => {
                const u = [
                  (dir[0] / len) * v,
                  (dir[1] / len) * v,
                  (dir[2] / len) * v,
                ];
                const p = cam.project(u);
                H.circle(p.x, p.y, 1.6, { fill: c });
                H.text(String(v), p.x + 3, p.y - 3, {
                  color: COLORS.sub,
                  size: 10,
                });
              });
            }
          }
          return cam;
        },
      };
      // Invented cam methods degrade to no-ops, like H and plot2d views.
      // Reassign the `cam` binding to the proxy so every `return cam` inside the
      // methods above yields the wrapped object — chains keep working in any
      // order (e.g. cam.grid().glow(), cam.line(...).spiral(...)).
      cam = wrapHelpers(cam);
      return cam;
    },

    /* Solid, lit, depth-sorted height surface: screenHeight = f(x, y).
     * THE way to draw z = f(x, y) surfaces. `f` receives the two ground-plane
     * coordinates and returns the height drawn along the screen-up axis. */
    surface3d(cam, f, opts) {
      opts = opts || {};
      const xMin = opts.xMin == null ? -3 : opts.xMin;
      const xMax = opts.xMax == null ? 3 : opts.xMax;
      const yMin = opts.yMin == null ? -3 : opts.yMin;
      const yMax = opts.yMax == null ? 3 : opts.yMax;
      const nx = clamp(Math.round(opts.nx || 36), 4, 64);
      const ny = clamp(Math.round(opts.ny || 36), 4, 64);
      // Sample the grid once; reuse corner samples between quads.
      const pts = [];
      let hMin = Infinity;
      let hMax = -Infinity;
      for (let j = 0; j <= ny; j++) {
        const row = [];
        for (let i = 0; i <= nx; i++) {
          const x = map(i, 0, nx, xMin, xMax);
          const y = map(j, 0, ny, yMin, yMax);
          let h;
          try {
            h = f(x, y);
          } catch (e) {
            h = NaN;
          }
          if (Number.isFinite(h)) {
            if (h < hMin) hMin = h;
            if (h > hMax) hMax = h;
            row.push([x, h, y]);
          } else {
            row.push(null);
          }
        }
        pts.push(row);
      }
      if (hMin > hMax) return; // nothing finite to draw
      const quads = [];
      for (let j = 0; j < ny; j++) {
        for (let i = 0; i < nx; i++) {
          const a = pts[j][i];
          const b = pts[j][i + 1];
          const c = pts[j + 1][i + 1];
          const d = pts[j + 1][i];
          if (!a || !b || !c || !d) continue;
          const value =
            hMax > hMin
              ? ((a[1] + b[1] + c[1] + d[1]) / 4 - hMin) / (hMax - hMin)
              : 0.5;
          quads.push({ pts: [a, b, c, d], value });
        }
      }
      drawShadedQuads(cam, quads, opts);
    },

    /* Solid, lit, depth-sorted parametric surface: fn(u, v) -> [x, y, z].
     * Spheres, tori, cylinders, tubes, ribbons, Möbius strips, orbitals... */
    mesh3d(cam, fn, opts) {
      opts = opts || {};
      const uMin = opts.uMin == null ? 0 : opts.uMin;
      const uMax = opts.uMax == null ? TAU : opts.uMax;
      const vMin = opts.vMin == null ? 0 : opts.vMin;
      const vMax = opts.vMax == null ? TAU : opts.vMax;
      const nu = clamp(Math.round(opts.nu || 32), 3, 64);
      const nv = clamp(Math.round(opts.nv || 18), 3, 64);
      const pts = [];
      let hMin = Infinity;
      let hMax = -Infinity;
      for (let j = 0; j <= nv; j++) {
        const row = [];
        for (let i = 0; i <= nu; i++) {
          const u = map(i, 0, nu, uMin, uMax);
          const v = map(j, 0, nv, vMin, vMax);
          let p;
          try {
            p = fn(u, v);
          } catch (e) {
            p = null;
          }
          if (
            p &&
            Number.isFinite(p[0]) &&
            Number.isFinite(p[1]) &&
            Number.isFinite(p[2])
          ) {
            if (p[1] < hMin) hMin = p[1];
            if (p[1] > hMax) hMax = p[1];
            row.push(p);
          } else {
            row.push(null);
          }
        }
        pts.push(row);
      }
      if (hMin > hMax) return;
      const quads = [];
      for (let j = 0; j < nv; j++) {
        for (let i = 0; i < nu; i++) {
          const a = pts[j][i];
          const b = pts[j][i + 1];
          const c = pts[j + 1][i + 1];
          const d = pts[j + 1][i];
          if (!a || !b || !c || !d) continue;
          const value =
            hMax > hMin
              ? ((a[1] + b[1] + c[1] + d[1]) / 4 - hMin) / (hMax - hMin)
              : 0.5;
          quads.push({ pts: [a, b, c, d], value });
        }
      }
      drawShadedQuads(cam, quads, opts);
    },

    // Convenience: draw a soft legend chip.
    legend(items, x, y) {
      ctx.save();
      let cy = y;
      items.forEach((it) => {
        H.circle(x + 6, cy - 4, 5, { fill: it.color });
        H.text(it.label, x + 18, cy, { size: 13, color: COLORS.sub });
        cy += 20;
      });
      ctx.restore();
    },
  };
  return H;
}

/* Shared core of surface3d / mesh3d: project quads, Lambert-shade them from a
 * fixed light, sort far-to-near, and fill. Color options:
 *   hue          — fixed hue (parametric meshes default to 210)
 *   hueMin/hueMax — height-mapped hue ramp (surfaces default to 215 → 25)
 *   colorFn(value, lambert) — full custom CSS color escape hatch
 *   alpha, wire (stroke the quad edges, default true), shade (default true)
 */
const LIGHT_DIR = (() => {
  const v = [0.45, 0.85, 0.35];
  const n = Math.hypot(v[0], v[1], v[2]);
  return [v[0] / n, v[1] / n, v[2] / n];
})();

function drawShadedQuads(cam, quads, opts) {
  opts = opts || {};
  const alpha = opts.alpha == null ? 0.96 : clamp(opts.alpha, 0.05, 1);
  const wire = opts.wire !== false;
  const shade = opts.shade !== false;
  const hueFixed = opts.hue;
  const hueMin = opts.hueMin == null ? 215 : opts.hueMin;
  const hueMax = opts.hueMax == null ? 25 : opts.hueMax;
  const polys = [];
  for (let k = 0; k < quads.length; k++) {
    const q = quads[k];
    const [a, b, c, d] = q.pts;
    // Normal from the diagonals — stable even for non-planar quads.
    const u = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    const v = [d[0] - b[0], d[1] - b[1], d[2] - b[2]];
    let nx = u[1] * v[2] - u[2] * v[1];
    let ny = u[2] * v[0] - u[0] * v[2];
    let nz = u[0] * v[1] - u[1] * v[0];
    const nl = Math.hypot(nx, ny, nz) || 1;
    nx /= nl;
    ny /= nl;
    nz /= nl;
    // abs(): quad winding is arbitrary, light both faces.
    const lambert = Math.abs(
      nx * LIGHT_DIR[0] + ny * LIGHT_DIR[1] + nz * LIGHT_DIR[2]
    );
    const pr = [
      cam.project(a),
      cam.project(b),
      cam.project(c),
      cam.project(d),
    ];
    polys.push({
      pr,
      depth: (pr[0].depth + pr[1].depth + pr[2].depth + pr[3].depth) / 4,
      lambert: shade ? 0.25 + 0.75 * lambert : 1,
      value: q.value,
    });
  }
  // Painter's algorithm: larger depth = farther; draw far first.
  polys.sort((p1, p2) => p2.depth - p1.depth);
  ctx.save();
  ctx.lineJoin = "round";
  for (let k = 0; k < polys.length; k++) {
    const p = polys[k];
    let fill;
    if (typeof opts.colorFn === "function") {
      try {
        fill = opts.colorFn(p.value, p.lambert);
      } catch (e) {
        fill = null;
      }
    }
    if (!fill) {
      const hue =
        hueFixed == null ? lerp(hueMin, hueMax, p.value) : hueFixed;
      const lightness = clamp(18 + 44 * p.lambert, 8, 78);
      fill = `hsla(${hue}, 72%, ${lightness}%, ${alpha})`;
    }
    ctx.beginPath();
    ctx.moveTo(p.pr[0].x, p.pr[0].y);
    ctx.lineTo(p.pr[1].x, p.pr[1].y);
    ctx.lineTo(p.pr[2].x, p.pr[2].y);
    ctx.lineTo(p.pr[3].x, p.pr[3].y);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();
    if (wire) {
      ctx.strokeStyle = COLORS.quadEdge;
      ctx.lineWidth = 0.7;
      ctx.stroke();
    }
  }
  ctx.restore();
}

function niceStep(range) {
  const raw = range / 8;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  let step;
  if (norm < 1.5) step = 1;
  else if (norm < 3) step = 2;
  else if (norm < 7) step = 5;
  else step = 10;
  return step * mag;
}

let HELP = null;

/* Safety net for a common model mistake: referencing `cam` / `view` / `v`
 * without creating them first (previously a fatal ReferenceError that burned
 * the whole repair budget). These globals provide sane defaults; code that
 * properly declares `const cam = H.cam3d({...})` shadows them cleanly, same
 * as the `H` global. */
function seedConvenienceGlobals() {
  if (!HELP) return;
  self.cam = HELP.cam3d({});
  self.view = HELP.plot2d({});
  self.v = self.view;
}

/* Wrap the helper object in a Proxy that returns a harmless no-op for any
 * helper the model invents but we don't ship. Without this, a single
 * `H.spinner()`-style typo blanks the whole frame; with it, the rest of the
 * scene still renders and the model just doesn't get that specific helper. */
function wrapHelpers(h) {
  if (typeof Proxy === "undefined") return h;
  const proxy = new Proxy(h, {
    get(target, key) {
      // Real helpers and any symbol access (Symbol.toPrimitive, iterators, …)
      // pass straight through — intercepting symbols would break coercion.
      if (key in target || typeof key === "symbol") return target[key];
      // An invented helper (`H.spinner()`, `cam.spiral()`, `view.heatmap()`).
      // Return a no-op that RETURNS THE HOST so chains keep flowing:
      // `cam.invented(...).line(...)` used to throw "Cannot read properties of
      // undefined (reading 'line')" and burn the whole repair budget. Now the
      // invented call does nothing and `.line(...)` resolves on the real host.
      // A bare `H.invented(...)` still just no-ops.
      return function chainableNoop() {
        return proxy;
      };
    },
  });
  return proxy;
}

/* ------------------------------------------------------------------ */
/* Frame loop                                                          */
/* ------------------------------------------------------------------ */

function compile(code) {
  // Important shadowing fix: we used to pass `H` as a function parameter,
  // which made `const H = H.H` in the generated code throw a SyntaxError
  // ("Identifier 'H' has already been declared") and the whole scene died.
  //
  // Solution: expose H as a *worker global* instead. Generated code that
  // references bare `H` still resolves it through the global scope chain,
  // BUT a `const H = ...` declaration in the function body now shadows the
  // global cleanly — no syntax error, and the local `H` overrides for the
  // rest of that block, which is what the model intended anyway.
  //
  // ctx is kept as a parameter (we never see the model redeclare it).
  self.H = HELP;
  self.P = curParams; // demo parameters; a scene reads P.<name>, updated live
  /* eslint-disable no-new-func */
  const factory = new Function(
    "ctx",
    "t",
    '"use strict";\n' + code + "\n"
  );
  return factory;
}

// A scene that throws every frame from t=0 is broken and must go to repair.
// One that renders cleanly then throws on a single frame (a NaN at one value of
// `t`, a transient out-of-range index) should NOT — killing it wastes a full
// repair round-trip on a scene that's 99% working. We escalate only when the
// scene never produced a clean frame, or has thrown continuously for ~half a
// second (state is corrupted, not a one-frame blip).
const MAX_CONSECUTIVE_ERRORS = 30; // ~0.5s at 60fps

// Best-effort: pull the offending source line out of a V8 `new Function` stack
// frame (`<anonymous>:LINE:COL`). The compiled wrapper adds 3 lines ahead of the
// user's code (the `function(ctx,t)` header, the `) {` line, and the injected
// `"use strict";`), so user line = anonLine - 3. Non-V8 engines format stacks
// differently, miss the regex, and yield "" — the repair model then falls back
// to the message + code alone. Handing the model the exact failing line cuts
// repair rounds, especially for terse errors like "Cannot read properties of
// undefined" that don't say *which* access broke.
function offendingLine(stack, code) {
  try {
    if (!stack || !code) return "";
    const m = /<anonymous>:(\d+):\d+/.exec(stack);
    if (!m) return "";
    const lineNo = parseInt(m[1], 10) - 3; // 1-based line within `code`
    const lines = code.split("\n");
    if (lineNo < 1 || lineNo > lines.length) return "";
    const text = String(lines[lineNo - 1]).trim();
    return text ? "line " + lineNo + ": " + text : "";
  } catch (e) {
    return "";
  }
}

function tick() {
  if (!running) return;
  const now = performance.now();
  if (!paused) {
    const dt = Math.min(0.05, (now - lastWall) / 1000); // clamp big gaps
    simTime += dt * speed;
  }
  lastWall = now;

  let renderedThisTick = false;
  if (sceneFn && (!paused || needsRender)) {
    try {
      ctx.clearRect(0, 0, logicalW, logicalH);
      sceneFn(ctx, simTime);  // H is a global (see compile())
      everRendered = true;
      renderedThisTick = true;
      needsRender = false;
      consecutiveErrors = 0;
    } catch (err) {
      consecutiveErrors++;
      if (!everRendered || consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
        running = false;
        post({
          type: "runtime-error",
          message: String((err && err.message) || err),
          stack: String((err && err.stack) || ""),
          where: offendingLine(err && err.stack, lastCode),
        });
        return;
      }
      // Transient bad frame: skip drawing it, keep the loop alive.
    }
  }

  if (renderedThisTick) frameCount++;
  // Heartbeat on the first clean frame (so the main thread's run() promise
  // resolves ~immediately rather than after ~20 frames), then every 20 frames.
  if (everRendered && (frameCount === 1 || frameCount % 20 === 0)) {
    post({ type: "heartbeat", frame: frameCount, t: simTime });
  }

  // Suspended (tab hidden): stop the loop entirely instead of redrawing into a
  // canvas nobody can see. The "visible" message restarts it.
  if (suspended) {
    loopTimer = null;
    return;
  }
  // Self-correcting schedule: aim for a fixed ~16.7ms PERIOD, not 16.7ms AFTER
  // the work. Without this, a scene that takes 10ms to draw runs at ~37fps
  // (10 + 16.7) instead of 60. Subtract the time this frame already spent.
  const work = performance.now() - now;
  loopTimer = setTimeout(tick, paused ? 250 : Math.max(0, FRAME_MS - work));
}

/* ------------------------------------------------------------------ */
/* Message handling                                                    */
/* ------------------------------------------------------------------ */

self.onmessage = (e) => {
  const m = e.data || {};
  switch (m.type) {
    case "init": {
      canvas = m.canvas;
      dpr = m.dpr || 1;
      logicalW = m.width;
      logicalH = m.height;
      canvas.width = Math.round(logicalW * dpr);
      canvas.height = Math.round(logicalH * dpr);
      ctx = canvas.getContext("2d");
      ctx.scale(dpr, dpr);
      applyTheme(m.theme || THEME_NAME);
      HELP = wrapHelpers(makeHelpers());
      seedConvenienceGlobals();
      post({ type: "ready" });
      break;
    }
    case "resize": {
      if (!canvas) return;
      logicalW = m.width;
      logicalH = m.height;
      // Honor the new DPR when the user drags the window across displays —
      // otherwise text/strokes go blurry on a switch into Retina (or aliased
      // when going back).
      if (typeof m.dpr === "number" && m.dpr > 0) dpr = m.dpr;
      canvas.width = Math.round(logicalW * dpr);
      canvas.height = Math.round(logicalH * dpr);
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.scale(dpr, dpr);
      seedConvenienceGlobals(); // defaults capture canvas center/box at creation
      needsRender = true;
      break;
    }
    case "run": {
      try {
        curParams = m.params && typeof m.params === "object" ? m.params : {};
        if (m.theme) applyTheme(m.theme);
        const fn = compile(m.code);
        sceneFn = fn;
        lastCode = typeof m.code === "string" ? m.code : "";
        if (m.resetTime !== false) {
          simTime = 0;
          orbit.yaw = 0;
          orbit.pitch = 0;
          orbit.zoom = 1;
        }
        frameCount = 0;
        consecutiveErrors = 0;
        everRendered = false;
        needsRender = true;
        paused = false;
        lastWall = performance.now();
        if (!running) {
          running = true;
          tick();
        }
        post({ type: "running" });
      } catch (err) {
        post({
          type: "compile-error",
          message: String((err && err.message) || err),
        });
      }
      break;
    }
    case "pause":
      paused = true;
      break;
    case "resume":
      paused = false;
      needsRender = true;
      lastWall = performance.now();
      break;
    case "speed":
      speed = m.value;
      break;
    case "visible":
      // Tab visibility from the main thread. Hidden -> stop the loop (don't
      // redraw an invisible canvas). Visible -> restart, resetting the wall
      // clock so the paused gap doesn't jump simTime forward.
      suspended = !m.value;
      if (!suspended && running && !loopTimer) {
        lastWall = performance.now();
        tick();
      }
      break;
    case "params":
      // Live demo-parameter update from the UI sliders. Mutate in place so the
      // running scene (which reads the `P` global each frame) sees new values
      // immediately — no recompile, no flicker.
      if (m.values && typeof m.values === "object") {
        for (const k in m.values) curParams[k] = m.values[k];
        needsRender = true;
      }
      break;
    case "orbit":
      // Camera drag/zoom from the main thread. Applied inside cam3d.project,
      // so it affects every 3D scene without the generated code's cooperation.
      orbit.yaw += m.dyaw || 0;
      orbit.pitch = clamp(orbit.pitch + (m.dpitch || 0), -1.45, 1.45);
      if (m.dzoom) orbit.zoom = clamp(orbit.zoom * m.dzoom, 0.35, 4);
      needsRender = true;
      break;
    case "orbit-reset":
      orbit.yaw = 0;
      orbit.pitch = 0;
      orbit.zoom = 1;
      needsRender = true;
      break;
    case "theme":
      // Live theme switch from the main thread. Mutates COLORS/PALETTE in place
      // so the running scene redraws in the new palette next frame — no recompile.
      if (m.theme) {
        applyTheme(m.theme);
        needsRender = true;
      }
      break;
    case "stop":
      running = false;
      if (loopTimer) clearTimeout(loopTimer);
      break;
    default:
      break;
  }
};
