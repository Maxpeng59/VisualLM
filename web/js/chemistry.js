/* VisualLM — Chemistry subsystem (browser port of chemistry.py).
 *
 * Pure client-side: a chemical formula -> 3D ball-and-stick structure; a
 * reaction -> exact integer-balanced equation with a conservation tally.
 * Faithful 1:1 port of the Python so the browser edition is identical to the
 * desktop app. Exposes a single global:
 *
 *   VisualLMChem.loadMolecules(array)   // merge the workflow-verified library
 *   VisualLMChem.scene(prompt)          // -> scene-content object | null
 *
 * The returned object matches the Python chemistry_scene() shape
 * (title/tag/dimension/equation/summary/bullets/student_prompts/code/kind).
 */
(function (global) {
  "use strict";

  // --- Element data --------------------------------------------------------
  const PERIODIC = new Set((
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni " +
    "Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe " +
    "Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg " +
    "Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu"
  ).split(" "));

  // sym -> [color, covalentRadiusÅ, valenceElectrons|null]
  const E = {
    H: ["#f5f7ff", 0.31, 1], He: ["#d9ffff", 0.28, 8], Li: ["#cc80ff", 1.28, 1],
    Be: ["#c2ff00", 0.96, 2], B: ["#ffb5b5", 0.84, 3], C: ["#4a4f5c", 0.76, 4],
    N: ["#5a7bff", 0.71, 5], O: ["#ff4d4d", 0.66, 6], F: ["#7fe06a", 0.57, 7],
    Ne: ["#b3e3f5", 0.58, 8], Na: ["#ab5cf2", 1.66, 1], Mg: ["#8aff00", 1.41, 2],
    Al: ["#bfa6a6", 1.21, 3], Si: ["#f0c8a0", 1.11, 4], P: ["#ff8000", 1.07, 5],
    S: ["#ffe23d", 1.05, 6], Cl: ["#3df04a", 1.02, 7], Ar: ["#80d1e3", 1.06, 8],
    K: ["#8f40d4", 2.03, 1], Ca: ["#3dff00", 1.76, 2], Mn: ["#9c7ac7", 1.39, null],
    Fe: ["#e06633", 1.32, null], Co: ["#f090a0", 1.26, null], Ni: ["#50d050", 1.24, null],
    Cu: ["#c88033", 1.32, null], Zn: ["#7d80b0", 1.22, null], Br: ["#c44d3a", 1.20, 7],
    Se: ["#ffa100", 1.20, 6], As: ["#bd80e3", 1.19, 5], I: ["#a04dd6", 1.39, 7],
    Xe: ["#66c6cf", 1.40, 8], Ag: ["#c0c0c8", 1.45, null], Au: ["#ffd123", 1.36, null],
    Pb: ["#575961", 1.46, 4], Sn: ["#9e9eae", 1.39, 4], Te: ["#d47a00", 1.38, 6],
    Sb: ["#9e63b5", 1.39, 5],
  };
  const DEFAULT_E = ["#ff80c0", 1.40, null];
  const elColor = (s) => (E[s] || DEFAULT_E)[0];
  const covRadius = (s) => (E[s] || DEFAULT_E)[1];
  const valence = (s) => (E[s] || DEFAULT_E)[2];

  function luminance(hex) {
    const h = hex.replace("#", "");
    if (h.length !== 6) return 0.5;
    const r = parseInt(h.slice(0, 2), 16) / 255;
    const g = parseInt(h.slice(2, 4), 16) / 255;
    const b = parseInt(h.slice(4, 6), 16) / 255;
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }
  const labelColor = (hex) => (luminance(hex) > 0.55 ? "#0c1020" : "#f3f6ff");

  // --- Formula parsing -----------------------------------------------------
  const TERMINALS = new Set(["H", "F", "Cl", "Br", "I"]);
  const FORMULA_TOKEN_RE = /^[A-Za-z0-9()]+[+-]?$/;

  function parseFormula(formula) {
    if (!formula) return null;
    let s = String(formula).trim().replace(/\^/g, "");
    s = s.replace(/\d*[+-]$/, "");
    if (!s || !/^[A-Za-z0-9()]+$/.test(s)) return null;
    const counts = {};
    const stack = [counts];
    let i = 0;
    const n = s.length;
    while (i < n) {
      const ch = s[i];
      if (ch === "(") {
        stack.push({});
        i++;
      } else if (ch === ")") {
        i++;
        let j = i;
        while (j < n && /\d/.test(s[j])) j++;
        const mult = j > i ? parseInt(s.slice(i, j), 10) : 1;
        i = j;
        if (stack.length < 2) return null;
        const group = stack.pop();
        const top = stack[stack.length - 1];
        for (const el in group) top[el] = (top[el] || 0) + group[el] * mult;
      } else if (ch >= "A" && ch <= "Z") {
        let j = i + 1;
        if (j < n && s[j] >= "a" && s[j] <= "z") j++;
        const sym = s.slice(i, j);
        if (!PERIODIC.has(sym)) return null;
        i = j;
        j = i;
        while (j < n && /\d/.test(s[j])) j++;
        const cnt = j > i ? parseInt(s.slice(i, j), 10) : 1;
        i = j;
        const top = stack[stack.length - 1];
        top[sym] = (top[sym] || 0) + cnt;
      } else {
        return null;
      }
    }
    if (stack.length !== 1) return null;
    const out = {};
    for (const k in counts) if (counts[k] > 0) out[k] = counts[k];
    return Object.keys(out).length ? out : null;
  }

  const SUBS = { "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉" };
  const prettyFormula = (f) => String(f).replace(/\d+/g, (m) => m.replace(/\d/g, (d) => SUBS[d]));

  const HILL = ["C", "H"];
  function canonicalFormula(counts) {
    const parts = [];
    for (const el of HILL) if (el in counts) parts.push(el + (counts[el] > 1 ? counts[el] : ""));
    for (const el of Object.keys(counts).filter((k) => HILL.indexOf(k) < 0).sort())
      parts.push(el + (counts[el] > 1 ? counts[el] : ""));
    return parts.join("");
  }
  function canon(formula) {
    const c = parseFormula(formula);
    return c ? canonicalFormula(c) : formula;
  }
  const shapeName = (f, shape) => (shape ? prettyFormula(f) + " — " + shape : prettyFormula(f));

  // --- Equation parsing + balancing ---------------------------------------
  const ARROW_RE = /\s*(?:=+>|-+>|→|⟶|⇌|=)\s*/;
  const NONSPECIES = new Set(["heat", "energy", "light", "δ", "delta"]);

  function parseEquation(text) {
    if (!text) return null;
    const m = text.trim().split(ARROW_RE);
    if (m.length < 2) return null;
    const left = m[0];
    const right = m[m.length - 1];
    const species = (side) => {
      const out = [];
      for (let chunk of side.split("+")) {
        chunk = chunk.trim();
        if (!chunk) continue;
        if (NONSPECIES.has(chunk.toLowerCase())) continue;
        const cm = chunk.match(/^(\d+)\s*([A-Za-z(].*)$/);
        const formula = cm ? cm[2].trim() : chunk;
        if (parseFormula(formula) === null) return null;
        out.push(formula);
      }
      return out.length ? out : null;
    };
    const r = species(left);
    const p = species(right);
    if (!r || !p) return null;
    return [r, p];
  }

  // exact rational arithmetic over BigInt
  function gcdBig(a, b) { a = a < 0n ? -a : a; b = b < 0n ? -b : b; while (b) { const t = a % b; a = b; b = t; } return a; }
  function F(n, d) {
    n = BigInt(n); d = d === undefined ? 1n : BigInt(d);
    if (d < 0n) { n = -n; d = -d; }
    const g = gcdBig(n, d) || 1n;
    return { n: n / g, d: d / g };
  }
  const fAdd = (a, b) => F(a.n * b.d + b.n * a.d, a.d * b.d);
  const fSub = (a, b) => F(a.n * b.d - b.n * a.d, a.d * b.d);
  const fMul = (a, b) => F(a.n * b.n, a.d * b.d);
  const fDiv = (a, b) => F(a.n * b.d, a.d * b.n);

  function rref(matrix) {
    const M = matrix.map((row) => row.slice());
    const rows = M.length;
    const cols = rows ? M[0].length : 0;
    const pivots = [];
    let r = 0;
    for (let c = 0; c < cols; c++) {
      let pivot = -1;
      for (let i = r; i < rows; i++) if (M[i][c].n !== 0n) { pivot = i; break; }
      if (pivot < 0) continue;
      const tmp = M[r]; M[r] = M[pivot]; M[pivot] = tmp;
      const inv = M[r][c];
      M[r] = M[r].map((x) => fDiv(x, inv));
      for (let i = 0; i < rows; i++) {
        if (i !== r && M[i][c].n !== 0n) {
          const f = M[i][c];
          M[i] = M[i].map((a, k) => fSub(a, fMul(f, M[r][k])));
        }
      }
      pivots.push(c);
      r++;
      if (r === rows) break;
    }
    return { rref: M, pivots };
  }

  function balanceEquation(reactants, products) {
    const species = reactants.concat(products);
    const n = species.length;
    if (n < 2) return null;
    const comps = species.map(parseFormula);
    if (comps.some((c) => c === null)) return null;
    const elements = Array.from(new Set([].concat(...comps.map((c) => Object.keys(c))))).sort();
    const A = elements.map((el) =>
      comps.map((c, idx) => {
        const v = c[el] || 0;
        return F(idx < reactants.length ? v : -v);
      })
    );
    const { rref: R, pivots } = rref(A);
    const free = [];
    for (let c = 0; c < n; c++) if (pivots.indexOf(c) < 0) free.push(c);
    if (free.length !== 1) return null;
    const fcol = free[0];
    const x = new Array(n).fill(null).map(() => F(0));
    x[fcol] = F(1);
    pivots.forEach((pc, ri) => { x[pc] = F(-R[ri][fcol].n, R[ri][fcol].d); });
    let lcm = 1n;
    for (const v of x) lcm = (lcm * v.d) / gcdBig(lcm, v.d);
    let ints = x.map((v) => (v.n * lcm) / v.d);
    let g = 0n;
    for (const v of ints) g = gcdBig(g, v < 0n ? -v : v);
    if (g === 0n) return null;
    ints = ints.map((v) => v / g);
    if (ints.every((v) => v <= 0n)) ints = ints.map((v) => -v);
    if (ints.some((v) => v <= 0n)) return null;
    return ints.map((v) => Number(v));
  }

  // --- VSEPR geometry ------------------------------------------------------
  function unit(v) {
    const n = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) || 1;
    return [v[0] / n, v[1] / n, v[2] / n];
  }
  const tetra = () => [[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]].map(unit);
  const trigPlanar = () => [0, (2 * Math.PI) / 3, (4 * Math.PI) / 3].map((a) => [Math.cos(a), Math.sin(a), 0]);
  const tbp = () => [[0, 1, 0], [0, -1, 0]].concat([0, (2 * Math.PI) / 3, (4 * Math.PI) / 3].map((a) => [Math.cos(a), 0, Math.sin(a)]));
  const octa = () => [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];

  function geometry(sn, lp) {
    if (sn === 2) return [[[1, 0, 0], [-1, 0, 0]], "linear"];
    if (sn === 3) {
      const t = trigPlanar();
      if (lp === 0) return [t, "trigonal planar"];
      if (lp === 1) return [[t[1], t[2]], "bent"];
    }
    if (sn === 4) {
      const t = tetra();
      if (lp === 0) return [t, "tetrahedral"];
      if (lp === 1) return [t.slice(1), "trigonal pyramidal"];
      if (lp === 2) return [[t[1], t[2]], "bent"];
    }
    if (sn === 5) {
      const t = tbp();
      if (lp === 0) return [t, "trigonal bipyramidal"];
      if (lp === 1) return [[t[0], t[1], t[3], t[4]], "seesaw"];
      if (lp === 2) return [[t[0], t[1], t[2]], "T-shaped"];
      if (lp === 3) return [[t[0], t[1]], "linear"];
    }
    if (sn === 6) {
      const o = octa();
      if (lp === 0) return [o, "octahedral"];
      if (lp === 1) return [o.slice(0, 5), "square pyramidal"];
      if (lp === 2) return [[o[0], o[1], o[4], o[5]], "square planar"];
    }
    return [null, null];
  }

  function vseprMolecule(formula) {
    const counts = parseFormula(formula);
    if (!counts) return null;
    const nonTerminal = Object.keys(counts).filter((e) => !TERMINALS.has(e));
    if (nonTerminal.length !== 1 || counts[nonTerminal[0]] !== 1) return null;
    const central = nonTerminal[0];
    const ve = valence(central);
    if (ve === null) return null;
    const terminals = [];
    for (const el in counts) if (el !== central) for (let k = 0; k < counts[el]; k++) terminals.push(el);
    const n = terminals.length;
    if (n < 2) return null;
    const lone2 = ve - n;
    if (lone2 < 0 || lone2 % 2 !== 0) return null;
    const lp = lone2 / 2;
    const sn = n + lp;
    const [dirs, shape] = geometry(sn, lp);
    if (!dirs || dirs.length !== n) return null;
    terminals.sort((a, b) => covRadius(b) - covRadius(a));
    const atoms = [{ e: central, p: [0, 0, 0] }];
    const bonds = [];
    const rc = covRadius(central);
    dirs.forEach((d, k) => {
      const el = terminals[k];
      const len = rc + covRadius(el);
      const u = unit(d);
      atoms.push({ e: el, p: [u[0] * len, u[1] * len, u[2] * len] });
      bonds.push([0, k + 1, 1]);
    });
    return { atoms, bonds, shape };
  }

  // --- Curated library (seed) + merged generated --------------------------
  function diatomic(a, b, order, length) {
    if (length == null) length = covRadius(a) + covRadius(b);
    return { atoms: [{ e: a, p: [-length / 2, 0, 0] }, { e: b, p: [length / 2, 0, 0] }], bonds: [[0, 1, order]] };
  }
  function co2() {
    const d = 1.16;
    return { atoms: [{ e: "C", p: [0, 0, 0] }, { e: "O", p: [-d, 0, 0] }, { e: "O", p: [d, 0, 0] }], bonds: [[0, 1, 2], [0, 2, 2]] };
  }
  function bentTri(center, outer, angleDeg, len, order) {
    const half = (angleDeg * Math.PI) / 180 / 2;
    const dx = len * Math.sin(half), dy = len * Math.cos(half);
    return { atoms: [{ e: center, p: [0, 0, 0] }, { e: outer, p: [-dx, -dy, 0] }, { e: outer, p: [dx, -dy, 0] }], bonds: [[0, 1, order], [0, 2, order]] };
  }
  function benzene() {
    const R = 1.39, Rh = R + 1.09, atoms = [], bonds = [];
    for (let i = 0; i < 6; i++) { const a = (i * Math.PI) / 3; atoms.push({ e: "C", p: [R * Math.cos(a), R * Math.sin(a), 0] }); }
    for (let i = 0; i < 6; i++) { const a = (i * Math.PI) / 3; atoms.push({ e: "H", p: [Rh * Math.cos(a), Rh * Math.sin(a), 0] }); }
    for (let i = 0; i < 6; i++) { bonds.push([i, (i + 1) % 6, i % 2 === 0 ? 2 : 1]); bonds.push([i, i + 6, 1]); }
    return { atoms, bonds };
  }

  function seedLibrary() {
    return {
      H2: Object.assign(diatomic("H", "H", 1, 0.74), { name: "Hydrogen (H₂)", names: ["hydrogen", "dihydrogen"] }),
      O2: Object.assign(diatomic("O", "O", 2, 1.21), { name: "Oxygen (O₂)", names: ["oxygen", "dioxygen"] }),
      N2: Object.assign(diatomic("N", "N", 3, 1.10), { name: "Nitrogen (N₂)", names: ["nitrogen", "dinitrogen"] }),
      Cl2: Object.assign(diatomic("Cl", "Cl", 1, 1.99), { name: "Chlorine (Cl₂)", names: ["chlorine"] }),
      HCl: Object.assign(diatomic("H", "Cl", 1, 1.27), { name: "Hydrogen chloride (HCl)", names: ["hydrogen chloride", "hydrochloric acid"] }),
      HF: Object.assign(diatomic("H", "F", 1, 0.92), { name: "Hydrogen fluoride (HF)", names: ["hydrogen fluoride"] }),
      CO: Object.assign(diatomic("C", "O", 3, 1.13), { name: "Carbon monoxide (CO)", names: ["carbon monoxide"] }),
      NaCl: Object.assign(diatomic("Na", "Cl", 1, 2.36), { name: "Sodium chloride (NaCl)", names: ["sodium chloride", "table salt", "halite"] }),
      CO2: Object.assign(co2(), { name: "Carbon dioxide (CO₂)", names: ["carbon dioxide", "dry ice"] }),
      SO2: Object.assign(bentTri("S", "O", 119.0, 1.43, 2), { name: "Sulfur dioxide (SO₂)", names: ["sulfur dioxide", "sulphur dioxide"] }),
      O3: Object.assign(bentTri("O", "O", 117.0, 1.28, 1), { name: "Ozone (O₃)", names: ["ozone"] }),
      C6H6: Object.assign(benzene(), { name: "Benzene (C₆H₆)", names: ["benzene"] }),
    };
  }

  const COMMON_NAMES = {
    methane: "CH4", ammonia: "NH3", water: "H2O", "carbon dioxide": "CO2",
    "carbon monoxide": "CO", benzene: "C6H6", ozone: "O3", "sulfur dioxide": "SO2",
    "sulphur dioxide": "SO2", "sulfur hexafluoride": "SF6", "phosphorus pentachloride": "PCl5",
    "boron trifluoride": "BF3", "hydrogen sulfide": "H2S", methanol: "CH4O",
    ethanol: "C2H6O", glucose: "C6H12O6", "acetic acid": "C2H4O2", ethane: "C2H6",
    ethene: "C2H4", ethyne: "C2H2", acetylene: "C2H2", ethylene: "C2H4",
    "hydrogen peroxide": "H2O2", ammonium: "NH4", silane: "SiH4", phosphine: "PH3",
    "sodium chloride": "NaCl", "table salt": "NaCl",
  };
  const AMBIGUOUS_NAMES = new Set(["water", "oxygen", "nitrogen", "hydrogen", "salt", "ozone"]);

  const MOLECULES = {};
  const NAME_INDEX = {};

  function register(disp, mol) {
    const c = canon(disp);
    const m = Object.assign({}, mol);
    if (!("formula" in m)) m.formula = disp;
    MOLECULES[c] = m;
  }
  function indexNames() {
    for (const k in NAME_INDEX) delete NAME_INDEX[k];
    for (const c in MOLECULES) {
      NAME_INDEX[c.toLowerCase()] = c;
      const disp = MOLECULES[c].formula || c;
      NAME_INDEX[disp.toLowerCase()] = c;
      for (const nm of MOLECULES[c].names || []) NAME_INDEX[String(nm).trim().toLowerCase()] = c;
    }
  }
  function loadMolecules(items) {
    for (const k in MOLECULES) delete MOLECULES[k];
    const seed = seedLibrary();
    for (const disp in seed) register(disp, seed[disp]);
    if (Array.isArray(items)) {
      for (const mol of items) {
        if (mol && mol.formula && Array.isArray(mol.atoms) && mol.bonds != null) register(mol.formula, mol);
      }
    }
    indexNames();
  }
  loadMolecules([]); // seed-only until the generated library is injected

  // --- Lookup --------------------------------------------------------------
  function normalizeGeometry(mol) {
    const atoms = mol.atoms;
    const cx = atoms.reduce((s, a) => s + a.p[0], 0) / atoms.length;
    const cy = atoms.reduce((s, a) => s + a.p[1], 0) / atoms.length;
    const cz = atoms.reduce((s, a) => s + a.p[2], 0) / atoms.length;
    let maxr = 0;
    for (const a of atoms) {
      const d = Math.sqrt((a.p[0] - cx) ** 2 + (a.p[1] - cy) ** 2 + (a.p[2] - cz) ** 2);
      if (d > maxr) maxr = d;
    }
    const k = maxr > 1e-6 ? 3.0 / maxr : 1.0;
    const round = (x) => Math.round(x * 1e4) / 1e4;
    const outAtoms = atoms.map((a) => {
      const col = elColor(a.e);
      return {
        e: a.e,
        p: [round((a.p[0] - cx) * k), round((a.p[1] - cy) * k), round((a.p[2] - cz) * k)],
        c: col,
        lc: labelColor(col),
        r: round(Math.max(0.28, covRadius(a.e) * 0.42) * k),
      };
    });
    const bonds = mol.bonds.map((b) => [b[0] | 0, b[1] | 0, (b.length > 2 ? b[2] : 1) | 0]);
    return { atoms: outAtoms, bonds };
  }

  function libraryGeo(c, dispOverride) {
    const mol = MOLECULES[c];
    const geo = normalizeGeometry(mol);
    geo.formula = dispOverride || mol.formula || c;
    geo.name = mol.name || prettyFormula(geo.formula);
    geo.shape = mol.shape || "";
    return geo;
  }

  function lookupMolecule(query) {
    if (!query) return null;
    const q = String(query).trim();
    const counts = parseFormula(q);
    if (counts) {
      const c = canonicalFormula(counts);
      if (c in MOLECULES) return libraryGeo(c);
      const v = vseprMolecule(q);
      if (v) {
        const geo = normalizeGeometry(v);
        geo.formula = q;
        geo.name = shapeName(q, v.shape);
        geo.shape = v.shape || "";
        return geo;
      }
      return null;
    }
    const key = q.toLowerCase();
    if (key in NAME_INDEX) return libraryGeo(NAME_INDEX[key]);
    if (key in COMMON_NAMES) return lookupMolecule(COMMON_NAMES[key]);
    return null;
  }

  // --- Detection -----------------------------------------------------------
  const CHEM_KEYWORDS = /\b(molecul\w*|compound|lewis|vsepr|ball[- ]and[- ]stick|3d\s+structure|structure of|shape of|geometry of|bond(s|ing)?|chemical structure)\b/i;
  const COMMAND_PREFIX = /^\s*(please\s+)?(balance|solve|complete|finish)\b(\s+(the|this))?(\s+(equation|reaction|chemical\s+equation))?\s*[:\-]?\s*/i;

  function looksLikeFormula(token) {
    const counts = parseFormula(token);
    if (!counts) return false;
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    if (total < 2) return false;
    const hasDigit = /\d/.test(token);
    const multiEl = Object.keys(counts).length >= 2;
    return hasDigit || multiEl;
  }
  function findFormula(prompt) {
    let best = null;
    for (const raw of prompt.trim().split(/[\s,;:]+/)) {
      const tok = raw.replace(/^[.?!)（）"']+|[.?!)（）"']+$/g, "").trim();
      if (!tok || !FORMULA_TOKEN_RE.test(tok)) continue;
      if (looksLikeFormula(tok)) { if (best === null || tok.length > best.length) best = tok; }
    }
    return best;
  }
  function bareNameTriggers() {
    const names = new Set();
    for (const k in NAME_INDEX) if (/^[a-z]+$/.test(k) && k.length >= 4) names.add(k);
    for (const k in COMMON_NAMES) if (k.split(" ").every((p) => /^[a-z]+$/.test(p)) && k.length >= 4) names.add(k);
    for (const a of AMBIGUOUS_NAMES) names.delete(a);
    return names;
  }
  function detectChemistry(prompt) {
    if (!prompt) return null;
    const text = prompt.trim();
    const reactionText = text.replace(COMMAND_PREFIX, "");
    const eq = parseEquation(reactionText);
    if (eq !== null) return ["balance", eq];
    const formula = findFormula(text);
    if (formula !== null) return ["molecule", formula];
    const low = text.toLowerCase();
    let candidates;
    if (CHEM_KEYWORDS.test(text)) {
      candidates = new Set([].concat(Object.keys(NAME_INDEX), Object.keys(COMMON_NAMES)));
    } else {
      candidates = bareNameTriggers();
    }
    const sorted = Array.from(candidates).sort((a, b) => b.length - a.length);
    for (const name of sorted) {
      if (name.length >= 4 && new RegExp("\\b" + name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b").test(low))
        return ["molecule", name];
    }
    return null;
  }

  // --- Scene code builders (emit a bare scene(ctx,t) body) ----------------
  function moleculeCode(mol) {
    const data = JSON.stringify({ atoms: mol.atoms, bonds: mol.bonds, name: mol.name, formula: prettyFormula(mol.formula) });
    return (
      "H.background();\n" +
      "const MOL = " + data + ";\n" +
      "const w = H.W, hgt = H.H;\n" +
      "const cam = H.cam3d({ scale: 46, dist: 15, pitch: -0.16, cy: hgt * 0.54 });\n" +
      "cam.yaw = 0.45 * t;\n" +
      "const proj = MOL.atoms.map(function (a) { return cam.project(a.p); });\n" +
      "function bond(i, j, order) {\n" +
      "  const p1 = proj[i], p2 = proj[j];\n" +
      "  let dx = p2.x - p1.x, dy = p2.y - p1.y;\n" +
      "  const len = Math.sqrt(dx * dx + dy * dy) || 1;\n" +
      "  const ux = -dy / len, uy = dx / len;\n" +
      "  const gap = 3.4;\n" +
      "  const offs = order >= 3 ? [-gap * 1.5, 0, gap * 1.5]\n" +
      "    : order === 2 ? [-gap, gap] : [0];\n" +
      "  for (let k = 0; k < offs.length; k++) {\n" +
      "    const o = offs[k];\n" +
      "    H.line(p1.x + ux * o, p1.y + uy * o, p2.x + ux * o, p2.y + uy * o,\n" +
      "      { color: '#9aa3c0', width: 3 });\n" +
      "  }\n" +
      "}\n" +
      "for (let b = 0; b < MOL.bonds.length; b++) {\n" +
      "  bond(MOL.bonds[b][0], MOL.bonds[b][1], MOL.bonds[b][2]);\n" +
      "}\n" +
      "const order = MOL.atoms.map(function (a, idx) {\n" +
      "  return { idx: idx, depth: proj[idx].depth };\n" +
      "}).sort(function (u, v) { return v.depth - u.depth; });\n" +
      "for (let s = 0; s < order.length; s++) {\n" +
      "  const a = MOL.atoms[order[s].idx];\n" +
      "  cam.sphere(a.p, a.r, { color: a.c, stroke: 'rgba(6,8,18,0.45)', width: 1 });\n" +
      "  const q = proj[order[s].idx];\n" +
      "  if (a.e !== 'H') H.text(a.e, q.x, q.y,\n" +
      "    { color: a.lc, size: 12, weight: 700, align: 'center', baseline: 'middle' });\n" +
      "}\n" +
      "H.text(MOL.name, 24, 30, { color: H.colors.ink, size: 18, weight: 700 });\n" +
      "H.text(MOL.formula + '  ·  drag to orbit, scroll to zoom', 24, 52,\n" +
      "  { color: H.colors.sub, size: 13 });\n" +
      "H.legend(MOL.atoms.filter(function (a, i, arr) {\n" +
      "  return arr.findIndex(function (b) { return b.e === a.e; }) === i;\n" +
      "}).map(function (a) { return { label: a.e, color: a.c }; }), 24, hgt - 28);\n"
    );
  }

  function balanceCode(reactants, products, coeffs) {
    const nr = reactants.length;
    const rc = coeffs.slice(0, nr);
    const pc = coeffs.slice(nr);
    const comps = reactants.concat(products).map(parseFormula);
    const elements = Array.from(new Set([].concat(...comps.map((c) => Object.keys(c))))).sort();
    const tally = elements.map((el) => {
      let left = 0, right = 0;
      for (let i = 0; i < nr; i++) left += rc[i] * (comps[i][el] || 0);
      for (let i = 0; i < products.length; i++) right += pc[i] * (comps[nr + i][el] || 0);
      return { el, left, right, color: elColor(el) };
    });
    const side = (formulas, cs) => formulas.map((f, i) => ({ coef: cs[i], formula: prettyFormula(f) }));
    const eqstr = (formulas, cs) => formulas.map((f, i) => (cs[i] !== 1 ? cs[i] + " " : "") + prettyFormula(f)).join("  +  ");
    const balanced = eqstr(reactants, rc) + "   →   " + eqstr(products, pc);
    const data = JSON.stringify({ reactants: side(reactants, rc), products: side(products, pc), tally, balanced });
    return (
      "H.background();\n" +
      "const EQ = " + data + ";\n" +
      "const w = H.W, hgt = H.H;\n" +
      "H.text('Balancing the equation', 24, 30,\n" +
      "  { color: H.colors.ink, size: 18, weight: 700 });\n" +
      "H.text('Coefficients chosen so every element is conserved (same count on both sides).',\n" +
      "  24, 52, { color: H.colors.sub, size: 13 });\n" +
      "// Reactant cards (left) -> arrow -> product cards (right). The layout\n" +
      "// scales to the canvas width so even a 6-species reaction fits.\n" +
      "const nL = EQ.reactants.length, nR = EQ.products.length;\n" +
      "const nCards = nL + nR;\n" +
      "const margin = 34, arrowGap = 64;\n" +
      "const gapX = Math.min(124, (w - 2 * margin - arrowGap) / Math.max(1, nCards));\n" +
      "const cw = Math.min(100, gapX * 0.82), ch = 50;\n" +
      "const fs = Math.max(11, Math.min(20, cw * 0.21));\n" +
      "const midY = hgt * 0.40;\n" +
      "function card(cx, item, accent) {\n" +
      "  H.rect(cx - cw / 2, midY - ch / 2, cw, ch,\n" +
      "    { fill: 'rgba(124,196,255,0.08)', stroke: accent, width: 1.5, radius: 10 });\n" +
      "  H.text(item.formula, cx, midY + 3,\n" +
      "    { color: H.colors.ink, size: fs, weight: 700, align: 'center', baseline: 'middle' });\n" +
      "  if (item.coef !== 1) {\n" +
      "    H.circle(cx - cw / 2, midY - ch / 2, 13, { fill: accent });\n" +
      "    H.text(String(item.coef), cx - cw / 2, midY - ch / 2 + 1,\n" +
      "      { color: '#0c1020', size: 13, weight: 700, align: 'center', baseline: 'middle' });\n" +
      "  }\n" +
      "}\n" +
      "const totalW = nCards * gapX + arrowGap;\n" +
      "const start = w / 2 - totalW / 2 + gapX / 2;\n" +
      "for (let i = 0; i < nL; i++) {\n" +
      "  const cx = start + i * gapX;\n" +
      "  card(cx, EQ.reactants[i], H.colors.accent);\n" +
      "  if (i < nL - 1) H.text('+', cx + gapX / 2, midY,\n" +
      "    { color: H.colors.sub, size: 20, align: 'center', baseline: 'middle' });\n" +
      "}\n" +
      "const px0 = start + nL * gapX + arrowGap;\n" +
      "const ax0 = start + (nL - 1) * gapX + cw / 2 + 6, ax1 = px0 - cw / 2 - 6;\n" +
      "H.arrow(ax0, midY, ax1, midY, { color: H.colors.good, width: 3 });\n" +
      "const gx = ax0 + (ax1 - ax0) * (0.5 + 0.5 * Math.sin(t * 1.6));\n" +
      "H.circle(gx, midY, 4, { fill: H.colors.yellow });\n" +
      "for (let i = 0; i < nR; i++) {\n" +
      "  const cx = px0 + i * gapX;\n" +
      "  card(cx, EQ.products[i], H.colors.good);\n" +
      "  if (i < nR - 1) H.text('+', cx + gapX / 2, midY,\n" +
      "    { color: H.colors.sub, size: 20, align: 'center', baseline: 'middle' });\n" +
      "}\n" +
      "H.text(EQ.balanced, w / 2, hgt * 0.62,\n" +
      "  { color: H.colors.accent, size: 18, weight: 700, align: 'center', baseline: 'middle' });\n" +
      "const rows = EQ.tally.length;\n" +
      "const ty0 = hgt * 0.72, rowH = 24;\n" +
      "const tx = Math.max(40, w / 2 - 160);\n" +
      "const reveal = Math.floor((t * 1.1) % (rows + 2));\n" +
      "H.text('Atom balance', tx, ty0 - 22,\n" +
      "  { color: H.colors.sub, size: 12, weight: 700 });\n" +
      "for (let i = 0; i < rows; i++) {\n" +
      "  const r = EQ.tally[i];\n" +
      "  const yy = ty0 + i * rowH;\n" +
      "  const on = i <= reveal;\n" +
      "  H.circle(tx, yy, 7, { fill: on ? r.color : H.colors.grid });\n" +
      "  H.text(r.el, tx, yy + 1,\n" +
      "    { color: '#0c1020', size: 10, weight: 700, align: 'center', baseline: 'middle' });\n" +
      "  H.text(r.left + ' = ' + r.right + (on ? '   ✓' : ''), tx + 18, yy + 1,\n" +
      "    { color: on ? H.colors.good : H.colors.sub, size: 14, baseline: 'middle' });\n" +
      "}\n"
    );
  }

  // --- Public entry --------------------------------------------------------
  function scene(prompt) {
    const hit = detectChemistry(prompt);
    if (hit === null) return null;
    const kind = hit[0], payload = hit[1];

    if (kind === "molecule") {
      const mol = lookupMolecule(payload);
      if (mol === null) return null;
      const shape = mol.shape || "";
      const summary =
        "3D ball-and-stick structure of " + mol.name +
        (shape ? ", a " + shape + " molecule." : ".") +
        " Atoms are colored by element (CPK); sticks are bonds. Drag to orbit.";
      const bullets = [
        "Each ball is an atom (colored by element); each stick is a bond.",
        "Double and triple bonds are drawn as 2 or 3 parallel sticks.",
        shape
          ? "The arrangement is " + shape + " — set by how electron pairs spread out (VSEPR)."
          : "The 3D arrangement reflects how the atoms bond in space.",
      ];
      return {
        title: mol.name, tag: "Chemistry", dimension: "3D", equation: mol.formula,
        summary, bullets,
        student_prompts: [
          "Why does " + mol.formula + " take this shape?",
          "What are the bond angles in this molecule?",
          "How do lone pairs change the geometry?",
        ],
        code: moleculeCode(mol), kind: "molecule",
      };
    }

    if (kind === "balance") {
      const reactants = payload[0], products = payload[1];
      const coeffs = balanceEquation(reactants, products);
      if (coeffs === null) return null;
      const nr = reactants.length;
      const eq = (formulas, cs) => formulas.map((f, i) => (cs[i] !== 1 ? cs[i] + " " : "") + f).join(" + ");
      const balancedPlain = eq(reactants, coeffs.slice(0, nr)) + " -> " + eq(products, coeffs.slice(nr));
      return {
        title: "Balanced chemical equation", tag: "Chemistry", dimension: "2D",
        equation: balancedPlain,
        summary:
          "The reaction balanced so atoms of every element are conserved. " +
          "Reactants (left) combine in the shown ratio to give the products (right); " +
          "the tally proves each element's count matches on both sides.",
        bullets: [
          "Coefficients are the smallest whole numbers that conserve every atom.",
          "Atoms are never created or destroyed — only rearranged (conservation of mass).",
          "The badge on each card is how many of that molecule the balance requires.",
        ],
        student_prompts: [
          "How do you find balancing coefficients systematically?",
          "Why must the atom counts match on both sides?",
          "What is the mole ratio between the reactants here?",
        ],
        code: balanceCode(reactants, products, coeffs), kind: "balance",
      };
    }
    return null;
  }

  global.VisualLMChem = {
    loadMolecules, scene,
    // exposed for parity testing
    parseFormula, balanceEquation, detectChemistry, lookupMolecule, vseprMolecule, canonicalFormula,
  };
})(typeof window !== "undefined" ? window : this);
