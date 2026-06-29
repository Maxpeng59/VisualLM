"""Chemistry visualization subsystem for VisualLM.

Two capabilities, both fired from `chemistry_scene(prompt)`:

  1. MOLECULE — a chemical formula or a known molecule name ("CH4", "benzene",
     "H2O") renders a 3D ball-and-stick structure. Geometry comes from one of:
       - a curated/validated library (`MOLECULES` + chemistry_molecules_generated.json),
       - a VSEPR generator for single-centre hydride/halide molecules (CH4, NH3,
         H2O, SF6, PCl5, ...), computed from valence electrons + electron-domain
         geometry. Correct angles, no hand coordinates needed.

  2. BALANCE — a reaction ("C3H8 + O2 -> CO2 + H2O") is balanced exactly (integer
     coefficients via the rational null space of the element-composition matrix)
     and rendered as reactant cards → balanced product cards, with a per-element
     conservation tally proving both sides match.

Pure standard library — no numpy/scipy. Coordinates are in Ångström internally
and normalized to a fixed on-screen size at render time, so every molecule frames
consistently. The emitted `code` is a bare `scene(ctx, t)` body using the worker's
`H`/`cam3d` helpers; it carries its own data as JS literals (no `P` params).
"""

from __future__ import annotations

import json
import math
import os
import re
from fractions import Fraction

# --------------------------------------------------------------------------- #
# Element data
# --------------------------------------------------------------------------- #

# Every real element symbol — used only to decide whether a token is a valid
# chemical formula (so we don't hijack a math/physics prompt). Curated visual
# data (color/radius) lives in ELEMENT_DATA below; anything here but not there
# renders with a neutral default.
PERIODIC = {
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
    "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr",
    "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
    "In", "Sn", "Sb", "Te", "I", "Xe",
    "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy",
    "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt",
    "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn",
    "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu",
}

# CPK-ish colors (tuned for a dark canvas), covalent radii (Å), and a label
# text color (light symbol on dark atoms, dark symbol on light atoms).
# (color, covalent_radius_Å, valence_electrons_or_None)
_E = {
    "H":  ("#f5f7ff", 0.31, 1),
    "He": ("#d9ffff", 0.28, 8),
    "Li": ("#cc80ff", 1.28, 1),
    "Be": ("#c2ff00", 0.96, 2),
    "B":  ("#ffb5b5", 0.84, 3),
    "C":  ("#4a4f5c", 0.76, 4),
    "N":  ("#5a7bff", 0.71, 5),
    "O":  ("#ff4d4d", 0.66, 6),
    "F":  ("#7fe06a", 0.57, 7),
    "Ne": ("#b3e3f5", 0.58, 8),
    "Na": ("#ab5cf2", 1.66, 1),
    "Mg": ("#8aff00", 1.41, 2),
    "Al": ("#bfa6a6", 1.21, 3),
    "Si": ("#f0c8a0", 1.11, 4),
    "P":  ("#ff8000", 1.07, 5),
    "S":  ("#ffe23d", 1.05, 6),
    "Cl": ("#3df04a", 1.02, 7),
    "Ar": ("#80d1e3", 1.06, 8),
    "K":  ("#8f40d4", 2.03, 1),
    "Ca": ("#3dff00", 1.76, 2),
    "Mn": ("#9c7ac7", 1.39, None),
    "Fe": ("#e06633", 1.32, None),
    "Co": ("#f090a0", 1.26, None),
    "Ni": ("#50d050", 1.24, None),
    "Cu": ("#c88033", 1.32, None),
    "Zn": ("#7d80b0", 1.22, None),
    "Br": ("#c44d3a", 1.20, 7),
    "Se": ("#ffa100", 1.20, 6),
    "As": ("#bd80e3", 1.19, 5),
    "I":  ("#a04dd6", 1.39, 7),
    "Xe": ("#66c6cf", 1.40, 8),
    "Ag": ("#c0c0c8", 1.45, None),
    "Au": ("#ffd123", 1.36, None),
    "Pb": ("#575961", 1.46, 4),
    "Sn": ("#9e9eae", 1.39, 4),
    "Te": ("#d47a00", 1.38, 6),
    "Sb": ("#9e63b5", 1.39, 5),
    "B ": ("#ffb5b5", 0.84, 3),
}

_DEFAULT_ELEMENT = ("#ff80c0", 1.40, None)  # neutral pink for uncolored elements


def element_color(sym: str) -> str:
    return _E.get(sym, _DEFAULT_ELEMENT)[0]


def covalent_radius(sym: str) -> float:
    return _E.get(sym, _DEFAULT_ELEMENT)[1]


def valence_electrons(sym: str):
    return _E.get(sym, _DEFAULT_ELEMENT)[2]


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return 0.5
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return 0.5
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _label_color(hex_color: str) -> str:
    return "#0c1020" if _luminance(hex_color) > 0.55 else "#f3f6ff"


# --------------------------------------------------------------------------- #
# Formula parsing
# --------------------------------------------------------------------------- #

_TERMINALS = {"H", "F", "Cl", "Br", "I"}
_FORMULA_TOKEN_RE = re.compile(r"^[A-Za-z0-9()]+[+-]?$")


def parse_formula(formula: str) -> dict | None:
    """'C6H12O6' -> {'C':6,'H':12,'O':6}; supports parentheses ('Ca(OH)2').

    Returns None if the string isn't a valid neutral formula over real elements.
    A trailing charge ('SO4^2-', 'NH4+') is tolerated and ignored.
    """
    if not formula:
        return None
    s = formula.strip()
    # Drop a trailing ionic charge. With a caret ('SO4^2-'), the charge is
    # everything after it. Without ('NH4+'), only a bare trailing sign is the
    # charge — any digits before it are subscripts, so don't eat them.
    if "^" in s:
        s = s.split("^", 1)[0]
    else:
        s = re.sub(r"[+-]$", "", s)
    if not s or not re.match(r"^[A-Za-z0-9()]+$", s):
        return None

    counts: dict[str, int] = {}
    stack: list[dict[str, int]] = [counts]
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "(":
            new: dict[str, int] = {}
            stack.append(new)
            i += 1
        elif ch == ")":
            i += 1
            j = i
            while j < n and s[j].isdigit():
                j += 1
            mult = int(s[i:j]) if j > i else 1
            i = j
            if len(stack) < 2:
                return None
            group = stack.pop()
            for el, c in group.items():
                stack[-1][el] = stack[-1].get(el, 0) + c * mult
        elif ch.isupper():
            j = i + 1
            if j < n and s[j].islower():
                j += 1
            sym = s[i:j]
            if sym not in PERIODIC:
                return None
            i = j
            j = i
            while j < n and s[j].isdigit():
                j += 1
            cnt = int(s[i:j]) if j > i else 1
            i = j
            stack[-1][sym] = stack[-1].get(sym, 0) + cnt
        else:
            return None
    if len(stack) != 1:
        return None
    counts = {k: v for k, v in counts.items() if v > 0}
    return counts or None


def formula_atom_count(formula: str) -> int:
    counts = parse_formula(formula)
    return sum(counts.values()) if counts else 0


_SUBSCRIPTS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def pretty_formula(formula: str) -> str:
    """'C6H12O6' -> 'C₆H₁₂O₆' (subscript the digits) for display strings."""
    return re.sub(r"\d+", lambda m: m.group(0).translate(_SUBSCRIPTS), formula)


# --------------------------------------------------------------------------- #
# Equation parsing + balancing
# --------------------------------------------------------------------------- #

_ARROW_RE = re.compile(r"\s*(=+>|-+>|→|⟶|⇌|=)\s*")


def parse_equation(text: str):
    """'2H2 + O2 -> 2H2O' -> (reactants, products) as [(coeff, formula), ...]
    with any existing coefficients stripped to 1 (we re-balance). Returns None
    if the text isn't a two-sided reaction with valid species on both sides."""
    if not text:
        return None
    parts = _ARROW_RE.split(text.strip(), maxsplit=1)
    if len(parts) < 3:
        return None
    left, right = parts[0], parts[-1]

    def _species(side: str):
        out = []
        for chunk in side.split("+"):
            chunk = chunk.strip()
            if not chunk:
                continue
            # Drop non-species reaction terms sometimes written in equations.
            if chunk.lower() in {"heat", "energy", "light", "δ", "delta"}:
                continue
            # Strip a leading stoichiometric coefficient ("2H2O" / "2 H2O").
            m = re.match(r"^(\d+)\s*([A-Za-z(].*)$", chunk)
            formula = m.group(2).strip() if m else chunk
            if parse_formula(formula) is None:
                return None
            out.append(formula)
        return out or None

    r = _species(left)
    p = _species(right)
    if not r or not p:
        return None
    return r, p


def _rref(matrix: list[list[Fraction]]):
    """Reduced row echelon form (in place copy) -> (rref, pivot_columns)."""
    M = [row[:] for row in matrix]
    rows = len(M)
    cols = len(M[0]) if rows else 0
    pivots = []
    r = 0
    for c in range(cols):
        pivot = next((i for i in range(r, rows) if M[i][c] != 0), None)
        if pivot is None:
            continue
        M[r], M[pivot] = M[pivot], M[r]
        inv = M[r][c]
        M[r] = [x / inv for x in M[r]]
        for i in range(rows):
            if i != r and M[i][c] != 0:
                f = M[i][c]
                M[i] = [a - f * b for a, b in zip(M[i], M[r])]
        pivots.append(c)
        r += 1
        if r == rows:
            break
    return M, pivots


def balance_equation(reactants: list[str], products: list[str]):
    """Return integer coefficients [r1.., p1..] balancing the reaction, or None.

    Sets up element conservation A·x = 0 (reactants +, products −), finds the
    1-D rational null space, and scales to the smallest positive integers.
    None if it can't be balanced uniquely (no solution / multiple independent
    reactions / a non-positive coefficient)."""
    species = reactants + products
    n = len(species)
    if n < 2:
        return None
    comps = [parse_formula(f) for f in species]
    if any(c is None for c in comps):
        return None
    elements = sorted({e for c in comps for e in c})
    # Element-composition matrix: row per element, col per species.
    A: list[list[Fraction]] = []
    for el in elements:
        row = []
        for idx, c in enumerate(comps):
            val = c.get(el, 0)
            row.append(Fraction(val if idx < len(reactants) else -val))
        A.append(row)

    rref, pivots = _rref(A)
    free = [c for c in range(n) if c not in pivots]
    # A unique balance needs exactly one free variable (1-D null space).
    if len(free) != 1:
        return None
    fcol = free[0]
    x = [Fraction(0)] * n
    x[fcol] = Fraction(1)
    for ri, pc in enumerate(pivots):
        # pivot var = -sum(coeff*free) ; only the single free col contributes.
        x[pc] = -rref[ri][fcol]

    denom_lcm = 1
    for v in x:
        denom_lcm = denom_lcm * v.denominator // math.gcd(denom_lcm, v.denominator)
    ints = [int(v * denom_lcm) for v in x]
    g = 0
    for v in ints:
        g = math.gcd(g, abs(v))
    if g == 0:
        return None
    ints = [v // g for v in ints]
    if all(v <= 0 for v in ints):
        ints = [-v for v in ints]
    if any(v <= 0 for v in ints):
        return None
    return ints


# --------------------------------------------------------------------------- #
# VSEPR geometry (single-centre hydride / halide molecules)
# --------------------------------------------------------------------------- #

def _u(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / n for c in v]


def _tetra():
    return [_u(v) for v in ([1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1])]


def _trig_planar():
    return [[math.cos(a), math.sin(a), 0.0]
            for a in (0.0, 2 * math.pi / 3, 4 * math.pi / 3)]


def _tbp():
    eq = [[math.cos(a), 0.0, math.sin(a)]
          for a in (0.0, 2 * math.pi / 3, 4 * math.pi / 3)]
    return [[0, 1, 0], [0, -1, 0]] + eq  # 2 axial + 3 equatorial


def _octa():
    return [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]]


# (steric_number, lone_pairs) -> bonding direction unit vectors. Lone pairs are
# placed in the positions VSEPR predicts; only the bonding directions remain.
def _geometry(sn: int, lp: int):
    if sn == 2:
        return [[1, 0, 0], [-1, 0, 0]], "linear"
    if sn == 3:
        tri = _trig_planar()
        if lp == 0:
            return tri, "trigonal planar"
        if lp == 1:
            return [tri[1], tri[2]], "bent"
    if sn == 4:
        tet = _tetra()
        if lp == 0:
            return tet, "tetrahedral"
        if lp == 1:
            return tet[1:], "trigonal pyramidal"
        if lp == 2:
            return [tet[1], tet[2]], "bent"
    if sn == 5:
        t = _tbp()  # [ax+, ax-, eq0, eq1, eq2]
        if lp == 0:
            return t, "trigonal bipyramidal"
        if lp == 1:
            return [t[0], t[1], t[3], t[4]], "seesaw"
        if lp == 2:
            return [t[0], t[1], t[2]], "T-shaped"
        if lp == 3:
            return [t[0], t[1]], "linear"
    if sn == 6:
        o = _octa()
        if lp == 0:
            return o, "octahedral"
        if lp == 1:
            return o[:5], "square pyramidal"
        if lp == 2:
            return [o[0], o[1], o[4], o[5]], "square planar"
    return None, None


def vsepr_molecule(formula: str):
    """Build a {atoms, bonds, shape} for a single-centre hydride/halide molecule,
    or None when the formula isn't of that form (then library/generative handles
    it). Central atom = the one element that is not H or a halogen, count 1."""
    counts = parse_formula(formula)
    if not counts:
        return None
    non_terminal = [e for e in counts if e not in _TERMINALS]
    if len(non_terminal) != 1 or counts[non_terminal[0]] != 1:
        return None
    central = non_terminal[0]
    ve = valence_electrons(central)
    if ve is None:
        return None
    terminals: list[str] = []
    for el, c in counts.items():
        if el != central:
            terminals.extend([el] * c)
    n = len(terminals)
    if n < 2:
        return None
    lone2 = ve - n
    if lone2 < 0 or lone2 % 2 != 0:
        return None
    lp = lone2 // 2
    sn = n + lp
    dirs, shape = _geometry(sn, lp)
    if dirs is None or len(dirs) != n:
        return None

    # Heavier terminals first so they land on the more spread-out positions
    # (purely cosmetic; chemistry is symmetric for identical terminals).
    terminals.sort(key=lambda e: -covalent_radius(e))
    atoms = [{"e": central, "p": [0.0, 0.0, 0.0]}]
    bonds = []
    rc = covalent_radius(central)
    for k, d in enumerate(dirs):
        el = terminals[k]
        length = rc + covalent_radius(el)
        d = _u(d)
        atoms.append({"e": el, "p": [d[0] * length, d[1] * length, d[2] * length]})
        bonds.append([0, k + 1, 1])
    return {"atoms": atoms, "bonds": bonds, "shape": shape}


# --------------------------------------------------------------------------- #
# Canonical formula (Hill system) — order-independent library keys
# --------------------------------------------------------------------------- #

_HILL_ORDER = ["C", "H"]


def _canonical_formula(counts: dict) -> str:
    """Hill system: C first, H second, then the rest alphabetical."""
    parts = []
    for el in _HILL_ORDER:
        if el in counts:
            parts.append(el + (str(counts[el]) if counts[el] > 1 else ""))
    for el in sorted(k for k in counts if k not in _HILL_ORDER):
        parts.append(el + (str(counts[el]) if counts[el] > 1 else ""))
    return "".join(parts)


def _canon(formula: str) -> str:
    counts = parse_formula(formula)
    return _canonical_formula(counts) if counts else formula


def _shape_name(formula: str, shape) -> str:
    return f"{pretty_formula(formula)} — {shape}" if shape else pretty_formula(formula)


# --------------------------------------------------------------------------- #
# Curated molecule library (correct geometry for non-VSEPR / named molecules)
# --------------------------------------------------------------------------- #

def _diatomic(a: str, b: str, order: int = 1, length: float | None = None):
    if length is None:
        length = covalent_radius(a) + covalent_radius(b)
    return {
        "atoms": [{"e": a, "p": [-length / 2, 0, 0]},
                  {"e": b, "p": [length / 2, 0, 0]}],
        "bonds": [[0, 1, order]],
    }


def _co2():
    d = 1.16
    return {
        "atoms": [{"e": "C", "p": [0, 0, 0]},
                  {"e": "O", "p": [-d, 0, 0]},
                  {"e": "O", "p": [d, 0, 0]}],
        "bonds": [[0, 1, 2], [0, 2, 2]],
    }


def _benzene():
    R = 1.39
    Rh = R + 1.09  # C–H ~1.09 Å outward
    atoms, bonds = [], []
    for i in range(6):
        a = i * math.pi / 3
        atoms.append({"e": "C", "p": [R * math.cos(a), R * math.sin(a), 0]})
    for i in range(6):
        a = i * math.pi / 3
        atoms.append({"e": "H", "p": [Rh * math.cos(a), Rh * math.sin(a), 0]})
    for i in range(6):
        bonds.append([i, (i + 1) % 6, 2 if i % 2 == 0 else 1])  # kekulé
        bonds.append([i, i + 6, 1])
    return {"atoms": atoms, "bonds": bonds}


def _bent_triatomic(center, outer, angle_deg, bond_len, order):
    half = math.radians(angle_deg) / 2
    dx = bond_len * math.sin(half)
    dy = bond_len * math.cos(half)
    return {
        "atoms": [{"e": center, "p": [0, 0, 0]},
                  {"e": outer, "p": [-dx, -dy, 0]},
                  {"e": outer, "p": [dx, -dy, 0]}],
        "bonds": [[0, 1, order], [0, 2, order]],
    }


# Seed library — correct geometry, computed (not hand-typed) where possible. The
# workflow-generated chemistry_molecules_generated.json is merged on top of this.
# Keys here are human-readable formulas; they're re-keyed by canonical (Hill)
# formula at registration so lookup is order-independent.
def _seed_library() -> dict:
    return {
        "H2": {**_diatomic("H", "H", 1, 0.74), "name": "Hydrogen (H₂)",
               "names": ["hydrogen", "dihydrogen"]},
        "O2": {**_diatomic("O", "O", 2, 1.21), "name": "Oxygen (O₂)",
               "names": ["oxygen", "dioxygen"]},
        "N2": {**_diatomic("N", "N", 3, 1.10), "name": "Nitrogen (N₂)",
               "names": ["nitrogen", "dinitrogen"]},
        "Cl2": {**_diatomic("Cl", "Cl", 1, 1.99), "name": "Chlorine (Cl₂)",
                "names": ["chlorine"]},
        "HCl": {**_diatomic("H", "Cl", 1, 1.27), "name": "Hydrogen chloride (HCl)",
                "names": ["hydrogen chloride", "hydrochloric acid"]},
        "HF": {**_diatomic("H", "F", 1, 0.92), "name": "Hydrogen fluoride (HF)",
               "names": ["hydrogen fluoride"]},
        "CO": {**_diatomic("C", "O", 3, 1.13), "name": "Carbon monoxide (CO)",
               "names": ["carbon monoxide"]},
        "NaCl": {**_diatomic("Na", "Cl", 1, 2.36), "name": "Sodium chloride (NaCl)",
                 "names": ["sodium chloride", "table salt", "halite"]},
        "CO2": {**_co2(), "name": "Carbon dioxide (CO₂)",
                "names": ["carbon dioxide", "dry ice"]},
        "SO2": {**_bent_triatomic("S", "O", 119.0, 1.43, 2), "name": "Sulfur dioxide (SO₂)",
                "names": ["sulfur dioxide", "sulphur dioxide"]},
        "O3": {**_bent_triatomic("O", "O", 117.0, 1.28, 1), "name": "Ozone (O₃)",
               "names": ["ozone"]},
        "C6H6": {**_benzene(), "name": "Benzene (C₆H₆)",
                 "names": ["benzene"]},
    }


# Common molecule names → formula, so a bare "methane" / "ammonia" resolves
# (via the library or the VSEPR generator) even when not in the curated library.
_COMMON_NAMES = {
    "methane": "CH4", "ammonia": "NH3", "water": "H2O",
    "carbon dioxide": "CO2", "carbon monoxide": "CO", "benzene": "C6H6",
    "ozone": "O3", "sulfur dioxide": "SO2", "sulphur dioxide": "SO2",
    "sulfur hexafluoride": "SF6", "phosphorus pentachloride": "PCl5",
    "boron trifluoride": "BF3", "hydrogen sulfide": "H2S",
    "methanol": "CH4O", "ethanol": "C2H6O", "glucose": "C6H12O6",
    "acetic acid": "C2H4O2", "ethane": "C2H6", "ethene": "C2H4",
    "ethyne": "C2H2", "acetylene": "C2H2", "ethylene": "C2H4",
    "hydrogen peroxide": "H2O2", "ammonium": "NH4",
    "silane": "SiH4", "phosphine": "PH3", "sodium chloride": "NaCl",
    "table salt": "NaCl",
}

# Ambiguous everyday/physics words — only treat as a molecule with an explicit
# structure cue, so we don't hijack "water waves" or "oxygen tank".
_AMBIGUOUS_NAMES = {"water", "oxygen", "nitrogen", "hydrogen", "salt", "ozone"}

MOLECULES: dict = {}
_NAME_INDEX: dict = {}


def _register(disp_formula: str, mol: dict):
    canon = _canon(disp_formula)
    mol = dict(mol)
    mol.setdefault("formula", disp_formula)
    MOLECULES[canon] = mol


def _index_names():
    _NAME_INDEX.clear()
    for canon, mol in MOLECULES.items():
        _NAME_INDEX[canon.lower()] = canon
        disp = mol.get("formula", canon)
        _NAME_INDEX[disp.lower()] = canon
        for nm in mol.get("names", []):
            _NAME_INDEX[str(nm).strip().lower()] = canon


def _load_generated(path: str = "chemistry_molecules_generated.json"):
    """Merge a workflow-generated, chemically-verified molecule library."""
    MOLECULES.clear()
    for disp, mol in _seed_library().items():
        _register(disp, mol)
    full = path if os.path.isabs(path) else os.path.join(os.path.dirname(__file__), path)
    try:
        with open(full, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        _index_names()
        return
    items = data.get("molecules", data) if isinstance(data, dict) else data
    if isinstance(items, list):
        for mol in items:
            f = mol.get("formula")
            if f and isinstance(mol.get("atoms"), list) and mol.get("bonds") is not None:
                _register(f, mol)
    _index_names()


_load_generated()


# --------------------------------------------------------------------------- #
# Molecule lookup
# --------------------------------------------------------------------------- #

def _normalize_geometry(mol: dict) -> dict:
    """Center the molecule and scale to a fixed bounding radius so every
    structure frames the same on screen. Attaches per-atom color/radius/label."""
    atoms = mol["atoms"]
    cx = sum(a["p"][0] for a in atoms) / len(atoms)
    cy = sum(a["p"][1] for a in atoms) / len(atoms)
    cz = sum(a["p"][2] for a in atoms) / len(atoms)
    maxr = 0.0
    for a in atoms:
        p = a["p"]
        d = math.sqrt((p[0] - cx) ** 2 + (p[1] - cy) ** 2 + (p[2] - cz) ** 2)
        maxr = max(maxr, d)
    k = (3.0 / maxr) if maxr > 1e-6 else 1.0
    out_atoms = []
    for a in atoms:
        p = a["p"]
        col = element_color(a["e"])
        out_atoms.append({
            "e": a["e"],
            "p": [round((p[0] - cx) * k, 4), round((p[1] - cy) * k, 4),
                  round((p[2] - cz) * k, 4)],
            "c": col,
            "lc": _label_color(col),
            "r": round(max(0.28, covalent_radius(a["e"]) * 0.42) * k, 4),
        })
    bonds = [[int(b[0]), int(b[1]), int(b[2]) if len(b) > 2 else 1]
             for b in mol["bonds"]]
    return {"atoms": out_atoms, "bonds": bonds}


def _library_geo(canon: str, display_override: str | None = None):
    mol = MOLECULES[canon]
    geo = _normalize_geometry(mol)
    geo["formula"] = display_override or mol.get("formula", canon)
    geo["name"] = mol.get("name", pretty_formula(geo["formula"]))
    geo["shape"] = mol.get("shape", "")
    return geo


def lookup_molecule(query: str):
    """Resolve a formula or name to a normalized renderable molecule, or None.

    Tries the curated library first (by canonical formula then name), then the
    VSEPR generator for single-centre hydride/halide formulas."""
    if not query:
        return None
    q = query.strip()
    counts = parse_formula(q)
    if counts:
        canon = _canonical_formula(counts)
        if canon in MOLECULES:
            return _library_geo(canon)
        v = vsepr_molecule(q)
        if v:
            geo = _normalize_geometry(v)
            geo["formula"] = q  # show the formula as the user typed it
            geo["name"] = _shape_name(q, v.get("shape"))
            geo["shape"] = v.get("shape", "")
            return geo
        return None
    key = q.lower()
    if key in _NAME_INDEX:
        return _library_geo(_NAME_INDEX[key])
    if key in _COMMON_NAMES:
        return lookup_molecule(_COMMON_NAMES[key])
    return None


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #

_CHEM_KEYWORDS = re.compile(
    r"\b(molecul\w*|compound|lewis|vsepr|ball[- ]and[- ]stick|3d\s+structure|"
    r"structure of|shape of|geometry of|bond(s|ing)?|chemical structure)\b",
    re.I,
)
_BALANCE_KEYWORDS = re.compile(r"\b(balanc\w+|stoichiometr\w+|reaction|reactants?|products?)\b", re.I)


def _looks_like_formula(token: str) -> bool:
    counts = parse_formula(token)
    if not counts:
        return False
    total = sum(counts.values())
    if total < 2:
        return False
    has_digit = bool(re.search(r"\d", token))
    multi_element = len(counts) >= 2
    return has_digit or multi_element


def _find_formula(prompt: str):
    """Pull the most formula-like token from a prompt, or None."""
    best = None
    for raw in re.split(r"[\s,;:]+", prompt.strip()):
        tok = raw.strip().strip(".?!)（）\"'")
        if not tok or not _FORMULA_TOKEN_RE.match(tok):
            continue
        if _looks_like_formula(tok):
            # Prefer the longer / more specific token.
            if best is None or len(tok) > len(best):
                best = tok
    return best


_COMMAND_PREFIX = re.compile(
    r"^\s*(please\s+)?(balance|solve|complete|finish)\b"
    r"(\s+(the|this))?(\s+(equation|reaction|chemical\s+equation))?\s*[:\-]?\s*",
    re.I,
)


def _bare_name_triggers():
    """Multi-letter molecule names safe to fire on without a structure cue."""
    names = set(k for k in _NAME_INDEX if k.isalpha() and len(k) >= 4)
    names |= set(k for k in _COMMON_NAMES if all(p.isalpha() for p in k.split()) and len(k) >= 4)
    return names - _AMBIGUOUS_NAMES


def detect_chemistry(prompt: str):
    """Classify a prompt -> ('balance', (reactants, products)) |
    ('molecule', query) | None. Conservative: only fires on an unambiguous
    chemical formula, a reaction, or a recognized molecule name."""
    if not prompt:
        return None
    text = prompt.strip()
    # Drop a leading command phrase ("balance the equation: ...") so the reaction
    # parser sees the species, not the verb.
    reaction_text = _COMMAND_PREFIX.sub("", text)

    # Reaction first — an arrow with valid species on both sides is unambiguous.
    eq = parse_equation(reaction_text)
    if eq is not None:
        return ("balance", eq)

    # Bare formula (or formula + words): "CH4", "draw C6H12O6", "H2O structure".
    formula = _find_formula(text)
    if formula is not None:
        return ("molecule", formula)

    low = text.lower()
    # A recognized molecule name. Unambiguous names ("benzene", "methane") fire
    # on their own; everyday/physics words ("water", "oxygen") need a structure
    # cue so we don't hijack "water waves" or "liquid oxygen".
    if _CHEM_KEYWORDS.search(text):
        candidates = set(_NAME_INDEX) | set(_COMMON_NAMES)  # incl. ambiguous
    else:
        candidates = _bare_name_triggers()
    # Match the longest name first ("carbon dioxide" before "carbon monoxide").
    for name in sorted(candidates, key=len, reverse=True):
        if len(name) >= 4 and re.search(r"\b" + re.escape(name) + r"\b", low):
            return ("molecule", name)
    return None


# --------------------------------------------------------------------------- #
# Scene code builders (emit a bare scene(ctx, t) body)
# --------------------------------------------------------------------------- #

def _molecule_code(mol: dict) -> str:
    data = json.dumps({"atoms": mol["atoms"], "bonds": mol["bonds"],
                       "name": mol["name"], "formula": pretty_formula(mol["formula"])},
                      ensure_ascii=False)
    return (
        "H.background();\n"
        f"const MOL = {data};\n"
        "const w = H.W, hgt = H.H;\n"
        "const cam = H.cam3d({ scale: 46, dist: 15, pitch: -0.16, cy: hgt * 0.54 });\n"
        "cam.yaw = 0.45 * t;\n"
        "const proj = MOL.atoms.map(function (a) { return cam.project(a.p); });\n"
        "function bond(i, j, order) {\n"
        "  const p1 = proj[i], p2 = proj[j];\n"
        "  let dx = p2.x - p1.x, dy = p2.y - p1.y;\n"
        "  const len = Math.sqrt(dx * dx + dy * dy) || 1;\n"
        "  const ux = -dy / len, uy = dx / len;\n"
        "  const gap = 3.4;\n"
        "  const offs = order >= 3 ? [-gap * 1.5, 0, gap * 1.5]\n"
        "    : order === 2 ? [-gap, gap] : [0];\n"
        "  for (let k = 0; k < offs.length; k++) {\n"
        "    const o = offs[k];\n"
        "    H.line(p1.x + ux * o, p1.y + uy * o, p2.x + ux * o, p2.y + uy * o,\n"
        "      { color: H.colors.sub, width: 3 });\n"
        "  }\n"
        "}\n"
        "for (let b = 0; b < MOL.bonds.length; b++) {\n"
        "  bond(MOL.bonds[b][0], MOL.bonds[b][1], MOL.bonds[b][2]);\n"
        "}\n"
        "const order = MOL.atoms.map(function (a, idx) {\n"
        "  return { idx: idx, depth: proj[idx].depth };\n"
        "}).sort(function (u, v) { return v.depth - u.depth; });\n"
        "for (let s = 0; s < order.length; s++) {\n"
        "  const a = MOL.atoms[order[s].idx];\n"
        "  cam.sphere(a.p, a.r, { color: a.c, stroke: 'rgba(6,8,18,0.45)', width: 1 });\n"
        "  const q = proj[order[s].idx];\n"
        "  if (a.e !== 'H') H.text(a.e, q.x, q.y,\n"
        "    { color: a.lc, size: 12, weight: 700, align: 'center', baseline: 'middle' });\n"
        "}\n"
        "H.text(MOL.name, 24, 30, { color: H.colors.ink, size: 18, weight: 700 });\n"
        "H.text(MOL.formula + '  ·  drag to orbit, scroll to zoom', 24, 52,\n"
        "  { color: H.colors.sub, size: 13 });\n"
        "H.legend(MOL.atoms.filter(function (a, i, arr) {\n"
        "  return arr.findIndex(function (b) { return b.e === a.e; }) === i;\n"
        "}).map(function (a) { return { label: a.e, color: a.c }; }), 24, hgt - 28);\n"
    )


def _element_chip_color(el: str) -> str:
    return element_color(el)


def _balance_code(reactants, products, coeffs) -> str:
    nr = len(reactants)
    rc = coeffs[:nr]
    pc = coeffs[nr:]
    comps = [parse_formula(f) for f in reactants + products]
    elements = sorted({e for c in comps for e in c})
    tally = []
    for el in elements:
        left = sum(rc[i] * comps[i].get(el, 0) for i in range(nr))
        right = sum(pc[i] * comps[nr + i].get(el, 0) for i in range(len(products)))
        tally.append({"el": el, "left": left, "right": right, "color": element_color(el)})

    def _side(formulas, cs):
        return [{"coef": cs[i], "formula": pretty_formula(formulas[i])}
                for i in range(len(formulas))]

    def _eqstr(formulas, cs):
        toks = []
        for i, f in enumerate(formulas):
            pre = (str(cs[i]) + " ") if cs[i] != 1 else ""
            toks.append(pre + pretty_formula(f))
        return "  +  ".join(toks)

    balanced = _eqstr(reactants, rc) + "   →   " + _eqstr(products, pc)
    data = json.dumps({
        "reactants": _side(reactants, rc),
        "products": _side(products, pc),
        "tally": tally,
        "balanced": balanced,
    }, ensure_ascii=False)

    return (
        "H.background();\n"
        f"const EQ = {data};\n"
        "const w = H.W, hgt = H.H;\n"
        "H.text('Balancing the equation', 24, 30,\n"
        "  { color: H.colors.ink, size: 18, weight: 700 });\n"
        "H.text('Coefficients chosen so every element is conserved (same count on both sides).',\n"
        "  24, 52, { color: H.colors.sub, size: 13 });\n"
        "// Reactant cards (left) -> arrow -> product cards (right). The layout\n"
        "// scales to the canvas width so even a 6-species reaction fits.\n"
        "const nL = EQ.reactants.length, nR = EQ.products.length;\n"
        "const nCards = nL + nR;\n"
        "const margin = 34, arrowGap = 64;\n"
        "const gapX = Math.min(124, (w - 2 * margin - arrowGap) / Math.max(1, nCards));\n"
        "const cw = Math.min(100, gapX * 0.82), ch = 50;\n"
        "const fs = Math.max(11, Math.min(20, cw * 0.21));\n"
        "const midY = hgt * 0.40;\n"
        "function card(cx, item, accent) {\n"
        "  H.rect(cx - cw / 2, midY - ch / 2, cw, ch,\n"
        "    { fill: 'rgba(124,196,255,0.08)', stroke: accent, width: 1.5, radius: 10 });\n"
        "  H.text(item.formula, cx, midY + 3,\n"
        "    { color: H.colors.ink, size: fs, weight: 700, align: 'center', baseline: 'middle' });\n"
        "  if (item.coef !== 1) {\n"
        "    H.circle(cx - cw / 2, midY - ch / 2, 13, { fill: accent });\n"
        "    H.text(String(item.coef), cx - cw / 2, midY - ch / 2 + 1,\n"
        "      { color: '#0c1020', size: 13, weight: 700, align: 'center', baseline: 'middle' });\n"
        "  }\n"
        "}\n"
        "const totalW = nCards * gapX + arrowGap;\n"
        "const start = w / 2 - totalW / 2 + gapX / 2;\n"
        "for (let i = 0; i < nL; i++) {\n"
        "  const cx = start + i * gapX;\n"
        "  card(cx, EQ.reactants[i], H.colors.accent);\n"
        "  if (i < nL - 1) H.text('+', cx + gapX / 2, midY,\n"
        "    { color: H.colors.sub, size: 20, align: 'center', baseline: 'middle' });\n"
        "}\n"
        "const px0 = start + nL * gapX + arrowGap;\n"
        "const ax0 = start + (nL - 1) * gapX + cw / 2 + 6, ax1 = px0 - cw / 2 - 6;\n"
        "H.arrow(ax0, midY, ax1, midY, { color: H.colors.good, width: 3 });\n"
        "// A glow travels along the arrow to show the reaction proceeding.\n"
        "const gx = ax0 + (ax1 - ax0) * (0.5 + 0.5 * Math.sin(t * 1.6));\n"
        "H.circle(gx, midY, 4, { fill: H.colors.yellow });\n"
        "for (let i = 0; i < nR; i++) {\n"
        "  const cx = px0 + i * gapX;\n"
        "  card(cx, EQ.products[i], H.colors.good);\n"
        "  if (i < nR - 1) H.text('+', cx + gapX / 2, midY,\n"
        "    { color: H.colors.sub, size: 20, align: 'center', baseline: 'middle' });\n"
        "}\n"
        "// Balanced equation, one clean line.\n"
        "H.text(EQ.balanced, w / 2, hgt * 0.62,\n"
        "  { color: H.colors.accent, size: 18, weight: 700, align: 'center', baseline: 'middle' });\n"
        "// Per-element conservation tally, revealed one row at a time.\n"
        "const rows = EQ.tally.length;\n"
        "const ty0 = hgt * 0.72, rowH = 24;\n"
        "const tx = Math.max(40, w / 2 - 160);\n"
        "const reveal = Math.floor((t * 1.1) % (rows + 2));\n"
        "H.text('Atom balance', tx, ty0 - 22,\n"
        "  { color: H.colors.sub, size: 12, weight: 700 });\n"
        "for (let i = 0; i < rows; i++) {\n"
        "  const r = EQ.tally[i];\n"
        "  const yy = ty0 + i * rowH;\n"
        "  const on = i <= reveal;\n"
        "  H.circle(tx, yy, 7, { fill: on ? r.color : H.colors.grid });\n"
        "  H.text(r.el, tx, yy + 1,\n"
        "    { color: '#0c1020', size: 10, weight: 700, align: 'center', baseline: 'middle' });\n"
        "  H.text(r.left + ' = ' + r.right + (on ? '   ✓' : ''), tx + 18, yy + 1,\n"
        "    { color: on ? H.colors.good : H.colors.sub, size: 14, baseline: 'middle' });\n"
        "}\n"
    )


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def chemistry_scene(prompt: str):
    """Return a scene-content dict (title/tag/dimension/equation/summary/bullets/
    student_prompts/code/kind) for a chemistry prompt, or None to fall through to
    the normal demo/library/generative path. `code` is RAW — the caller should
    run it through sanitize_code (mirrors the demo/library shapers)."""
    hit = detect_chemistry(prompt)
    if hit is None:
        return None
    kind, payload = hit

    if kind == "molecule":
        mol = lookup_molecule(payload)
        if mol is None:
            return None
        shape = mol.get("shape", "")
        summary = (
            f"3D ball-and-stick structure of {mol['name']}"
            + (f", a {shape} molecule." if shape else ".")
            + " Atoms are colored by element (CPK); sticks are bonds. Drag to orbit."
        )
        bullets = [
            "Each ball is an atom (colored by element); each stick is a bond.",
            "Double and triple bonds are drawn as 2 or 3 parallel sticks.",
            (f"The arrangement is {shape} — set by how electron pairs spread out (VSEPR)."
             if shape else "The 3D arrangement reflects how the atoms bond in space."),
        ]
        return {
            "title": mol["name"],
            "tag": "Chemistry",
            "dimension": "3D",
            "equation": mol["formula"],
            "summary": summary,
            "bullets": bullets,
            "student_prompts": [
                f"Why does {mol['formula']} take this shape?",
                "What are the bond angles in this molecule?",
                "How do lone pairs change the geometry?",
            ],
            "code": _molecule_code(mol),
            "kind": "molecule",
        }

    if kind == "balance":
        reactants, products = payload
        coeffs = balance_equation(reactants, products)
        if coeffs is None:
            return None
        nr = len(reactants)

        def _eq(formulas, cs):
            toks = []
            for i, f in enumerate(formulas):
                pre = (str(cs[i]) + " ") if cs[i] != 1 else ""
                toks.append(pre + f)
            return " + ".join(toks)

        balanced_plain = _eq(reactants, coeffs[:nr]) + " -> " + _eq(products, coeffs[nr:])
        return {
            "title": "Balanced chemical equation",
            "tag": "Chemistry",
            "dimension": "2D",
            "equation": balanced_plain,
            "summary": (
                "The reaction balanced so atoms of every element are conserved. "
                "Reactants (left) combine in the shown ratio to give the products (right); "
                "the tally proves each element's count matches on both sides."
            ),
            "bullets": [
                "Coefficients are the smallest whole numbers that conserve every atom.",
                "Atoms are never created or destroyed — only rearranged (conservation of mass).",
                "The badge on each card is how many of that molecule the balance requires.",
            ],
            "student_prompts": [
                "How do you find balancing coefficients systematically?",
                "Why must the atom counts match on both sides?",
                "What is the mole ratio between the reactants here?",
            ],
            "code": _balance_code(reactants, products, coeffs),
            "kind": "balance",
        }
    return None
