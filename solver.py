"""Step-by-step worked-solution engine for VisualLM.

When a prompt is a SPECIFIC problem (actual numbers + labels) rather than a topic
name, this produces an animated *slide deck* that walks through solving it
gradually, with the student's own numbers — the "teach the process, show every
step" mode that complements the topic demos (which teach the general method).

First solver: triangles. Parse the given sides/angles, classify the case
(SAS / SSS / ASA / AAS / SSA), solve every unknown (handling the ambiguous SSA
case that yields 0, 1, or 2 triangles), and emit a scene that steps through the
worked solution — drawing the triangle to scale and revealing each computation.

Pure standard library. The emitted `code` is a bare scene(ctx, t) body using the
worker's `H` helpers; slides auto-advance over time and loop.
"""

from __future__ import annotations

import json
import math
import re

# --------------------------------------------------------------------------- #
# Parsing a triangle problem
# --------------------------------------------------------------------------- #

# "angle A = 40", "angle of a = 40", "A = 40 deg"  -> angle (key upper-case)
# The \b before "angle" stops "tri{angle}", "rect{angle}" from matching.
_ANGLE_RE = re.compile(r"\bangle\s+(?:of\s+)?([abcABC])\s*=\s*(-?\d+(?:\.\d+)?)", re.I)
# "side a = 12", "a = 12", "b =14"  -> side (key lower-case)
_SIDE_RE = re.compile(r"(?:side\s+)?\b([abcABC])\s*=\s*(-?\d+(?:\.\d+)?)")


def parse_triangle(prompt: str):
    """Extract given triangle data -> {'a':..,'A':..} (sides lower, angles upper),
    or None if it isn't a numeric triangle problem. Angles are in degrees."""
    if not prompt:
        return None
    text = prompt.strip()
    given: dict[str, float] = {}
    consumed = []  # (start, end) spans already taken by an angle match

    # Angles first (they carry the word "angle", so they're unambiguous).
    for m in _ANGLE_RE.finditer(text):
        given[m.group(1).upper()] = float(m.group(2))
        consumed.append((m.start(), m.end()))

    # Sides: bare "x = n". Skip spans already consumed by an angle phrase, and
    # skip an uppercase letter that was clearly meant as an angle name.
    for m in _SIDE_RE.finditer(text):
        if any(s <= m.start() < e for (s, e) in consumed):
            continue
        key = m.group(1)
        val = float(m.group(2))
        if key.isupper():
            given.setdefault(key, val)            # uppercase bare -> angle
        else:
            given.setdefault(key.lower(), val)    # lowercase -> side
    # Need at least 3 givens, at least one of which is a side, to fix a triangle.
    sides = [k for k in given if k in ("a", "b", "c")]
    if len(given) < 3 or not sides:
        return None
    # Sanity: positive sides, angles in (0,180).
    for k, v in given.items():
        if k in ("a", "b", "c") and v <= 0:
            return None
        if k in ("A", "B", "C") and not (0 < v < 180):
            return None
    angsum = sum(v for k, v in given.items() if k in ("A", "B", "C"))
    if angsum >= 180:
        return None
    return given


# --------------------------------------------------------------------------- #
# Solving
# --------------------------------------------------------------------------- #

def _classify(given: dict):
    sides = sorted(k for k in given if k in ("a", "b", "c"))
    angles = sorted(k for k in given if k in ("A", "B", "C"))
    ns, na = len(sides), len(angles)
    if ns == 3:
        return "SSS"
    if ns == 2 and na == 1:
        # SAS if the angle is the one BETWEEN the two sides, else SSA.
        opp = {"a": "A", "b": "B", "c": "C"}
        included = {frozenset(("a", "b")): "C", frozenset(("a", "c")): "B", frozenset(("b", "c")): "A"}
        ang = angles[0]
        return "SAS" if ang == included[frozenset(sides)] else "SSA"
    if ns == 1 and na == 2:
        return "ASA_AAS"
    return None


def _rad(d):
    return d * math.pi / 180.0


def _deg(r):
    return r * 180.0 / math.pi


def solve_triangle(given: dict):
    """Return {'case', 'solutions':[{a,b,c,A,B,C}], 'steps':[...]} or None.

    steps: list of {title, formula, detail} describing the worked solution.
    For the ambiguous SSA case, solutions may hold two triangles."""
    case = _classify(given)
    if case is None:
        return None
    g = dict(given)
    steps = []

    def sol_from(a, b, c, A, B, C):
        return {"a": a, "b": b, "c": c, "A": A, "B": B, "C": C}

    if case == "SSS":
        a, b, c = g["a"], g["b"], g["c"]
        if a + b <= c or a + c <= b or b + c <= a:
            return None  # not a valid triangle
        # Law of cosines for each angle.
        A = _deg(math.acos(max(-1, min(1, (b * b + c * c - a * a) / (2 * b * c)))))
        B = _deg(math.acos(max(-1, min(1, (a * a + c * c - b * b) / (2 * a * c)))))
        C = 180 - A - B
        steps = [
            {"title": "What's given", "formula": f"a = {a:g},  b = {b:g},  c = {c:g}",
             "detail": "Three sides (SSS). To find an angle, use the Law of Cosines."},
            {"title": "Find angle A (Law of Cosines)", "formula": "cos A = (b² + c² − a²) / (2bc)",
             "detail": f"cos A = ({b:g}² + {c:g}² − {a:g}²) / (2·{b:g}·{c:g})  →  A = {A:.1f}°"},
            {"title": "Find angle B (Law of Cosines)", "formula": "cos B = (a² + c² − b²) / (2ac)",
             "detail": f"B = {B:.1f}°"},
            {"title": "Find angle C", "formula": "C = 180° − A − B",
             "detail": f"C = 180° − {A:.1f}° − {B:.1f}° = {C:.1f}°"},
        ]
        return {"case": case, "solutions": [sol_from(a, b, c, A, B, C)], "steps": steps}

    if case == "SAS":
        # two sides + included angle -> third side via Law of Cosines, then angles
        opp = {"a": "A", "b": "B", "c": "C"}
        sides = sorted(k for k in g if k in ("a", "b", "c"))
        angK = [k for k in g if k in ("A", "B", "C")][0]
        s1, s2 = sides
        thirdS = ({"a", "b", "c"} - set(sides)).pop()
        x1, x2, ang = g[s1], g[s2], g[angK]
        third = math.sqrt(x1 * x1 + x2 * x2 - 2 * x1 * x2 * math.cos(_rad(ang)))
        full = {s1: x1, s2: x2, thirdS: third}
        a, b, c = full["a"], full["b"], full["c"]
        # angle opposite s1 via law of sines (safe; third is the largest only if ang obtuse)
        # use law of cosines to avoid ambiguity
        A = _deg(math.acos(max(-1, min(1, (b * b + c * c - a * a) / (2 * b * c)))))
        B = _deg(math.acos(max(-1, min(1, (a * a + c * c - b * b) / (2 * a * c)))))
        C = 180 - A - B
        steps = [
            {"title": "What's given", "formula": f"{s1} = {x1:g},  {s2} = {x2:g},  ∠{angK} = {ang:g}°",
             "detail": "Two sides and the angle BETWEEN them (SAS). Start with the Law of Cosines."},
            {"title": f"Find side {thirdS} (Law of Cosines)", "formula": f"{thirdS}² = {s1}² + {s2}² − 2·{s1}·{s2}·cos {angK}",
             "detail": f"{thirdS} = √({x1:g}² + {x2:g}² − 2·{x1:g}·{x2:g}·cos {ang:g}°) = {third:.2f}"},
            {"title": "Find the remaining angles", "formula": "Law of Cosines (or Sines)",
             "detail": f"A = {A:.1f}°,  B = {B:.1f}°,  C = {C:.1f}°"},
            {"title": "Solved", "formula": "A + B + C = 180°",
             "detail": f"a={a:.2f}, b={b:.2f}, c={c:.2f}; A={A:.1f}°, B={B:.1f}°, C={C:.1f}°"},
        ]
        return {"case": case, "solutions": [sol_from(a, b, c, A, B, C)], "steps": steps}

    if case == "ASA_AAS":
        angles = [k for k in g if k in ("A", "B", "C")]
        sideK = [k for k in g if k in ("a", "b", "c")][0]
        a3 = {"A", "B", "C"} - set(angles)
        thirdA = a3.pop()
        A_ = g.get("A"); B_ = g.get("B"); C_ = g.get("C")
        known = {k: g[k] for k in angles}
        known[thirdA] = 180 - sum(known.values())
        A_, B_, C_ = known["A"], known["B"], known["C"]
        opp = {"a": "A", "b": "B", "c": "C"}
        # Law of sines from the known side.
        sval = g[sideK]
        ratio = sval / math.sin(_rad(known[opp[sideK]]))
        sides = {sk: ratio * math.sin(_rad(known[opp[sk]])) for sk in ("a", "b", "c")}
        a, b, c = sides["a"], sides["b"], sides["c"]
        steps = [
            {"title": "What's given", "formula": "  ".join(f"∠{k}={g[k]:g}°" for k in angles) + f",  {sideK}={sval:g}",
             "detail": "Two angles and a side (ASA/AAS). The angles fix the shape."},
            {"title": f"Find ∠{thirdA}", "formula": "A + B + C = 180°",
             "detail": f"∠{thirdA} = 180° − " + " − ".join(f"{g[k]:g}°" for k in angles) + f" = {known[thirdA]:.1f}°"},
            {"title": "Find the sides (Law of Sines)", "formula": "a/sin A = b/sin B = c/sin C",
             "detail": f"common ratio = {sideK}/sin {opp[sideK]} = {ratio:.2f}"},
            {"title": "Solved", "formula": "every side from the ratio",
             "detail": f"a={a:.2f}, b={b:.2f}, c={c:.2f}; A={A_:.1f}°, B={B_:.1f}°, C={C_:.1f}°"},
        ]
        return {"case": case, "solutions": [sol_from(a, b, c, A_, B_, C_)], "steps": steps}

    if case == "SSA":
        # two sides + a non-included angle -> ambiguous.
        opp = {"a": "A", "b": "B", "c": "C"}
        angK = [k for k in g if k in ("A", "B", "C")][0]
        ang = g[angK]
        known_side = opp_side = None
        # side opposite the known angle:
        os = {"A": "a", "B": "b", "C": "c"}[angK]
        other = [s for s in ("a", "b", "c") if s in g and s != os]
        if os not in g or not other:
            return None
        sideOpp = g[os]            # side opposite the known angle
        other_k = other[0]
        sideOther = g[other_k]     # the other given side
        # Law of sines: sin(angle opposite the OTHER side) = sideOther·sin(ang)/sideOpp
        sinX = sideOther * math.sin(_rad(ang)) / sideOpp
        otherAngK = opp[other_k]
        base_steps = [
            {"title": "What's given", "formula": f"{os} = {sideOpp:g},  {other_k} = {sideOther:g},  ∠{angK} = {ang:g}°",
             "detail": "Two sides and an angle NOT between them (SSA) — the ambiguous case. Use the Law of Sines."},
            {"title": f"Set up the Law of Sines", "formula": f"sin {otherAngK} / {other_k} = sin {angK} / {os}",
             "detail": f"sin {otherAngK} = {other_k}·sin {angK} / {os} = {sideOther:g}·sin {ang:g}° / {sideOpp:g} = {sinX:.3f}"},
        ]
        if sinX > 1 + 1e-9:
            base_steps.append({"title": "No triangle", "formula": "sin value > 1",
                               "detail": f"sin {otherAngK} = {sinX:.3f} > 1 is impossible — NO triangle exists."})
            return {"case": case, "solutions": [], "steps": base_steps, "ambiguous": True}
        sinX = max(-1, min(1, sinX))
        X1 = _deg(math.asin(sinX))
        sols = []
        for X in (X1, 180 - X1):
            if X <= 0 or ang + X >= 180:
                continue
            known = {angK: ang, otherAngK: X}
            thirdA = ({"A", "B", "C"} - set(known)).pop()
            known[thirdA] = 180 - ang - X
            ratio = sideOpp / math.sin(_rad(ang))
            sides = {sk: ratio * math.sin(_rad(known[opp[sk]])) for sk in ("a", "b", "c")}
            sols.append(sol_from(sides["a"], sides["b"], sides["c"], known["A"], known["B"], known["C"]))
        if len(sols) == 2:
            base_steps.append({"title": f"Two possible angles for ∠{otherAngK}", "formula": f"{otherAngK} = {X1:.1f}°  OR  180° − {X1:.1f}° = {180-X1:.1f}°",
                               "detail": "Both keep the angle sum under 180°, so TWO triangles fit the data."})
            s1, s2 = sols
            base_steps.append({"title": "Triangle 1", "formula": f"∠{otherAngK} = {X1:.1f}°",
                               "detail": f"A={s1['A']:.1f}°, B={s1['B']:.1f}°, C={s1['C']:.1f}°; a={s1['a']:.2f}, b={s1['b']:.2f}, c={s1['c']:.2f}"})
            base_steps.append({"title": "Triangle 2 (the other solution)", "formula": f"∠{otherAngK} = {180-X1:.1f}°",
                               "detail": f"A={s2['A']:.1f}°, B={s2['B']:.1f}°, C={s2['C']:.1f}°; a={s2['a']:.2f}, b={s2['b']:.2f}, c={s2['c']:.2f}"})
        elif len(sols) == 1:
            s1 = sols[0]
            base_steps.append({"title": f"∠{otherAngK} = {X1:.1f}°", "formula": "the obtuse option fails (angle sum ≥ 180°)",
                               "detail": "Only ONE triangle fits."})
            base_steps.append({"title": "Solved", "formula": "A + B + C = 180°",
                               "detail": f"A={s1['A']:.1f}°, B={s1['B']:.1f}°, C={s1['C']:.1f}°; a={s1['a']:.2f}, b={s1['b']:.2f}, c={s1['c']:.2f}"})
        return {"case": case, "solutions": sols, "steps": base_steps, "ambiguous": len(sols) == 2}

    return None


# --------------------------------------------------------------------------- #
# Scene: an animated step-by-step slide deck
# --------------------------------------------------------------------------- #

def _triangle_vertices(sol):
    """Place a triangle with the given side lengths at a readable scale.
    Vertex A at origin, B along +x at distance c, C found from sides b (AC) and a (BC)."""
    a, b, c = sol["a"], sol["b"], sol["c"]
    if min(a, b, c) <= 0:
        return None
    Ax, Ay = 0.0, 0.0
    Bx, By = c, 0.0
    # C: distance b from A, distance a from B.
    x = (b * b - a * a + c * c) / (2 * c) if c > 1e-9 else 0.0
    y2 = b * b - x * x
    y = math.sqrt(y2) if y2 > 0 else 0.0
    return [(Ax, Ay), (Bx, By), (x, y)]


def _solver_code(result, prompt: str) -> str:
    steps = result["steps"]
    sols = result.get("solutions", [])
    verts = _triangle_vertices(sols[0]) if sols else None
    data = json.dumps({
        "steps": steps,
        "verts": verts,
        "labels": (sols[0] if sols else None),
        "nslides": len(steps),
        "ambiguous": bool(result.get("ambiguous")),
    }, ensure_ascii=False)
    return (
        "H.background();\n"
        f"const D = {data};\n"
        "const w = H.W, hgt = H.H;\n"
        "const N = D.nslides;\n"
        "const SLIDE = 3.4;\n"
        "const k = Math.floor((t / SLIDE) % N);\n"
        "const st = D.steps[k];\n"
        "H.text('Step-by-step solution', 24, 30, { color: H.colors.ink, size: 18, weight: 700 });\n"
        "H.text('Slide ' + (k + 1) + ' of ' + N + '  ·  worked through with your numbers', 24, 52, { color: H.colors.sub, size: 13 });\n"
        "// progress dots\n"
        "for (let i = 0; i < N; i++) {\n"
        "  H.circle(24 + i * 16, 70, 5, { fill: i === k ? H.colors.accent : (i < k ? H.colors.good : H.colors.grid) });\n"
        "}\n"
        "// Draw the triangle (to scale) on the right, labels revealed as solved.\n"
        "if (D.verts) {\n"
        "  const vs = D.verts;\n"
        "  let minx = 1e9, maxx = -1e9, miny = 1e9, maxy = -1e9;\n"
        "  for (const p of vs) { minx = Math.min(minx, p[0]); maxx = Math.max(maxx, p[0]); miny = Math.min(miny, p[1]); maxy = Math.max(maxy, p[1]); }\n"
        "  const tw = maxx - minx || 1, th = maxy - miny || 1;\n"
        "  const boxX = w * 0.60, boxY = hgt * 0.30, boxW = w * 0.34, boxH = hgt * 0.42;\n"
        "  const sc = Math.min(boxW / tw, boxH / th) * 0.82;\n"
        "  const ox = boxX + boxW / 2 - (minx + tw / 2) * sc;\n"
        "  const oy = boxY + boxH / 2 + (miny + th / 2) * sc;\n"
        "  const PX = vs.map(p => [ox + p[0] * sc, oy - p[1] * sc]);\n"
        "  H.path(PX, { color: H.colors.accent, width: 3, close: true });\n"
        "  const names = ['A', 'B', 'C'];\n"
        "  for (let i = 0; i < 3; i++) {\n"
        "    H.circle(PX[i][0], PX[i][1], 4, { fill: H.colors.ink });\n"
        "    const av = D.labels[names[i]];\n"
        "    H.text(names[i] + (av != null ? ' = ' + av.toFixed(0) + '\\u00B0' : ''), PX[i][0] + 8, PX[i][1] - 8, { color: H.colors.sub, size: 12, weight: 700 });\n"
        "  }\n"
        "  // side labels at edge midpoints (a opposite A = edge B-C, etc.)\n"
        "  const edges = [[1, 2, 'a'], [0, 2, 'b'], [0, 1, 'c']];\n"
        "  for (const e of edges) {\n"
        "    const mx = (PX[e[0]][0] + PX[e[1]][0]) / 2, my = (PX[e[0]][1] + PX[e[1]][1]) / 2;\n"
        "    const sv = D.labels[e[2]];\n"
        "    H.text(e[2] + (sv != null ? '=' + sv.toFixed(1) : ''), mx, my, { color: H.colors.accent2, size: 12, align: 'center', baseline: 'middle' });\n"
        "  }\n"
        "}\n"
        "// Slide text card on the left.\n"
        "const cx = 24, cy = hgt * 0.34, cw = w * 0.50;\n"
        "H.rect(cx, cy, cw, 132, { fill: 'rgba(124,196,255,0.07)', stroke: H.colors.accent, width: 1.4, radius: 12 });\n"
        "H.text(st.title, cx + 16, cy + 28, { color: H.colors.accent, size: 16, weight: 700, maxWidth: cw - 32 });\n"
        "H.text(st.formula, cx + 16, cy + 60, { color: H.colors.ink, size: 15, weight: 700, maxWidth: cw - 32 });\n"
        "H.text(st.detail, cx + 16, cy + 92, { color: H.colors.sub, size: 13, maxWidth: cw - 32 });\n"
        "if (D.ambiguous) H.text('\\u26A0 Ambiguous (SSA): two triangles satisfy the given data.', cx, cy + 156, { color: H.colors.warn, size: 13, weight: 700 });\n"
    )


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def solver_scene(prompt: str):
    """Return a scene-content dict for a specific solvable problem, or None.
    `code` is RAW (caller runs it through sanitize_code, like the other paths)."""
    given = parse_triangle(prompt)
    if not given:
        return None
    result = solve_triangle(given)
    if result is None:
        return None
    nsol = len(result.get("solutions", []))
    case = result["case"]
    case_name = {"SSS": "three sides (SSS)", "SAS": "two sides + included angle (SAS)",
                 "ASA_AAS": "two angles + a side (ASA/AAS)", "SSA": "two sides + a non-included angle (SSA)"}[case]
    if nsol == 0:
        summary = f"The given values ({case_name}) describe NO valid triangle — the slides show why."
    elif result.get("ambiguous"):
        summary = (f"This is the ambiguous case ({case_name}): TWO different triangles fit your numbers. "
                   "The slides solve it with the Law of Sines and show both solutions.")
    else:
        summary = (f"A worked, step-by-step solution for your triangle ({case_name}). "
                   "Each slide reveals one step — set-up, the law used, and the computation with your numbers.")
    return {
        "title": "Solving your triangle — step by step",
        "tag": "Worked solution",
        "dimension": "2D",
        "equation": "  ".join(f"{k}={given[k]:g}" + ("°" if k.isupper() else "") for k in given),
        "summary": summary,
        "bullets": [
            "Each slide is one step of the solution, advancing automatically.",
            "The triangle is drawn to scale; values fill in as they're found.",
            "It uses YOUR numbers — not a generic example.",
            ("Two triangles fit (the SSA ambiguous case) — both are shown."
             if result.get("ambiguous") else "The chosen law (Sines/Cosines) is named at each step."),
        ],
        "student_prompts": [
            "Why does this case use the Law of Sines (or Cosines)?",
            "When does a triangle problem have two answers?",
            "How do I check my solution is right?",
        ],
        "code": _solver_code(result, prompt),
        "kind": "triangle",
    }
