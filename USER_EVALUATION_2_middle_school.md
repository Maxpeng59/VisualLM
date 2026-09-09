# VisualLM — User Evaluation Form (Persona 2)

> Second hands-on evaluation, from a **different and younger** persona than
> `USER_EVALUATION.md`. Same method: actually type what this student would type,
> watch where it routes, judge it through her eyes.

---

## 1. Session details

| Field | Value |
|---|---|
| Tester persona | **Maya, age 12, 7th grade** — doing science + pre-algebra homework |
| How she types | Plain-English questions, often "what is…/why do…", occasional typo; **no math notation** |
| What she wants | A quick, clear picture and a simple explanation; gives up at walls of text |
| Edition tested | Browser edition (`http://localhost:4179`, `parameterized-demos`) |
| Date | 2026-06-26 |

## 2. What I actually typed (12 real 7th-grade prompts)

| Prompt | What she got | Verdict |
|---|---|---|
| what is photosynthesis | Dead-end help card | ✗ no biology |
| what is a cell | Dead-end help card | ✗ no biology |
| how do magnets work | Dead-end help card | ✗ |
| why do we have seasons | Dead-end help card | ✗ no earth science |
| the water cycle | Dead-end help card | ✗ no earth science |
| 7 times 8 | Dead-end help card | ✗ no basic arithmetic |
| why is the sky blue | Dead-end help card | ✗ |
| parts of a plant cell | Dead-end help card | ✗ |
| how does the heart pump blood | Dead-end help card | ✗ |
| area of a circle | **Rectangle: Area = L·W** | ✗ wrong shape |
| how to add fractions 1/2 + 1/4 | **Add rational expressions a/b + c/d** (Algebra 2) | ~ right idea, wrong grade |
| what is gravity | **Inverse-Square Gravity & the Potential Well** | ~ real, but college-level |

**8 of 12 dead-ended. The other 4 were wrong, mis-graded, or over her head.** Zero
clean, age-appropriate hits.

## 3. Overall impression

**★★☆☆☆ for a middle-schooler.** The app is clearly built for high-school-and-up
STEM. A 12-year-old's curriculum — life science, earth science, simple physical
science, pre-algebra arithmetic — is almost entirely outside it, and the content she
*can* reach is written above her reading level. The interactivity is appealing; the
content scope and tone are not for her.

## 4. What still works for her (be fair)

- [x] When she reaches the **fraction demo**, the bar / area-model visual ("cut each
      fraction into finer pieces until denominators match") is genuinely
      age-appropriate and well explained.
- [x] **Instant, colorful, interactive** — kids respond to drag-the-slider.
- [x] "what is gravity" at least produced a real moving visualization (just the wrong
      altitude for her).

## 5. Findings by severity

### P0 — Reading level / grade band is fixed and too high
The same explanation is served to everyone; there's no notion of audience. "what is
gravity" returns *"the gravitational potential Φ = −GM/r drawn as a 3D funnel-shaped
well with a test mass orbiting on its wall… g(r) = GM/r²."* A 12-year-old wanted
"gravity is the pull that brings things down to Earth." Dense multi-clause paragraphs
are a wall for her.

**Fix:** add a **grade-band / "explain it simpler ↔ deeper" control** that swaps the
explanation text (and biases demo selection toward the grade-appropriate version).
Cheapest first step: a reading-level toggle that rewrites the explanation; later,
let grade preference break ties in the matcher.

### P0 — Tie-breaking serves the abstract demo over the exact-topic one
"area of a circle" → **Rectangle** (Area = L·W). The literally-perfect demo
**"Circle: area = πr², circumference = 2πr" (Geometry)** exists but **tied at score 2**
and lost the tie-break. Same shape of bug as Persona 1's quadratic→calculus case.

**Fix:** break ties by **exact topic/title phrase match** — an "area of a circle" query
must let the *Circle area* demo beat a generic *Rectangle* demo. Also bias by grade
band (a 7th-grade "fractions" query should prefer the arithmetic demo over Algebra 2
"rational expressions").

### P0 — Demos ignore the numbers the student typed
She types `1/2 + 1/4`; the fraction demo opens at **default sliders**, not
a=1, b=2, c=1, d=4. She has to re-enter her own problem by hand. (Contrast: the
**triangle solver reads her numbers** — which is exactly why it feels great.) For a
younger student, "show MY problem" is most of the value.

**Fix:** parse numbers out of the prompt and **seed the demo's sliders** from them,
the way `solver.js` already seeds the triangle. Big perceived-quality win across all
ages, biggest for this one.

### P1 — Coverage scope excludes the middle-school curriculum
No biology, no earth science, simple physical science only in advanced form, and no
elementary arithmetic. This is a **product-scope decision**, not a bug — but if
younger students are in scope, the library needs life-science / earth-science /
physical-science / pre-algebra demos. If they're *not* in scope, the app should say so
kindly instead of dead-ending (see next).

### P1 — The dead-end help card is written for adults
What she sees after a dead-end: *"Free-form AI generation runs in the desktop app…
curriculum demos… curated scenes… no server,"* then it suggests she try
*"quadratic vertex / projectile motion / CH4."* Every word and every example is above
her. It reads like an error for power users.

**Fix:** plain-language, kid-friendly copy with age-appropriate example chips, and
**don't push high-school topics** at someone who asked about photosynthesis. If the
topic genuinely isn't covered, say "I can't draw that one yet" simply.

## 6. Recommended next steps

| Priority | Item | Effort | Note |
|---|---|---|---|
| 1 | Seed demo sliders from numbers in the prompt | Small | Helps every persona |
| 2 | Tie-break by exact topic/title phrase (+ grade bias) | Small | Fixes circle→rectangle & fractions→Algebra 2 |
| 3 | Reading-level / "simpler ↔ deeper" toggle on explanations | Medium | Core of the age problem |
| 4 | Plain-language, age-aware help card | Small | Stop dead-ending kids with jargon |
| 5 | Decide middle-school coverage (scope) | Large | Product call: add life/earth science or set expectations |

**Biggest lever for this persona:** items 1–3. Reading "MY numbers" back to me, at
*my* level, in *plain words* is the whole difference between "this is for me" and
"this is for the big kids."

## 7. Cross-persona note

The relevance/tie-break weakness shows up for **both** personas — the older student's
`x²−5x+6=0` → calculus limit, and the younger student's `area of a circle` → rectangle
are the *same* underlying bug (an exact-topic demo losing a tie to a generic one).
Fixing tie-breaking + number-seeding + a grade toggle would lift the experience for
the whole age range at once.
