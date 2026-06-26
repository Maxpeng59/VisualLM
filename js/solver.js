/* VisualLM — step-by-step worked-solution engine (browser port of solver.py).
 *
 * A SPECIFIC problem (real numbers + labels) -> an animated slide deck that
 * walks through solving it with the student's own numbers. First solver:
 * triangles (SAS / SSS / ASA / AAS / SSA incl. the ambiguous case).
 *
 * Exposes VisualLMSolver.scene(prompt) -> scene-content object | null,
 * matching the Python solver_scene() shape. Verified-parity with solver.py.
 */
(function (global) {
  "use strict";

  const ANGLE_RE = /\bangle\s+(?:of\s+)?([abcABC])\s*=\s*(-?\d+(?:\.\d+)?)/gi;
  const SIDE_RE = /(?:side\s+)?\b([abcABC])\s*=\s*(-?\d+(?:\.\d+)?)/g;

  function parseTriangle(prompt) {
    if (!prompt) return null;
    const text = String(prompt).trim();
    const given = {};
    const order = [];
    const consumed = [];
    let m;
    ANGLE_RE.lastIndex = 0;
    while ((m = ANGLE_RE.exec(text)) !== null) {
      const k = m[1].toUpperCase();
      if (!(k in given)) { given[k] = parseFloat(m[2]); order.push(k); }
      consumed.push([m.index, m.index + m[0].length]);
    }
    SIDE_RE.lastIndex = 0;
    while ((m = SIDE_RE.exec(text)) !== null) {
      const start = m.index;
      if (consumed.some(([s, e]) => s <= start && start < e)) continue;
      const raw = m[1];
      const val = parseFloat(m[2]);
      const k = raw === raw.toUpperCase() ? raw : raw.toLowerCase();
      if (!(k in given)) { given[k] = val; order.push(k); }
    }
    given.__order = order;
    const keys = order;
    const sides = keys.filter((k) => k === "a" || k === "b" || k === "c");
    if (keys.length < 3 || !sides.length) return null;
    for (const k of keys) {
      const v = given[k];
      if ((k === "a" || k === "b" || k === "c") && v <= 0) return null;
      if ((k === "A" || k === "B" || k === "C") && !(v > 0 && v < 180)) return null;
    }
    const angsum = keys.filter((k) => k === "A" || k === "B" || k === "C").reduce((s, k) => s + given[k], 0);
    if (angsum >= 180) return null;
    return given;
  }

  const rad = (d) => (d * Math.PI) / 180;
  const deg = (r) => (r * 180) / Math.PI;
  const g = (x) => String(x);           // mirrors Python :g for clean inputs
  const f1 = (x) => x.toFixed(1);
  const f2 = (x) => x.toFixed(2);
  const f3 = (x) => x.toFixed(3);
  const clamp1 = (x) => Math.max(-1, Math.min(1, x));

  function classify(given) {
    const keys = given.__order;
    const sides = keys.filter((k) => "abc".includes(k)).sort();
    const angles = keys.filter((k) => "ABC".includes(k)).sort();
    const ns = sides.length, na = angles.length;
    if (ns === 3) return "SSS";
    if (ns === 2 && na === 1) {
      const inc = { "a,b": "C", "a,c": "B", "b,c": "C", "b,c2": "A" };
      const incMap = {};
      incMap[["a", "b"].join(",")] = "C";
      incMap[["a", "c"].join(",")] = "B";
      incMap[["b", "c"].join(",")] = "A";
      return angles[0] === incMap[sides.join(",")] ? "SAS" : "SSA";
    }
    if (ns === 1 && na === 2) return "ASA_AAS";
    return null;
  }

  function solFrom(a, b, c, A, B, C) { return { a, b, c, A, B, C }; }

  function solveTriangle(given) {
    const cse = classify(given);
    if (!cse) return null;
    const G = given;
    const opp = { a: "A", b: "B", c: "C" };

    if (cse === "SSS") {
      const a = G.a, b = G.b, c = G.c;
      if (a + b <= c || a + c <= b || b + c <= a) return null;
      const A = deg(Math.acos(clamp1((b * b + c * c - a * a) / (2 * b * c))));
      const B = deg(Math.acos(clamp1((a * a + c * c - b * b) / (2 * a * c))));
      const C = 180 - A - B;
      const steps = [
        { title: "What's given", formula: `a = ${g(a)},  b = ${g(b)},  c = ${g(c)}`, detail: "Three sides (SSS). To find an angle, use the Law of Cosines." },
        { title: "Find angle A (Law of Cosines)", formula: "cos A = (b² + c² − a²) / (2bc)", detail: `cos A = (${g(b)}² + ${g(c)}² − ${g(a)}²) / (2·${g(b)}·${g(c)})  →  A = ${f1(A)}°` },
        { title: "Find angle B (Law of Cosines)", formula: "cos B = (a² + c² − b²) / (2ac)", detail: `B = ${f1(B)}°` },
        { title: "Find angle C", formula: "C = 180° − A − B", detail: `C = 180° − ${f1(A)}° − ${f1(B)}° = ${f1(C)}°` },
      ];
      return { case: cse, solutions: [solFrom(a, b, c, A, B, C)], steps };
    }

    if (cse === "SAS") {
      const sides = given.__order.filter((k) => "abc".includes(k)).sort();
      const angK = given.__order.filter((k) => "ABC".includes(k))[0];
      const [s1, s2] = sides;
      const thirdS = ["a", "b", "c"].find((s) => s !== s1 && s !== s2);
      const x1 = G[s1], x2 = G[s2], ang = G[angK];
      const third = Math.sqrt(x1 * x1 + x2 * x2 - 2 * x1 * x2 * Math.cos(rad(ang)));
      const full = {}; full[s1] = x1; full[s2] = x2; full[thirdS] = third;
      const a = full.a, b = full.b, c = full.c;
      const A = deg(Math.acos(clamp1((b * b + c * c - a * a) / (2 * b * c))));
      const B = deg(Math.acos(clamp1((a * a + c * c - b * b) / (2 * a * c))));
      const C = 180 - A - B;
      const steps = [
        { title: "What's given", formula: `${s1} = ${g(x1)},  ${s2} = ${g(x2)},  ∠${angK} = ${g(ang)}°`, detail: "Two sides and the angle BETWEEN them (SAS). Start with the Law of Cosines." },
        { title: `Find side ${thirdS} (Law of Cosines)`, formula: `${thirdS}² = ${s1}² + ${s2}² − 2·${s1}·${s2}·cos ${angK}`, detail: `${thirdS} = √(${g(x1)}² + ${g(x2)}² − 2·${g(x1)}·${g(x2)}·cos ${g(ang)}°) = ${f2(third)}` },
        { title: "Find the remaining angles", formula: "Law of Cosines (or Sines)", detail: `A = ${f1(A)}°,  B = ${f1(B)}°,  C = ${f1(C)}°` },
        { title: "Solved", formula: "A + B + C = 180°", detail: `a=${f2(a)}, b=${f2(b)}, c=${f2(c)}; A=${f1(A)}°, B=${f1(B)}°, C=${f1(C)}°` },
      ];
      return { case: cse, solutions: [solFrom(a, b, c, A, B, C)], steps };
    }

    if (cse === "ASA_AAS") {
      const angles = given.__order.filter((k) => "ABC".includes(k));
      const sideK = given.__order.filter((k) => "abc".includes(k))[0];
      const thirdA = ["A", "B", "C"].find((k) => !angles.includes(k));
      const known = {}; angles.forEach((k) => (known[k] = G[k]));
      known[thirdA] = 180 - angles.reduce((s, k) => s + known[k], 0);
      const A_ = known.A, B_ = known.B, C_ = known.C;
      const sval = G[sideK];
      const ratio = sval / Math.sin(rad(known[opp[sideK]]));
      const sides = {}; ["a", "b", "c"].forEach((sk) => (sides[sk] = ratio * Math.sin(rad(known[opp[sk]]))));
      const a = sides.a, b = sides.b, c = sides.c;
      const steps = [
        { title: "What's given", formula: angles.map((k) => `∠${k}=${g(G[k])}°`).join("  ") + `,  ${sideK}=${g(sval)}`, detail: "Two angles and a side (ASA/AAS). The angles fix the shape." },
        { title: `Find ∠${thirdA}`, formula: "A + B + C = 180°", detail: `∠${thirdA} = 180° − ` + angles.map((k) => `${g(G[k])}°`).join(" − ") + ` = ${f1(known[thirdA])}°` },
        { title: "Find the sides (Law of Sines)", formula: "a/sin A = b/sin B = c/sin C", detail: `common ratio = ${sideK}/sin ${opp[sideK]} = ${f2(ratio)}` },
        { title: "Solved", formula: "every side from the ratio", detail: `a=${f2(a)}, b=${f2(b)}, c=${f2(c)}; A=${f1(A_)}°, B=${f1(B_)}°, C=${f1(C_)}°` },
      ];
      return { case: cse, solutions: [solFrom(a, b, c, A_, B_, C_)], steps };
    }

    if (cse === "SSA") {
      const angK = given.__order.filter((k) => "ABC".includes(k))[0];
      const ang = G[angK];
      const os = { A: "a", B: "b", C: "c" }[angK];
      const other = ["a", "b", "c"].filter((s) => s in G && s !== os);
      if (!(os in G) || !other.length) return null;
      const sideOpp = G[os], otherK = other[0], sideOther = G[otherK];
      const otherAngK = opp[otherK];
      const sinX = (sideOther * Math.sin(rad(ang))) / sideOpp;
      const steps = [
        { title: "What's given", formula: `${os} = ${g(sideOpp)},  ${otherK} = ${g(sideOther)},  ∠${angK} = ${g(ang)}°`, detail: "Two sides and an angle NOT between them (SSA) — the ambiguous case. Use the Law of Sines." },
        { title: "Set up the Law of Sines", formula: `sin ${otherAngK} / ${otherK} = sin ${angK} / ${os}`, detail: `sin ${otherAngK} = ${otherK}·sin ${angK} / ${os} = ${g(sideOther)}·sin ${g(ang)}° / ${g(sideOpp)} = ${f3(sinX)}` },
      ];
      if (sinX > 1 + 1e-9) {
        steps.push({ title: "No triangle", formula: "sin value > 1", detail: `sin ${otherAngK} = ${f3(sinX)} > 1 is impossible — NO triangle exists.` });
        return { case: cse, solutions: [], steps, ambiguous: true };
      }
      const sx = clamp1(sinX);
      const X1 = deg(Math.asin(sx));
      const sols = [];
      for (const X of [X1, 180 - X1]) {
        if (X <= 0 || ang + X >= 180) continue;
        const known = {}; known[angK] = ang; known[otherAngK] = X;
        const thirdA = ["A", "B", "C"].find((k) => !(k in known));
        known[thirdA] = 180 - ang - X;
        const ratio = sideOpp / Math.sin(rad(ang));
        const sd = {}; ["a", "b", "c"].forEach((sk) => (sd[sk] = ratio * Math.sin(rad(known[opp[sk]]))));
        sols.push(solFrom(sd.a, sd.b, sd.c, known.A, known.B, known.C));
      }
      if (sols.length === 2) {
        steps.push({ title: `Two possible angles for ∠${otherAngK}`, formula: `${otherAngK} = ${f1(X1)}°  OR  180° − ${f1(X1)}° = ${f1(180 - X1)}°`, detail: "Both keep the angle sum under 180°, so TWO triangles fit the data." });
        const [s1, s2] = sols;
        steps.push({ title: "Triangle 1", formula: `∠${otherAngK} = ${f1(X1)}°`, detail: `A=${f1(s1.A)}°, B=${f1(s1.B)}°, C=${f1(s1.C)}°; a=${f2(s1.a)}, b=${f2(s1.b)}, c=${f2(s1.c)}` });
        steps.push({ title: "Triangle 2 (the other solution)", formula: `∠${otherAngK} = ${f1(180 - X1)}°`, detail: `A=${f1(s2.A)}°, B=${f1(s2.B)}°, C=${f1(s2.C)}°; a=${f2(s2.a)}, b=${f2(s2.b)}, c=${f2(s2.c)}` });
      } else if (sols.length === 1) {
        const s1 = sols[0];
        steps.push({ title: `∠${otherAngK} = ${f1(X1)}°`, formula: "the obtuse option fails (angle sum ≥ 180°)", detail: "Only ONE triangle fits." });
        steps.push({ title: "Solved", formula: "A + B + C = 180°", detail: `A=${f1(s1.A)}°, B=${f1(s1.B)}°, C=${f1(s1.C)}°; a=${f2(s1.a)}, b=${f2(s1.b)}, c=${f2(s1.c)}` });
      }
      return { case: cse, solutions: sols, steps, ambiguous: sols.length === 2 };
    }
    return null;
  }

  function triangleVertices(sol) {
    const a = sol.a, b = sol.b, c = sol.c;
    if (Math.min(a, b, c) <= 0) return null;
    const x = c > 1e-9 ? (b * b - a * a + c * c) / (2 * c) : 0;
    const y2 = b * b - x * x;
    const y = y2 > 0 ? Math.sqrt(y2) : 0;
    return [[0, 0], [c, 0], [x, y]];
  }

  function solverCode(result) {
    const sols = result.solutions || [];
    const verts = sols.length ? triangleVertices(sols[0]) : null;
    const data = JSON.stringify({
      steps: result.steps, verts, labels: sols.length ? sols[0] : null,
      nslides: result.steps.length, ambiguous: !!result.ambiguous,
    });
    return (
      "H.background();\n" +
      "const D = " + data + ";\n" +
      "const w = H.W, hgt = H.H;\n" +
      "const N = D.nslides;\n" +
      "const SLIDE = 3.4;\n" +
      "const k = Math.floor((t / SLIDE) % N);\n" +
      "const st = D.steps[k];\n" +
      "H.text('Step-by-step solution', 24, 30, { color: H.colors.ink, size: 18, weight: 700 });\n" +
      "H.text('Slide ' + (k + 1) + ' of ' + N + '  ·  worked through with your numbers', 24, 52, { color: H.colors.sub, size: 13 });\n" +
      "for (let i = 0; i < N; i++) {\n" +
      "  H.circle(24 + i * 16, 70, 5, { fill: i === k ? H.colors.accent : (i < k ? H.colors.good : H.colors.grid) });\n" +
      "}\n" +
      "if (D.verts) {\n" +
      "  const vs = D.verts;\n" +
      "  let minx = 1e9, maxx = -1e9, miny = 1e9, maxy = -1e9;\n" +
      "  for (const p of vs) { minx = Math.min(minx, p[0]); maxx = Math.max(maxx, p[0]); miny = Math.min(miny, p[1]); maxy = Math.max(maxy, p[1]); }\n" +
      "  const tw = maxx - minx || 1, th = maxy - miny || 1;\n" +
      "  const boxX = w * 0.60, boxY = hgt * 0.30, boxW = w * 0.34, boxH = hgt * 0.42;\n" +
      "  const sc = Math.min(boxW / tw, boxH / th) * 0.82;\n" +
      "  const ox = boxX + boxW / 2 - (minx + tw / 2) * sc;\n" +
      "  const oy = boxY + boxH / 2 + (miny + th / 2) * sc;\n" +
      "  const PX = vs.map(p => [ox + p[0] * sc, oy - p[1] * sc]);\n" +
      "  H.path(PX, { color: H.colors.accent, width: 3, close: true });\n" +
      "  const names = ['A', 'B', 'C'];\n" +
      "  for (let i = 0; i < 3; i++) {\n" +
      "    H.circle(PX[i][0], PX[i][1], 4, { fill: H.colors.ink });\n" +
      "    const av = D.labels[names[i]];\n" +
      "    H.text(names[i] + (av != null ? ' = ' + av.toFixed(0) + '\\u00B0' : ''), PX[i][0] + 8, PX[i][1] - 8, { color: H.colors.sub, size: 12, weight: 700 });\n" +
      "  }\n" +
      "  const edges = [[1, 2, 'a'], [0, 2, 'b'], [0, 1, 'c']];\n" +
      "  for (const e of edges) {\n" +
      "    const mx = (PX[e[0]][0] + PX[e[1]][0]) / 2, my = (PX[e[0]][1] + PX[e[1]][1]) / 2;\n" +
      "    const sv = D.labels[e[2]];\n" +
      "    H.text(e[2] + (sv != null ? '=' + sv.toFixed(1) : ''), mx, my, { color: H.colors.accent2, size: 12, align: 'center', baseline: 'middle' });\n" +
      "  }\n" +
      "}\n" +
      "const cx = 24, cy = hgt * 0.34, cw = w * 0.50;\n" +
      "H.rect(cx, cy, cw, 132, { fill: 'rgba(124,196,255,0.07)', stroke: H.colors.accent, width: 1.4, radius: 12 });\n" +
      "H.text(st.title, cx + 16, cy + 28, { color: H.colors.accent, size: 16, weight: 700, maxWidth: cw - 32 });\n" +
      "H.text(st.formula, cx + 16, cy + 60, { color: H.colors.ink, size: 15, weight: 700, maxWidth: cw - 32 });\n" +
      "H.text(st.detail, cx + 16, cy + 92, { color: H.colors.sub, size: 13, maxWidth: cw - 32 });\n" +
      "if (D.ambiguous) H.text('\\u26A0 Ambiguous (SSA): two triangles satisfy the given data.', cx, cy + 156, { color: H.colors.warn, size: 13, weight: 700 });\n"
    );
  }

  function triangleScene(prompt) {
    const given = parseTriangle(prompt);
    if (!given) return null;
    const result = solveTriangle(given);
    if (!result) return null;
    const nsol = (result.solutions || []).length;
    const caseName = {
      SSS: "three sides (SSS)", SAS: "two sides + included angle (SAS)",
      ASA_AAS: "two angles + a side (ASA/AAS)", SSA: "two sides + a non-included angle (SSA)",
    }[result.case];
    let summary;
    if (nsol === 0) summary = `The given values (${caseName}) describe NO valid triangle — the slides show why.`;
    else if (result.ambiguous) summary = `This is the ambiguous case (${caseName}): TWO different triangles fit your numbers. The slides solve it with the Law of Sines and show both solutions.`;
    else summary = `A worked, step-by-step solution for your triangle (${caseName}). Each slide reveals one step — set-up, the law used, and the computation with your numbers.`;
    const eq = given.__order.map((k) => `${k}=${g(given[k])}` + (k === k.toUpperCase() ? "°" : "")).join("  ");
    return {
      title: "Solving your triangle — step by step",
      tag: "Worked solution", dimension: "2D", equation: eq, summary,
      bullets: [
        "Each slide is one step of the solution, advancing automatically.",
        "The triangle is drawn to scale; values fill in as they're found.",
        "It uses YOUR numbers — not a generic example.",
        result.ambiguous ? "Two triangles fit (the SSA ambiguous case) — both are shown." : "The chosen law (Sines/Cosines) is named at each step.",
      ],
      student_prompts: [
        "Why does this case use the Law of Sines (or Cosines)?",
        "When does a triangle problem have two answers?",
        "How do I check my solution is right?",
      ],
      code: solverCode(result), kind: "triangle",
    };
  }

  // --- Polynomial equation solver (numeric quadratic / linear) ------------
  const FUNC_RE = /sin|cos|tan|sec|csc|cot|sqrt|log|ln|abs|exp|pi|sum|int|mod/;

  function parsePolySide(s) {
    s = s.replace(/\*/g, "");
    if (!s) return { 0: 0, 1: 0, 2: 0 };
    s = s.replace(/-/g, "+-");
    const coeffs = { 0: 0, 1: 0, 2: 0 };
    for (const term of s.split("+")) {
      if (!term) continue;
      let m = term.match(/^(-?\d*\.?\d*)x(?:\^(\d+))?$/);
      if (m) {
        const cs = m[1], ps = m[2];
        const c = cs === "-" ? -1 : (cs === "" || cs === "+" ? 1 : parseFloat(cs));
        const p = ps ? parseInt(ps, 10) : 1;
        if (p > 2) return null;
        coeffs[p] += c;
        continue;
      }
      m = term.match(/^(-?\d+\.?\d*)$/);
      if (m) { coeffs[0] += parseFloat(m[1]); continue; }
      return null;
    }
    return coeffs;
  }

  function parsePolynomial(prompt) {
    if (!prompt || (prompt.split("=").length - 1) !== 1) return null;
    let s = prompt.trim().toLowerCase().replace(/\s/g, "");
    s = s.replace(/²/g, "^2").replace(/³/g, "^3").replace(/[−–]/g, "-");
    s = s.replace(/^(solve|find|rootsof|rootof|zerosof|zeroof)/, "");
    if (FUNC_RE.test(s)) return null;
    const letters = Array.from(new Set(s.match(/[a-z]/g) || []));
    if (letters.length !== 1) return null;
    const varName = letters[0];
    s = s.split(varName).join("x");
    if (!/^[0-9x.+\-^=]+$/.test(s)) return null;
    const parts = s.split("=");
    const cl = parsePolySide(parts[0]), cr = parsePolySide(parts[1]);
    if (!cl || !cr) return null;
    const coeffs = { 0: cl[0] - cr[0], 1: cl[1] - cr[1], 2: cl[2] - cr[2] };
    const degree = Math.abs(coeffs[2]) > 1e-12 ? 2 : (Math.abs(coeffs[1]) > 1e-12 ? 1 : 0);
    if (degree === 0) return null;
    return { var: varName, coeffs, degree };
  }

  function fmt(x) {
    if (Math.abs(x - Math.round(x)) < 1e-9) return String(Math.round(x));
    return (Math.round(x * 100) / 100).toString();
  }

  function solveQuadratic(coeffs, v) {
    const a = coeffs[2], b = coeffs[1], c = coeffs[0];
    const D = b * b - 4 * a * c;
    const vx = -b / (2 * a), vy = c - (b * b) / (4 * a);
    const steps = [
      { title: "Standard form", formula: `a${v}² + b${v} + c = 0`, detail: `a = ${fmt(a)},  b = ${fmt(b)},  c = ${fmt(c)}` },
      { title: "Discriminant", formula: "D = b² − 4ac", detail: `D = (${fmt(b)})² − 4·(${fmt(a)})·(${fmt(c)}) = ${fmt(D)}` + (D > 1e-9 ? "  → two real roots" : (Math.abs(D) <= 1e-9 ? "  → one repeated root" : "  → no real roots")) },
      { title: "Quadratic formula", formula: `${v} = (−b ± √D) / (2a)`, detail: `${v} = (${fmt(-b)} ± √${fmt(D)}) / ${fmt(2 * a)}` },
    ];
    let realRoots = [];
    if (D > 1e-9) {
      const r1 = (-b + Math.sqrt(D)) / (2 * a), r2 = (-b - Math.sqrt(D)) / (2 * a);
      realRoots = [r1, r2];
      steps.push({ title: "The two roots", formula: `${v}₁, ${v}₂`, detail: `${v} = ${fmt(r1)}  or  ${v} = ${fmt(r2)}` });
    } else if (Math.abs(D) <= 1e-9) {
      const r1 = -b / (2 * a);
      realRoots = [r1];
      steps.push({ title: "One repeated root", formula: `${v} = −b / 2a`, detail: `${v} = ${fmt(r1)}  (the vertex touches the x-axis)` });
    } else {
      const rev = -b / (2 * a), im = Math.sqrt(-D) / (2 * a);
      steps.push({ title: "Complex roots", formula: `${v} = −b/2a ± (√−D /2a) i`, detail: `${v} = ${fmt(rev)} ± ${fmt(Math.abs(im))}i  (parabola never crosses the x-axis)` });
    }
    return { kind: "quadratic", var: v, coeffs, steps, real_roots: realRoots, vertex: [vx, vy], discriminant: D };
  }

  function solveLinear(coeffs, v) {
    const b = coeffs[1], c = coeffs[0];
    const root = -c / b;
    const steps = [
      { title: "Standard form", formula: `a${v} + b = 0`, detail: `a = ${fmt(b)},  b = ${fmt(c)}` },
      { title: `Isolate ${v}`, formula: `a${v} = −b`, detail: `${fmt(b)}·${v} = ${fmt(-c)}` },
      { title: "Solve", formula: `${v} = −b / a`, detail: `${v} = ${fmt(-c)} / ${fmt(b)} = ${fmt(root)}` },
    ];
    return { kind: "linear", var: v, coeffs, steps, real_roots: [root], vertex: null, discriminant: null };
  }

  function polyCode(result) {
    const a = result.coeffs[2], b = result.coeffs[1], c = result.coeffs[0];
    const roots = result.real_roots || [];
    let xmin, xmax;
    if (result.kind === "quadratic") {
      const vx = result.vertex[0];
      const span = Math.max(3, ...(roots.length ? roots.map((r) => Math.abs(r - vx) * 1.5) : [3]));
      xmin = vx - span; xmax = vx + span;
    } else {
      const r = roots[0]; xmin = r - 5; xmax = r + 5;
    }
    const ys = [a * xmin * xmin + b * xmin + c, a * xmax * xmax + b * xmax + c, 0];
    if (result.kind === "quadratic") ys.push(result.vertex[1]);
    const lo = Math.min(...ys), hi = Math.max(...ys), pad = (hi - lo) * 0.18 + 1;
    const data = JSON.stringify({ steps: result.steps, a, b, c, roots, var: result.var, xMin: xmin, xMax: xmax, yMin: lo - pad, yMax: hi + pad, vertex: result.vertex });
    return (
      "H.background();\n" +
      "const D = " + data + ";\n" +
      "const w = H.W, hgt = H.H;\n" +
      "const N = D.steps.length;\n" +
      "const k = Math.floor((t / 3.4) % N);\n" +
      "const st = D.steps[k];\n" +
      "H.text('Step-by-step solution', 24, 30, { color: H.colors.ink, size: 18, weight: 700 });\n" +
      "H.text('Slide ' + (k + 1) + ' of ' + N + '  ·  solving for ' + D.var + ' with your numbers', 24, 52, { color: H.colors.sub, size: 13 });\n" +
      "for (let i = 0; i < N; i++) {\n" +
      "  H.circle(24 + i * 16, 70, 5, { fill: i === k ? H.colors.accent : (i < k ? H.colors.good : H.colors.grid) });\n" +
      "}\n" +
      "const v = H.plot2d({ xMin: D.xMin, xMax: D.xMax, yMin: D.yMin, yMax: D.yMax, box: { x: w * 0.40, y: hgt * 0.24, w: w * 0.55, h: hgt * 0.62 } });\n" +
      "v.grid(); v.axes();\n" +
      "v.fn(function (x) { return D.a * x * x + D.b * x + D.c; }, { color: H.colors.accent, width: 3 });\n" +
      "if (D.vertex) v.dot(D.vertex[0], D.vertex[1], { r: 5, fill: H.colors.warn });\n" +
      "for (let i = 0; i < D.roots.length; i++) {\n" +
      "  v.dot(D.roots[i], 0, { r: 7, fill: H.colors.good });\n" +
      "  v.text(D.var + '=' + (Math.round(D.roots[i] * 100) / 100), D.roots[i], 0, { color: H.colors.good, size: 12 });\n" +
      "}\n" +
      "const px = D.xMin + (D.xMax - D.xMin) * (0.5 + 0.5 * Math.sin(t));\n" +
      "v.dot(px, D.a * px * px + D.b * px + D.c, { r: 5, fill: H.colors.accent2 });\n" +
      "const cx = 24, cy = hgt * 0.30, cw = w * 0.33;\n" +
      "H.rect(cx, cy, cw, 150, { fill: 'rgba(124,196,255,0.07)', stroke: H.colors.accent, width: 1.4, radius: 12 });\n" +
      "H.text(st.title, cx + 16, cy + 28, { color: H.colors.accent, size: 16, weight: 700, maxWidth: cw - 32 });\n" +
      "H.text(st.formula, cx + 16, cy + 62, { color: H.colors.ink, size: 15, weight: 700, maxWidth: cw - 32 });\n" +
      "H.text(st.detail, cx + 16, cy + 96, { color: H.colors.sub, size: 13, maxWidth: cw - 32 });\n"
    );
  }

  function polynomialScene(prompt) {
    const parsed = parsePolynomial(prompt);
    if (!parsed) return null;
    const { coeffs, degree } = parsed;
    let result, kindName, summary;
    if (degree === 2) {
      result = solveQuadratic(coeffs, parsed.var);
      kindName = "quadratic equation";
      const n = result.real_roots.length;
      summary = `A worked, step-by-step solution of your ${kindName}. The slides set up the standard form, compute the discriminant, apply the quadratic formula, and read off ` +
        (n === 2 ? "the two real roots" : (n === 1 ? "the repeated root" : "the complex roots")) +
        " — with the parabola drawn so you can see the roots as its x-intercepts.";
    } else if (degree === 1) {
      result = solveLinear(coeffs, parsed.var);
      kindName = "linear equation";
      summary = `A worked, step-by-step solution of your linear equation: move to standard form, isolate ${parsed.var}, and solve — with the line drawn so you can see the solution as its x-intercept.`;
    } else return null;
    return {
      title: `Solving your ${kindName} — step by step`,
      tag: "Worked solution", dimension: "2D", equation: prompt.trim(), summary,
      bullets: [
        "Each slide is one step of the solution, advancing automatically.",
        "The curve is drawn to scale; roots show as x-intercepts (green dots).",
        "It uses YOUR coefficients — not a generic example.",
        degree === 2 ? "The discriminant tells you how many real roots to expect." : "A linear equation has exactly one solution.",
      ],
      student_prompts: [
        degree === 2 ? "Why does the discriminant decide the number of real roots?" : "How do I check a linear solution?",
        "What do the roots mean on the graph?",
        "How would I solve this by factoring instead?",
      ],
      code: polyCode(result), kind: result.kind,
    };
  }

  function scene(prompt) {
    return triangleScene(prompt) || polynomialScene(prompt);
  }

  global.VisualLMSolver = { scene, parseTriangle, solveTriangle, parsePolynomial };
})(typeof window !== "undefined" ? window : this);
