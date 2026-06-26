/* VisualLM — curated matching (browser port of main.py's scorer).
 *
 * Scores the prompt against the demo library (333 interactive demos) and the
 * scene library (50 curated scenes) with the exact same keyword/title/tag
 * scoring as the Python server, so the browser routes a prompt to the same
 * scene the desktop app would. Exposes a global VisualLMMatch.
 */
(function (global) {
  "use strict";

  let DEMOS = [];
  let SCENES = [];

  const STOPWORDS = new Set((
    "the a an of in on to and or is are show me how visualize animate explain " +
    "draw plot with for as its it this that what why over time using see"
  ).split(" "));

  function tokenize(s) {
    const m = (s || "").toLowerCase().match(/[a-z0-9]+/g);
    return new Set(m || []);
  }
  function tokensMinusStop(s) {
    const out = new Set();
    for (const t of tokenize(s)) if (!STOPWORDS.has(t)) out.add(t);
    return out;
  }
  function intersize(a, b) {
    let n = 0;
    for (const x of a) if (b.has(x)) n++;
    return n;
  }

  // Equation-form matching (mirrors main.py _norm_eq / _prompt_equation /
  // _equation_boost): a bare equation like "E=mc^2" tokenizes to junk, so we
  // match a normalized equation signature instead.
  function normEq(s) {
    s = String(s || "").toLowerCase()
      .replace(/²/g, "2").replace(/³/g, "3").replace(/⁴/g, "4")
      .replace(/λ/g, "l").replace(/·/g, "").replace(/×/g, "").replace(/[−–]/g, "-");
    return s.replace(/[^a-z0-9=+/]/g, "");
  }
  function promptEquation(prompt) {
    if (!prompt || prompt.indexOf("=") < 0) return "";
    const tight = String(prompt).replace(/\s*([=+\-*/^·×])\s*/g, "$1");
    const cands = tight.split(/\s+/).filter((tok) => tok.indexOf("=") >= 0);
    if (!cands.length) return "";
    return normEq(cands.reduce((a, b) => (b.length > a.length ? b : a), ""));
  }
  function sortRuns(s) {
    return s.replace(/[a-z]{2,}/g, (m) => m.split("").sort().join(""));
  }
  function equationBoost(sc, peq) {
    if (!peq || peq.length < 4) return 0;
    let sigs = [normEq(sc.equation || ""), normEq(sc.title || "")];
    for (const k of sc.keywords || []) if (String(k).indexOf("=") >= 0) sigs.push(normEq(k));
    sigs = sigs.filter(Boolean);
    let boost = 0;
    for (const sig of sigs) {
      if (peq === sig) return 6.0;
      if (sig.indexOf(peq) >= 0 || (sig.length >= 4 && peq.indexOf(sig) >= 0)) boost = Math.max(boost, 5.0);
    }
    if (boost === 0) {
      const peqs = sortRuns(peq);
      for (const sig of sigs) {
        const ss = sortRuns(sig);
        if (peqs === ss) return 5.0;
        if ((peqs.length >= 4 && ss.indexOf(peqs) >= 0) || (ss.length >= 4 && peqs.indexOf(ss) >= 0)) boost = Math.max(boost, 4.0);
      }
    }
    return boost;
  }

  // Mirrors _scene_score(sc, ptext, ptoks, mode, peq).
  function sceneScore(sc, ptext, ptoks, mode, peq) {
    let score = 0;
    for (const kw of sc.keywords || []) {
      const k = String(kw).toLowerCase().trim();
      if (!k) continue;
      if (k.indexOf(" ") >= 0) {
        if (ptext.indexOf(k) >= 0) score += 2.0;
      } else if (ptoks.has(k)) {
        score += 1.0;
      }
    }
    const titleToks = tokensMinusStop(sc.title || "");
    const tagToks = tokensMinusStop(sc.tag || sc.area || "");
    score += 1.0 * intersize(titleToks, ptoks);
    score += 0.5 * intersize(tagToks, ptoks);
    score += equationBoost(sc, peq || "");
    const dim = String(sc.dimension || "").toLowerCase();
    if ((mode === "2d" || mode === "3d") && dim !== mode) score -= 1.5;
    return score;
  }

  function ptextOf(prompt) {
    return " " + String(prompt || "").toLowerCase().replace(/\s+/g, " ") + " ";
  }

  function libraryScored(prompt, mode) {
    if (!SCENES.length) return [];
    const ptext = ptextOf(prompt);
    const ptoks = tokensMinusStop(prompt);
    const peq = promptEquation(prompt);
    const scored = SCENES.map((sc) => [sc, sceneScore(sc, ptext, ptoks, mode, peq)]).filter((t) => t[1] > 0);
    scored.sort((a, b) => b[1] - a[1]);
    return scored;
  }

  function demoScored(prompt) {
    if (!DEMOS.length) return [];
    const ptext = ptextOf(prompt);
    const ptoks = tokensMinusStop(prompt);
    const peq = promptEquation(prompt);
    // mode "auto" so a 2D demo isn't penalized by a 3D hint (matches Python).
    const scored = DEMOS.map((d) => [d, sceneScore(d, ptext, ptoks, "auto", peq)]).filter((t) => t[1] > 0);
    scored.sort((a, b) => b[1] - a[1]);
    return scored;
  }

  function demoMatch(prompt) {
    const s = demoScored(prompt);
    return s.length ? { demo: s[0][0], score: s[0][1] } : { demo: null, score: 0 };
  }

  global.VisualLMMatch = {
    loadData(demos, scenes) { DEMOS = demos || []; SCENES = scenes || []; },
    libraryScored, demoScored, demoMatch, sceneScore, tokenize,
    get demos() { return DEMOS; },
    get scenes() { return SCENES; },
  };
})(typeof window !== "undefined" ? window : this);
