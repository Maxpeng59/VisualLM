(function () {
  "use strict";

  /* ============================================================== */
  /* Small utilities                                                */
  /* ============================================================== */

  const $ = (id) => document.getElementById(id);

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  /* ============================================================== */
  /* Tutor text rendering                                           */
  /* ============================================================== */
  //
  // The tutor (Ollama or Claude) sometimes ignores the "plain text" rule and
  // emits Markdown + LaTeX. Rather than rely on prompt discipline, we clean
  // it up here:
  //   1. HTML-escape first, so any literal <, >, & from the model stays text.
  //   2. Strip LaTeX delimiters and rewrite the common commands into plain
  //      text (e.g. \(F\) -> F, \frac{dF}{dt} -> dF/dt, \alpha -> α).
  //   3. Render a tiny safe subset of Markdown (bold, italic, inline code,
  //      bullet/numbered lists, paragraph breaks). NO arbitrary HTML.

  const GREEK = {
    alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ε",
    zeta: "ζ", eta: "η", theta: "θ", iota: "ι", kappa: "κ",
    lambda: "λ", mu: "μ", nu: "ν", xi: "ξ", pi: "π", rho: "ρ",
    sigma: "σ", tau: "τ", upsilon: "υ", phi: "φ", chi: "χ",
    psi: "ψ", omega: "ω",
    Alpha: "Α", Beta: "Β", Gamma: "Γ", Delta: "Δ", Epsilon: "Ε",
    Theta: "Θ", Lambda: "Λ", Mu: "Μ", Pi: "Π", Sigma: "Σ",
    Phi: "Φ", Psi: "Ψ", Omega: "Ω",
    infty: "∞", partial: "∂", nabla: "∇", sum: "Σ", prod: "Π",
    int: "∫", cdot: "·", times: "×", div: "÷", pm: "±", mp: "∓",
    leq: "≤", geq: "≥", neq: "≠", approx: "≈", equiv: "≡",
    rightarrow: "→", leftarrow: "←", Rightarrow: "⇒", Leftarrow: "⇐",
    to: "→", sin: "sin", cos: "cos", tan: "tan", log: "log",
    ln: "ln", exp: "exp",
  };

  function stripLatex(s) {
    // Block math: \[ ... \] -> on its own line, plain.
    s = s.replace(/\\\[([\s\S]*?)\\\]/g, "\n$1\n");
    // Display $$ ... $$ -> on its own line.
    s = s.replace(/\$\$([\s\S]*?)\$\$/g, "\n$1\n");
    // Inline math: \(...\) and $...$ (avoid currency by requiring no space).
    s = s.replace(/\\\(([\s\S]*?)\\\)/g, "$1");
    s = s.replace(/(?<!\$)\$([^\s$][^$\n]*?[^\s$])\$(?!\$)/g, "$1");
    s = s.replace(/(?<!\$)\$([^\s$])\$(?!\$)/g, "$1");

    // Degree: \circ and ^\circ -> ° (do this BEFORE the greek fallback, which
    // would otherwise turn \circ into the literal word "circ", e.g. 58^circ).
    s = s.replace(/\^?\s*\\circ\b/g, "°");
    s = s.replace(/\\degrees?\b/g, "°");

    // LaTeX spacing macros (\, \; \: \! \quad \qquad and backslash-space) -> a
    // single space. The greek fallback ignores these (\, isn't a letter run),
    // so without this they survive as literal "\," junk.
    s = s.replace(/\\(?:quad|qquad)\b/g, " ");
    s = s.replace(/\\[,;:!> ]/g, " ");

    // \mathrm/\mathbf/\operatorname{...} -> just the inner text.
    s = s.replace(/\\(?:mathrm|mathbf|mathit|operatorname)\s*\{([^{}]*)\}/g, "$1");

    // \frac{a}{b} -> a/b. Tolerate doubled braces {{...}} that local models
    // sometimes emit, and parenthesize a compound numerator/denominator.
    s = s.replace(/\\frac\s*\{+([^{}]+)\}+\s*\{+([^{}]+)\}+/g, (_, a, b) => {
      a = a.trim();
      b = b.trim();
      const parenA = /[+\-]/.test(a) ? `(${a})` : a;
      const parenB = /[+\-]/.test(b) ? `(${b})` : b;
      return `${parenA}/${parenB}`;
    });
    // \sqrt{a} -> sqrt(a)
    s = s.replace(/\\sqrt\s*\{+([^{}]+)\}+/g, "sqrt($1)");
    // \text{a} -> a
    s = s.replace(/\\text\s*\{([^{}]*)\}/g, "$1");
    // Subscripts / superscripts: x_{n} -> x_n, x^{2} -> x^2 (doubled braces too)
    s = s.replace(/_\{+([^{}]+)\}+/g, "_$1");
    s = s.replace(/\^\{+([^{}]+)\}+/g, "^$1");

    // Greek + common symbols / function names.
    s = s.replace(/\\([A-Za-z]+)/g, (_, name) =>
      Object.prototype.hasOwnProperty.call(GREEK, name) ? GREEK[name] : name
    );
    // Stray "left"/"right" sizing markers — leave the inner brackets.
    s = s.replace(/\b(left|right)\b/g, "");
    // Any lone backslash left before whitespace/punctuation is LaTeX residue.
    s = s.replace(/\\(?=[\s.,;:)\]}])/g, "");
    // Tidy spaces.
    return s.replace(/[ \t]+/g, " ").replace(/ ?\n ?/g, "\n");
  }

  function renderTutorMarkdown(raw) {
    // 1. Escape first — everything we insert after this is either literal
    //    escaped text or our own whitelisted tags.
    let s = escapeHtml(raw);
    // 2. Strip LaTeX -> plain text.
    s = stripLatex(s);
    // 3. Markdown: code, bold, italics, headers.
    s = s.replace(/`([^`\n]+?)`/g, "<code>$1</code>");
    s = s.replace(/\*\*([^*\n][^*]*?)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(?<![*\w])\*([^*\n]+?)\*(?!\w)/g, "<em>$1</em>");
    s = s.replace(/^#{1,6}\s+(.+)$/gm, "<strong>$1</strong>");

    // 4. Lists, line by line. Group consecutive same-type items, even when
    //    separated by blank lines (tutors love "1. ...\n\n2. ...").
    const lines = s.split("\n");
    const out = [];
    let listType = null;
    let buf = [];
    const flush = () => {
      if (!listType) return;
      out.push(
        `<${listType}>` +
          buf.map((i) => `<li>${i}</li>`).join("") +
          `</${listType}>`
      );
      listType = null;
      buf = [];
    };
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const ol = line.match(/^\s*\d+\.\s+(.+)$/);
      const ul = line.match(/^\s*[-•]\s+(.+)$/);
      if (ol) {
        if (listType !== "ol") flush();
        listType = "ol";
        buf.push(ol[1]);
      } else if (ul) {
        if (listType !== "ul") flush();
        listType = "ul";
        buf.push(ul[1]);
      } else if (line.trim() === "" && listType) {
        // Blank line between items — look ahead. If the next non-blank line
        // continues the same list type, swallow this blank. Otherwise close.
        let j = i + 1;
        while (j < lines.length && lines[j].trim() === "") j++;
        const next = lines[j] || "";
        const continuesOl = /^\s*\d+\.\s+/.test(next);
        const continuesUl = /^\s*[-•]\s+/.test(next);
        if ((listType === "ol" && continuesOl) || (listType === "ul" && continuesUl)) {
          continue; // stay inside the list
        }
        flush();
        out.push(line);
      } else {
        flush();
        out.push(line);
      }
    }
    flush();
    s = out.join("\n");

    // 5. Paragraph breaks: collapse runs of blank lines, then \n -> <br>.
    s = s.replace(/\n{3,}/g, "\n\n");
    s = s.replace(/\n/g, "<br>");
    // Strip <br> noise adjacent to list tags.
    s = s.replace(/(<br>)+(<\/?(?:ol|ul|li)>)/g, "$2");
    s = s.replace(/(<\/(?:ol|ul)>)(<br>)+/g, "$1");
    return s;
  }

  /* Optional shared access code for published deployments. The server
   * answers 401 + code_required until the right X-Access-Code header is
   * sent; we ask once and remember it in localStorage. */
  const ACCESS_CODE_KEY = "visuallm-access-code";
  function getAccessCode() {
    try {
      return localStorage.getItem(ACCESS_CODE_KEY) || "";
    } catch (e) {
      return "";
    }
  }
  function apiHeaders() {
    const headers = { "Content-Type": "application/json" };
    const code = getAccessCode();
    if (code) headers["X-Access-Code"] = code;
    return headers;
  }
  function promptForAccessCode() {
    const entered = window.prompt(
      "This VisualLM server requires an access code to generate animations:"
    );
    if (!entered || !entered.trim()) return false;
    try {
      localStorage.setItem(ACCESS_CODE_KEY, entered.trim());
    } catch (e) {
      /* private mode — the code just won't persist */
    }
    return true;
  }

  async function postJSON(path, body, opts) {
    // Fetch with one retry by default: localhost fetches occasionally fail
    // with the browser-generic `TypeError: Failed to fetch` for transient
    // reasons (server thread mid-restart, socket race, etc.). Re-trying once
    // turns most of those into a single visible blip instead of a hard fail.
    //
    // Callers MUST opt out (`{retry: false}`) for non-idempotent endpoints:
    // if a request gets through to the server and only the *response* drops,
    // the retry would re-process the side effect (e.g. duplicate uploads).
    const maxAttempts = opts && opts.retry === false ? 1 : 2;
    let res;
    let lastFetchError = null;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      try {
        res = await fetch(path, {
          method: "POST",
          headers: apiHeaders(),
          body: JSON.stringify(body),
        });
        lastFetchError = null;
        break;
      } catch (err) {
        lastFetchError = err;
        if (attempt < maxAttempts - 1) {
          await new Promise((r) => setTimeout(r, 250));
        }
      }
    }
    if (lastFetchError) {
      throw new Error(
        "Couldn't reach the server. Is the Python server (`python3 main.py`) still running?"
      );
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      // Locked deployment: ask for the access code once and retry the same
      // call. A wrong code lands back here and asks again.
      if (res.status === 401 && data && data.code_required) {
        if (promptForAccessCode()) return postJSON(path, body, opts);
      }
      const message = data && data.error ? data.error : `Request failed (${res.status}).`;
      throw new Error(message);
    }
    return data;
  }

  /* ============================================================== */
  /* Sandbox runner: a Web Worker + OffscreenCanvas that runs the   */
  /* AI-generated animation code in isolation.                      */
  /* ============================================================== */

  class SandboxRunner {
    constructor(frame) {
      this.frame = frame;
      this.worker = null;
      this.ready = false;
      this.readyWaiters = [];
      this.pending = null; // { resolve, reject, settled, watchdog }
      this.speed = 1;
      this.paused = false;
      this.onCrash = null; // called for runtime errors after a scene is live
      this._resizeRaf = 0;
      this._spawn();
      // Debounce via rAF: a window-drag fires resize ~60×/s, and each
      // _resize() sets canvas.width which CLEARS the bitmap. Without coalescing,
      // the canvas flickers black for the entire drag. One resize message per
      // animation frame is enough for any visible UI change.
      window.addEventListener("resize", () => {
        if (this._resizeRaf) return;
        this._resizeRaf = requestAnimationFrame(() => {
          this._resizeRaf = 0;
          this._resize();
        });
      });
      this._wireOrbit();
    }

    /* Drag-to-orbit + scroll-to-zoom + double-click-to-reset for 3D scenes.
     * Listeners live on the persistent frame (the canvas inside is recreated
     * on every worker respawn); the worker applies the deltas to every cam3d. */
    _wireOrbit() {
      const frame = this.frame;
      let dragging = false;
      let lastX = 0;
      let lastY = 0;
      frame.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        dragging = true;
        lastX = e.clientX;
        lastY = e.clientY;
        if (frame.setPointerCapture) {
          try {
            frame.setPointerCapture(e.pointerId);
          } catch (err) {
            /* capture is best-effort */
          }
        }
      });
      frame.addEventListener("pointermove", (e) => {
        if (!dragging || !this.worker) return;
        const dx = e.clientX - lastX;
        const dy = e.clientY - lastY;
        lastX = e.clientX;
        lastY = e.clientY;
        this.worker.postMessage({
          type: "orbit",
          dyaw: dx * 0.008,
          dpitch: dy * 0.008,
        });
      });
      const endDrag = () => {
        dragging = false;
      };
      frame.addEventListener("pointerup", endDrag);
      frame.addEventListener("pointercancel", endDrag);
      frame.addEventListener("pointerleave", endDrag);
      frame.addEventListener(
        "wheel",
        (e) => {
          if (!this.worker) return;
          e.preventDefault();
          this.worker.postMessage({
            type: "orbit",
            dzoom: Math.exp(-e.deltaY * 0.0012),
          });
        },
        { passive: false }
      );
      frame.addEventListener("dblclick", () => {
        if (this.worker) this.worker.postMessage({ type: "orbit-reset" });
      });
    }

    _newCanvas() {
      const old = this.frame.querySelector("canvas");
      if (old) old.remove();
      const canvas = document.createElement("canvas");
      canvas.id = "visualizerCanvas";
      canvas.setAttribute("aria-label", "STEM visualization canvas");
      this.frame.insertBefore(canvas, this.frame.firstChild);
      return canvas;
    }

    _dims() {
      const rect = this.frame.getBoundingClientRect();
      return {
        width: Math.max(320, Math.round(rect.width)),
        height: Math.max(240, Math.round(rect.height)),
        dpr: Math.min(2, window.devicePixelRatio || 1),
      };
    }

    _spawn() {
      this.ready = false;
      if (this.worker) {
        try {
          this.worker.terminate();
        } catch (e) {
          /* ignore */
        }
      }
      const canvas = this._newCanvas();
      const offscreen = canvas.transferControlToOffscreen();
      const worker = new Worker("./sandbox-worker.js?v=17");
      this.worker = worker;
      worker.onmessage = (e) => this._onMessage(e.data || {});
      const d = this._dims();
      worker.postMessage(
        { type: "init", canvas: offscreen, width: d.width, height: d.height, dpr: d.dpr },
        [offscreen]
      );
    }

    _whenReady() {
      if (this.ready) return Promise.resolve();
      return new Promise((resolve) => this.readyWaiters.push(resolve));
    }

    _onMessage(m) {
      switch (m.type) {
        case "ready":
          this.ready = true;
          this.readyWaiters.splice(0).forEach((fn) => fn());
          break;
        case "heartbeat":
          if (this.pending && !this.pending.settled) this._settle(true);
          break;
        case "compile-error":
        case "runtime-error": {
          // Carry the sandbox-extracted offending line (m.where) on the Error so
          // the repair request can forward it to the model.
          if (this.pending && !this.pending.settled) {
            const e = new Error(m.message || "Animation failed.");
            e.where = m.where || "";
            this._settle(false, e);
          } else if (this.onCrash) {
            const e = new Error(m.message || "Animation crashed.");
            e.where = m.where || "";
            this.onCrash(e);
          }
          break;
        }
        default:
          break;
      }
    }

    _settle(ok, err) {
      const p = this.pending;
      if (!p || p.settled) return;
      p.settled = true;
      clearTimeout(p.watchdog);
      this.pending = null;
      if (ok) p.resolve();
      else p.reject(err);
    }

    /* Load code and resolve once it renders a frame; reject on error/hang.
     * `params` seeds the demo `P` global (editable live via setParams). */
    async run(code, params) {
      await this._whenReady();
      if (this.pending && !this.pending.settled) this._settle(false, new Error("superseded"));

      return new Promise((resolve, reject) => {
        const pending = { resolve, reject, settled: false, watchdog: null };
        this.pending = pending;
        pending.watchdog = setTimeout(() => {
          // No heartbeat and no error -> the scene is likely stuck in a loop.
          this._spawn(); // kill the frozen worker and start a fresh one
          this._settle(false, new Error("The animation hung (possible infinite loop)."));
        }, 3000);
        this.worker.postMessage({ type: "run", code, params: params || {}, resetTime: true });
        if (this.paused) this.worker.postMessage({ type: "pause" });
        this.worker.postMessage({ type: "speed", value: this.speed });
      });
    }

    pause() {
      this.paused = true;
      if (this.worker) this.worker.postMessage({ type: "pause" });
    }
    resume() {
      this.paused = false;
      if (this.worker) this.worker.postMessage({ type: "resume" });
    }
    setSpeed(value) {
      this.speed = value;
      if (this.worker) this.worker.postMessage({ type: "speed", value });
    }
    /* Live-update demo parameters without recompiling the scene. */
    setParams(values) {
      if (this.worker) this.worker.postMessage({ type: "params", values: values || {} });
    }
    _resize() {
      if (!this.worker || !this.ready) return;
      const d = this._dims();
      this.worker.postMessage({
        type: "resize",
        width: d.width,
        height: d.height,
        dpr: d.dpr,
      });
    }
  }

  /* ============================================================== */
  /* App state + DOM references                                     */
  /* ============================================================== */

  const state = {
    mode: "auto",
    scene: null,
    busy: false,
    chat: [],
    chatBusy: false,
    health: null,
  };

  const el = {
    prompt: $("promptInput"),
    visualize: $("visualizeButton"),
    random: $("randomButton"),
    playPause: $("playPauseButton"),
    speed: $("speedSlider"),
    speedValue: $("speedValue"),
    topic: $("detectedTopic"),
    dimension: $("detectedDimension"),
    equation: $("detectedEquation"),
    summary: $("sceneSummary"),
    tag: $("sceneTag"),
    confidence: $("sceneConfidence"),
    explanation: $("explanationList"),
    frame: document.querySelector(".canvas-frame"),
    chatMessages: $("chatMessages"),
    chatForm: $("chatForm"),
    chatInput: $("chatInput"),
    sendChat: $("sendChatButton"),
    chatSuggestions: $("chatSuggestions"),
    statusBadge: $("ollamaStatusBadge"),
    modelLabel: $("ollamaModelLabel"),
    orbitHint: $("orbitHint"),
  };

  const runner = new SandboxRunner(el.frame);
  // Crashes AFTER a scene has started (post-heartbeat runtime errors) used
  // to just print the error and leave a frozen canvas. Now we auto-trigger
  // the repair flow with the crashed scene's code + the error message, the
  // same way runSceneWithRepair handles errors during initial load.
  runner.onCrash = async (err) => {
    if (!state.scene || state.busy) {
      setConfidence("Animation error: " + err.message, "warn");
      return;
    }
    setBusyVisual(true, "Repairing…");
    setConfidence(
      "Animation crashed: " + err.message + ". Asking the model to fix it…",
      "pending",
    );
    try {
      const repaired = await postJSON("/api/repair", {
        prompt: state.scene.prompt,
        code: state.scene.code,
        error: err.message,
        where: err.where || "",
      });
      await runSceneWithRepair(repaired, state.scene.prompt);
    } catch (repairErr) {
      setConfidence("Could not auto-repair: " + repairErr.message, "warn");
    } finally {
      setBusyVisual(false);
    }
  };

  /* ============================================================== */
  /* Panel rendering                                                */
  /* ============================================================== */

  function setConfidence(text, tone) {
    el.confidence.textContent = text;
    el.confidence.dataset.tone = tone || "";
  }

  function updatePanels(scene) {
    el.topic.textContent = scene.title;
    el.dimension.textContent = scene.dimension;
    el.equation.textContent = scene.equation || "No single equation — concept scene";
    el.summary.textContent = scene.summary;
    el.tag.textContent = scene.tag;
    // 3D scenes are orbitable — surface that, since nothing else hints at it.
    if (el.orbitHint) el.orbitHint.hidden = scene.dimension !== "3D";

    el.explanation.innerHTML = "";
    (scene.bullets || []).forEach((b) => {
      const li = document.createElement("li");
      li.textContent = b;
      el.explanation.appendChild(li);
    });
    renderSuggestions(scene);
  }

  function setBusyVisual(isBusy, label) {
    // Track focus so keyboard users aren't stranded when the button they
    // pressed gets disabled (focus jumps to <body>). We restore after re-enable.
    const focusedWasControl =
      isBusy && (document.activeElement === el.visualize ||
                  document.activeElement === el.random);
    if (focusedWasControl) setBusyVisual._restoreFocus = document.activeElement;
    state.busy = isBusy;
    el.visualize.disabled = isBusy;
    el.random.disabled = isBusy;
    // Chips trigger visualize() too, but visualize() early-returns when busy.
    // Without disabling, clicking a chip mid-generation silently overwrites
    // the prompt textarea while the in-flight scene is still loading.
    document.querySelectorAll(".chip").forEach((c) => {
      c.disabled = isBusy;
    });
    el.visualize.textContent = isBusy ? label || "Generating…" : "Visualize";
    // Tell screen readers the visualization region is loading / settled.
    if (el.frame) el.frame.setAttribute("aria-busy", isBusy ? "true" : "false");
    if (!isBusy && setBusyVisual._restoreFocus) {
      // Only restore focus if it's still on body (user hasn't moved on).
      if (document.activeElement === document.body) {
        setBusyVisual._restoreFocus.focus();
      }
      setBusyVisual._restoreFocus = null;
    }
  }

  /* ============================================================== */
  /* Visualization flow: generate -> run -> repair loop             */
  /* ============================================================== */

  // Each repair is a full, slow LLM round-trip. With the sandbox now tolerant of
  // invented helpers and transient bad frames (see sandbox-worker.js), genuinely
  // unfixable scenes are rarer — so cap repairs at 2 and show the fallback
  // sooner instead of burning a third slow call that usually fails the same way.
  const MAX_REPAIRS = 2;

  // Guaranteed-renderable placeholder for when generation + all repairs fail.
  // Without it the canvas sits dead-black under the error message.
  const CLIENT_FALLBACK_CODE = [
    'H.background();',
    'H.text("Couldn\'t render this prompt", 28, 40, { color: H.colors.ink, size: 20, weight: 700 });',
    'H.text("The model\'s code kept failing. Rephrase the prompt or try again.", 28, 64, { color: H.colors.sub, size: 13 });',
    'const cx = H.W / 2, cy = H.H / 2 + 20;',
    'const r = 60 + 16 * Math.sin(t * 1.5);',
    'H.circle(cx, cy, r, { stroke: H.colors.accent, width: 3 });',
    'H.circle(cx, cy, r * 0.6, { stroke: H.colors.accent2, width: 2 });',
    'H.circle(cx, cy, 6, { fill: H.colors.ink });',
  ].join("\n");

  const ENGINE_NAMES = {
    claude: "Claude",
    openai: "ChatGPT",
    gemini: "Gemini",
    ollama: "local model",
    library: "curated library",
    fallback: "fallback",
  };
  function engineName(engine) {
    return ENGINE_NAMES[engine] || "the model";
  }

  // A live elapsed-seconds ticker so a slow local-model generation reads as
  // "working" rather than "frozen". Updates the status line in place.
  let _elapsedTimer = null;
  function startElapsed(baseLabel) {
    stopElapsed();
    const t0 = Date.now();
    const tick = () => {
      const s = Math.round((Date.now() - t0) / 1000);
      setConfidence(`${baseLabel} (${s}s)`, "pending");
    };
    tick();
    _elapsedTimer = setInterval(tick, 1000);
  }
  function stopElapsed() {
    if (_elapsedTimer) {
      clearInterval(_elapsedTimer);
      _elapsedTimer = null;
    }
  }

  async function visualize(prompt) {
    if (state.busy) return;
    const clean = (prompt || "").trim();
    if (!clean) return;

    setBusyVisual(true, "Thinking…");
    el.topic.textContent = "Generating…";
    // Elapsed ticker — local generation can take 10-60s; a live counter makes
    // the wait legible instead of looking hung. (Curated/cached hits return so
    // fast the ticker never visibly advances.)
    startElapsed("The AI is writing a custom animation for your prompt…");

    // A new scene always starts playing. Without this, pausing one scene
    // left every FUTURE scene frozen on its first frame — which reads as
    // "the animation doesn't move" rather than "I paused it earlier".
    if (runner.paused) {
      runner.resume();
      el.playPause.textContent = "Pause";
    }

    try {
      const scene = await postJSON("/api/visualize", {
        prompt: clean,
        preferred_mode: state.mode,
      });
      stopElapsed();
      await runSceneWithRepair(scene, clean);
    } catch (err) {
      stopElapsed();
      setConfidence("Could not generate: " + err.message, "warn");
      el.topic.textContent = "Generation failed";
      el.summary.textContent = err.message;
      // Re-check which backend is alive — the failure often means the badge
      // is now stale (Ollama died, Claude key expired, server restarted, etc.).
      refreshStatus();
    } finally {
      stopElapsed();
      setBusyVisual(false);
    }
  }

  // Show the guaranteed-renderable placeholder under a warning. Used whenever
  // the repair loop gives up — budget exhausted, or non-convergence detected
  // (repeated identical error, or the model returned the code unchanged).
  async function showClientFallback(scene, message) {
    if (scene) {
      state.scene = scene;
      updatePanels(scene);
    }
    setConfidence(message, "warn");
    renderDemoControls(null);
    try {
      await runner.run(CLIENT_FALLBACK_CODE);
    } catch (fallbackErr) {
      /* placeholder is hand-written and can't realistically fail */
    }
  }

  /* ============================================================== */
  /* Interactive demo parameter controls ("fill in the values")     */
  /* ============================================================== */

  function demoParams(scene) {
    const out = {};
    ((scene && scene.params) || []).forEach((p) => {
      out[p.name] = p.value;
    });
    return out;
  }

  function fmtNum(v) {
    return String(Math.round(v * 100) / 100);
  }

  function injectDemoStyles() {
    if (document.getElementById("demoControlsStyle")) return;
    const st = document.createElement("style");
    st.id = "demoControlsStyle";
    st.textContent =
      ".demo-controls{margin:10px auto 0;width:92%;max-width:1100px;background:#16203a;border:1px solid #26314f;border-radius:12px;padding:12px 16px;box-sizing:border-box;}" +
      ".demo-controls-head{font-size:12px;color:#9fb0d4;text-transform:uppercase;letter-spacing:.04em;margin-bottom:8px;}" +
      ".demo-params{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px 18px;}" +
      ".demo-param{display:grid;grid-template-columns:1fr auto;align-items:center;gap:2px 10px;}" +
      ".demo-param-name{font-size:13px;color:#cfe0ff;}" +
      ".demo-param-val{font:600 13px 'JetBrains Mono',ui-monospace,monospace;color:#7cc4ff;min-width:3ch;text-align:right;}" +
      ".demo-param input[type=range]{grid-column:1 / -1;width:100%;accent-color:#7cc4ff;}";
    document.head.appendChild(st);
  }

  // Build the live slider panel for a demo scene. A non-demo scene (no params)
  // hides the panel. Moving a slider updates the worker's `P` global live —
  // no recompile — so the graph responds as you drag.
  function renderDemoControls(scene) {
    injectDemoStyles();
    let dc = document.getElementById("demoControls");
    if (!dc) {
      dc = document.createElement("div");
      dc.id = "demoControls";
      dc.className = "demo-controls";
      el.frame.insertAdjacentElement("afterend", dc);
    }
    const params = (scene && scene.params) || [];
    if (!params.length) {
      dc.hidden = true;
      dc.innerHTML = "";
      return;
    }
    dc.hidden = false;
    dc.innerHTML = "";
    const head = document.createElement("div");
    head.className = "demo-controls-head";
    head.textContent = "Adjust the values — the graph updates live";
    dc.appendChild(head);
    const grid = document.createElement("div");
    grid.className = "demo-params";
    dc.appendChild(grid);
    params.forEach((p) => {
      const row = document.createElement("div");
      row.className = "demo-param";
      const name = document.createElement("span");
      name.className = "demo-param-name";
      name.textContent = p.label || p.name;
      const slider = document.createElement("input");
      slider.type = "range";
      slider.min = p.min;
      slider.max = p.max;
      slider.step = p.step;
      slider.value = p.value;
      slider.setAttribute("aria-label", p.label || p.name);
      const val = document.createElement("span");
      val.className = "demo-param-val";
      val.textContent = fmtNum(p.value);
      slider.addEventListener("input", () => {
        const v = parseFloat(slider.value);
        val.textContent = fmtNum(v);
        runner.setParams({ [p.name]: v });
      });
      row.appendChild(name);
      row.appendChild(slider);
      row.appendChild(val);
      grid.appendChild(row);
    });
  }

  async function runSceneWithRepair(scene, prompt) {
    let current = scene;
    let prevError = null;
    for (let attempt = 0; attempt <= MAX_REPAIRS; attempt++) {
      const engineLabel = engineName(current.engine);
      try {
        if (!current.code || !current.code.trim()) {
          throw new Error("No animation code was produced.");
        }
        setConfidence(
          attempt === 0
            ? `Running ${current.dimension} scene from ${engineLabel}…`
            : `Repair ${attempt}/${MAX_REPAIRS}: trying the fixed code…`,
          "pending"
        );
        await runner.run(current.code, demoParams(current));
        state.scene = current;
        updatePanels(current);
        renderDemoControls(current);
        if (current.is_fallback) {
          // Server gave us a guaranteed-renderable placeholder because the real
          // generator produced blank code three times. Surface it clearly —
          // otherwise the user sees the breathing-circle placeholder and
          // a confidence message that claims it was "generated by local model".
          setConfidence(
            "Fallback scene — the model didn't draw anything. " +
              (current.summary || "Try rephrasing or enable Claude."),
            "warn",
          );
        } else if (current.quality_warnings && current.quality_warnings.length) {
          const issues = current.quality_warnings
            .map((w) => (w === "static" ? "may not animate" : "may lack labels"))
            .join(", ");
          setConfidence(
            `${current.dimension} • generated by ${engineLabel} — heads-up: ${issues}. ` +
              "Regenerate or rephrase for a better scene.",
            "warn",
          );
        } else if (current.from_library) {
          // Instant, hand-verified scene from the curated STEM corpus.
          setConfidence(
            `${current.dimension} • curated STEM scene (instant, verified)` +
              (current.fallback_reason ? " — " + current.fallback_reason : ""),
            "ok",
          );
        } else if (current.recovered_after_retry) {
          const n = current.recovered_after_retry;
          setConfidence(
            `${current.dimension} • generated by ${engineLabel}` +
              (current.model ? " (" + current.model + ")" : "") +
              ` — recovered after ${n} retr${n === 1 ? "y" : "ies"}`,
            "ok",
          );
        } else {
          setConfidence(
            `${current.dimension} • generated by ${engineLabel}` +
              (current.model ? " (" + current.model + ")" : "") +
              (current.cached ? " — instant (cached)" : ""),
            "ok"
          );
        }
        seedTutorForScene(current);
        return;
      } catch (err) {
        // Non-convergence guard: if this error follows a repair and matches the
        // PREVIOUS attempt's error, the repairs aren't making progress — bail
        // now instead of grinding through the rest of the (slow) repair budget.
        const stuck = attempt > 0 && err.message === prevError;
        prevError = err.message;
        if (attempt >= MAX_REPAIRS || stuck) {
          await showClientFallback(
            current,
            (stuck
              ? `The fix kept hitting the same error ("${err.message}") — stopping early. `
              : `Couldn't fix it after ${MAX_REPAIRS} tries. Last error: ${err.message}. `) +
              "Try a different prompt, or set ANTHROPIC_API_KEY for the stronger Claude generator."
          );
          return;
        }
        setConfidence(
          `Animation error: "${err.message}". Asking ${engineLabel} for a fix…`,
          "pending"
        );
        const triedCode = current.code;
        try {
          current = await postJSON("/api/repair", {
            prompt,
            code: current.code,
            error: err.message,
            where: err.where || "",
          });
        } catch (repairErr) {
          setConfidence("Repair failed: " + repairErr.message, "warn");
          return;
        }
        // Unchanged-code guard: the model returned the same code it was given,
        // so re-running it would fail identically — stop rather than spend
        // another slow round on a guaranteed repeat.
        if (current.code && triedCode && current.code.trim() === triedCode.trim()) {
          await showClientFallback(
            current,
            "The model returned the same code unchanged — stopping early. " +
              "Try rephrasing the prompt."
          );
          return;
        }
      }
    }
  }

  /* ============================================================== */
  /* Tutor chat                                                     */
  /* ============================================================== */

  function renderChat() {
    // Differential render: append new messages and refresh changed ones in
    // place. A full innerHTML rebuild looks like "removed all + added all"
    // to the aria-live="polite" region, which makes screen readers
    // re-announce the entire conversation on every send.
    const list = el.chatMessages;
    // Shrunk (e.g., seedTutorForScene replaced everything) — wipe and start over.
    if (list.children.length > state.chat.length) {
      list.replaceChildren();
    }
    for (let i = 0; i < state.chat.length; i++) {
      const msg = state.chat[i];
      const key = `${msg.role}|${msg.pending ? "1" : "0"}|${msg.content}`;
      let div = list.children[i];
      if (!div) {
        div = document.createElement("div");
        list.appendChild(div);
      } else if (div.dataset.key === key) {
        continue; // unchanged — leave the DOM (and the screen reader) alone
      }
      div.dataset.key = key;
      div.className = "chat-message " + msg.role + (msg.pending ? " pending" : "");
      // Pending bubbles are visual placeholders; hide from the AT tree so
      // screen readers don't announce "Thinking…" and then re-announce when
      // the real answer replaces it. The container's aria-busy below carries
      // the loading state.
      if (msg.pending) div.setAttribute("aria-hidden", "true");
      else div.removeAttribute("aria-hidden");
      const who = document.createElement("span");
      who.className = "chat-role";
      who.textContent = msg.role === "user" ? "You" : "Tutor";
      const body = document.createElement("p");
      body.className = "chat-body";
      body.innerHTML = renderTutorMarkdown(msg.content);
      div.replaceChildren(who, body);
    }
    // Tell SRs the chat region is awaiting a response when any bubble is pending.
    list.setAttribute(
      "aria-busy",
      state.chat.some((m) => m.pending) ? "true" : "false",
    );
    list.scrollTop = list.scrollHeight;
  }

  // Bumped every time the chat is wiped (seedTutorForScene). sendChat captures
  // this at start; if it changes before the response lands, an unrelated reset
  // happened (e.g. a new scene loaded) and we must NOT pop/push into the new
  // chat — that ate the seed and orphaned the user's question.
  let chatSessionId = 0;

  function seedTutorForScene(scene) {
    chatSessionId++;
    state.chat = [
      {
        role: "assistant",
        content:
          `This is "${scene.title}". ${scene.summary} ` +
          "Ask me anything — or ask me to solve a problem step by step and I'll " +
          "show what you need, each step, and where it applies.",
      },
    ];
    renderChat();
  }

  // A persistent quick-action that puts the tutor into step-by-step solve mode.
  // Filling the box (rather than auto-sending) lets the student append their
  // own numbers first, e.g. "...for v0 = 20 m/s and angle = 30 degrees".
  const SOLVE_PROMPT = "Solve this step by step: show what's needed, each step, and where it applies.";

  function addSuggestionChip(text, opts) {
    const btn = document.createElement("button");
    btn.className = "suggestion-chip" + (opts && opts.solve ? " solve" : "");
    btn.type = "button";
    btn.textContent = text;
    btn.addEventListener("click", () => {
      el.chatInput.value = (opts && opts.value) || text;
      el.chatInput.focus();
      // Put the caret at the end so the student can keep typing their specifics.
      const v = el.chatInput.value;
      el.chatInput.setSelectionRange(v.length, v.length);
    });
    el.chatSuggestions.appendChild(btn);
  }

  function renderSuggestions(scene) {
    el.chatSuggestions.innerHTML = "";
    // Always offer the step-by-step solver first.
    addSuggestionChip("Solve it step by step", { solve: true, value: SOLVE_PROMPT });
    (scene.student_prompts || []).slice(0, 4).forEach((prompt) => {
      addSuggestionChip(prompt);
    });
  }

  async function sendChat(question) {
    const clean = (question || "").trim();
    if (!clean || state.chatBusy) return;
    state.chatBusy = true;
    el.sendChat.disabled = true;

    state.chat.push({ role: "user", content: clean });
    state.chat.push({ role: "assistant", content: "Thinking…", pending: true });
    renderChat();

    const history = state.chat
      .filter((m) => !m.pending)
      .map((m) => ({ role: m.role, content: m.content }))
      .slice(-6);
    const session = chatSessionId;

    try {
      const data = await postJSON("/api/chat", {
        question: clean,
        visualization: state.scene || {},
        history: history.slice(0, -1),
      });
      if (session !== chatSessionId) return; // chat was reset; discard response
      state.chat.pop();
      state.chat.push({ role: "assistant", content: data.answer });
    } catch (err) {
      if (session !== chatSessionId) return;
      state.chat.pop();
      state.chat.push({ role: "assistant", content: "Tutor unavailable: " + err.message });
      // Same reasoning as visualize(): the failure usually means the badge
      // is now stale.
      refreshStatus();
    } finally {
      state.chatBusy = false;
      el.sendChat.disabled = false;
      renderChat();
    }
  }

  /* ============================================================== */
  /* Status                                                         */
  /* ============================================================== */

  async function refreshStatus() {
    try {
      const health = await fetch("/api/health").then((r) => r.json());
      state.health = health;
      const gen = health.generator;
      if (gen === "claude") {
        el.statusBadge.textContent = "Claude online";
        el.statusBadge.className = "status-pill ok";
        el.modelLabel.textContent = "Generator: " + (health.claude.model || "claude");
      } else if (gen === "openai") {
        el.statusBadge.textContent = "ChatGPT online";
        el.statusBadge.className = "status-pill ok";
        el.modelLabel.textContent = "Generator: " + (health.openai.model || "openai");
      } else if (gen === "gemini") {
        el.statusBadge.textContent = "Gemini online";
        el.statusBadge.className = "status-pill ok";
        el.modelLabel.textContent = "Generator: " + (health.gemini.model || "gemini");
      } else if (gen === "ollama") {
        el.statusBadge.textContent = "Local model";
        el.statusBadge.className = "status-pill ok";
        el.modelLabel.textContent = "Generator: " + (health.ollama.selected_model || "ollama");
      } else {
        el.statusBadge.textContent = "No generator";
        el.statusBadge.className = "status-pill error";
        el.modelLabel.textContent =
          "Set ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY or start Ollama";
      }
    } catch (err) {
      el.statusBadge.textContent = "Server offline";
      el.statusBadge.className = "status-pill error";
      el.modelLabel.textContent = "Could not reach the VisualLM server.";
    }
  }

  /* ============================================================== */
  /* Tabs (left panel)                                              */
  /* ============================================================== */

  function activateTab(name, focusActive) {
    const tabs = Array.from(document.querySelectorAll(".tab"));
    let activated = null;
    tabs.forEach((t) => {
      const active = t.dataset.tab === name;
      t.classList.toggle("active", active);
      t.setAttribute("aria-selected", active ? "true" : "false");
      // ARIA tablist: only the active tab is in the Tab order.
      t.tabIndex = active ? 0 : -1;
      if (active) activated = t;
    });
    document.querySelectorAll(".tab-panel").forEach((p) => {
      const active = p.dataset.panel === name;
      p.classList.toggle("active", active);
      if (active) p.removeAttribute("hidden");
      else p.setAttribute("hidden", "");
    });
    if (focusActive && activated) activated.focus();
  }

  (function wireTabs() {
    const tabs = Array.from(document.querySelectorAll(".tab"));
    // Initialize tabindex so only the currently-active tab is tabbable.
    tabs.forEach((t) => {
      t.tabIndex = t.classList.contains("active") ? 0 : -1;
    });
    tabs.forEach((tab, i) => {
      tab.addEventListener("click", () => activateTab(tab.dataset.tab));
      tab.addEventListener("keydown", (e) => {
        let nextIndex = null;
        if (e.key === "ArrowLeft" || e.key === "ArrowUp") nextIndex = i - 1;
        else if (e.key === "ArrowRight" || e.key === "ArrowDown") nextIndex = i + 1;
        else if (e.key === "Home") nextIndex = 0;
        else if (e.key === "End") nextIndex = tabs.length - 1;
        if (nextIndex === null) return;
        e.preventDefault();
        const target = tabs[((nextIndex % tabs.length) + tabs.length) % tabs.length];
        activateTab(target.dataset.tab, true);
      });
    });
  })();

  /* ============================================================== */
  /* Resources                                                      */
  /* ============================================================== */

  const resourceEl = {
    drop: $("dropZone"),
    file: $("resourceFileInput"),
    list: $("resourceList"),
    empty: $("resourceEmpty"),
    count: $("resourceCount"),
  };

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " ch";
    return (bytes / 1024).toFixed(1) + " KB";
  }

  function renderResources(resources) {
    const items = resources || [];
    resourceEl.list.innerHTML = "";
    if (items.length === 0) {
      resourceEl.list.hidden = true;
      resourceEl.empty.hidden = false;
      resourceEl.count.hidden = true;
      resourceEl.count.textContent = "0";
      return;
    }
    resourceEl.list.hidden = false;
    resourceEl.empty.hidden = true;
    resourceEl.count.hidden = false;
    resourceEl.count.textContent = String(items.length);

    items.forEach((r) => {
      const row = document.createElement("div");
      row.className = "resource-item";
      const info = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = r.name;
      const meta = document.createElement("span");
      meta.className = "resource-meta";
      meta.textContent = formatSize(r.size);
      info.appendChild(name);
      info.appendChild(meta);
      const del = document.createElement("button");
      del.className = "resource-delete";
      del.type = "button";
      del.textContent = "Remove";
      del.addEventListener("click", () => deleteResource(r.id));
      row.appendChild(info);
      row.appendChild(del);
      resourceEl.list.appendChild(row);
    });
  }

  async function fetchResources() {
    try {
      const data = await fetch("/api/resources").then((r) => r.json());
      renderResources(data.resources || []);
    } catch (err) {
      console.error("Failed to load resources:", err);
    }
  }

  async function uploadResource(file) {
    if (!file) return;
    if (file.size > 1_500_000) {
      alert(`"${file.name}" is too large. Max ~1.5 MB.`);
      return;
    }
    let text;
    try {
      text = await file.text();
    } catch (err) {
      alert(`Could not read "${file.name}".`);
      return;
    }
    try {
      // No retry: a connection-reset mid-response from a successful upload
      // would cause the retry to create a duplicate resource entry.
      const data = await postJSON(
        "/api/resources",
        { name: file.name, content: text },
        { retry: false },
      );
      renderResources(data.resources || []);
      // Server silently trims content > MAX_RESOURCE_CHARS (60k); tell the
      // user when that happens so they understand the model only sees a slice.
      if (data.resource && data.resource.truncated) {
        alert(
          `"${file.name}" was over the 60K-character limit and was truncated. ` +
            "Only the first 60K characters will be visible to the AI.",
        );
      }
    } catch (err) {
      alert("Upload failed: " + err.message);
    }
  }

  async function deleteResource(id) {
    try {
      const res = await fetch("/api/resources/" + encodeURIComponent(id), {
        method: "DELETE",
        headers: apiHeaders(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Delete failed.");
      renderResources(data.resources || []);
    } catch (err) {
      alert("Could not delete: " + err.message);
    }
  }

  if (resourceEl.drop) {
    resourceEl.file.addEventListener("change", (e) => {
      const files = Array.from(e.target.files || []);
      files.forEach(uploadResource);
      resourceEl.file.value = "";
    });

    ["dragenter", "dragover"].forEach((evt) => {
      resourceEl.drop.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        resourceEl.drop.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach((evt) => {
      resourceEl.drop.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        resourceEl.drop.classList.remove("dragover");
      });
    });
    resourceEl.drop.addEventListener("drop", (e) => {
      const files = Array.from((e.dataTransfer && e.dataTransfer.files) || []);
      files.forEach(uploadResource);
    });
  }

  /* ============================================================== */
  /* Wiring                                                         */
  /* ============================================================== */

  el.visualize.addEventListener("click", () => visualize(el.prompt.value));

  el.random.addEventListener("click", () => {
    const ideas = [
      "Show how a Fourier series builds a square wave from sine waves.",
      "Visualize Newton's method converging to a root.",
      "Animate gradient descent rolling down a 2D loss surface.",
      "Explain simple harmonic motion with a mass on a spring.",
      "Show the unit circle generating sine and cosine.",
      "Visualize an RC circuit charging a capacitor over time.",
      "Animate bubble sort on a small array of bars.",
      "Show a wave packet and how phase and group velocity differ.",
      "Explain the dot product as a projection between two vectors.",
      "Visualize a planet's elliptical orbit and Kepler's equal areas.",
    ];
    const pick = ideas[Math.floor(Math.random() * ideas.length)];
    el.prompt.value = pick;
    visualize(pick);
  });

  el.prompt.addEventListener("keydown", (e) => {
    // Skip if an IME is mid-composition — see Bug #41 in chat handler.
    if (e.isComposing || e.keyCode === 229) return;
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      visualize(el.prompt.value);
    }
  });

  el.playPause.addEventListener("click", () => {
    if (runner.paused) {
      runner.resume();
      el.playPause.textContent = "Pause";
    } else {
      runner.pause();
      el.playPause.textContent = "Play";
    }
  });

  function applySpeedFromSlider(v) {
    const label = v.toFixed(1) + "×";
    el.speedValue.textContent = label;
    // Screen readers read aria-valuetext instead of the raw number, so they
    // announce "1.5× speed" instead of just "1.5".
    el.speed.setAttribute("aria-valuetext", label + " speed");
    runner.setSpeed(v);
  }
  // Seed aria-valuetext for the initial slider value.
  applySpeedFromSlider(parseFloat(el.speed.value));
  el.speed.addEventListener("input", (e) => {
    applySpeedFromSlider(parseFloat(e.target.value));
  });

  // Mode picker (radiogroup): click + arrow-key keyboard navigation. ARIA
  // pattern is "only the checked radio is in the Tab order; arrows move
  // between options and check as they move."
  (function () {
    const buttons = Array.from(document.querySelectorAll(".mode-button"));
    function selectAt(index, focus) {
      const target = buttons[((index % buttons.length) + buttons.length) % buttons.length];
      buttons.forEach((b) => {
        b.classList.remove("active");
        b.setAttribute("aria-checked", "false");
        b.tabIndex = -1;
      });
      target.classList.add("active");
      target.setAttribute("aria-checked", "true");
      target.tabIndex = 0;
      state.mode = target.dataset.mode || "auto";
      if (focus) target.focus();
    }
    // Initialize tabindex so only the currently-active button is tabbable.
    buttons.forEach((b, i) => {
      b.tabIndex = b.classList.contains("active") ? 0 : -1;
      b.addEventListener("click", () => selectAt(i, false));
      b.addEventListener("keydown", (e) => {
        if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
          e.preventDefault();
          selectAt(i - 1, true);
        } else if (e.key === "ArrowRight" || e.key === "ArrowDown") {
          e.preventDefault();
          selectAt(i + 1, true);
        } else if (e.key === "Home") {
          e.preventDefault();
          selectAt(0, true);
        } else if (e.key === "End") {
          e.preventDefault();
          selectAt(buttons.length - 1, true);
        }
      });
    });
  })();

  document.querySelectorAll(".chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const prompt = btn.dataset.prompt;
      if (!prompt) return;
      el.prompt.value = prompt;
      visualize(prompt);
    });
  });

  el.chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const value = el.chatInput.value;
    // Don't clear the textarea if sendChat would early-return — the user's
    // typing would otherwise disappear silently (e.g. they pressed Enter
    // while a prior chat was still in flight, or with no text at all).
    if (!value.trim() || state.chatBusy) return;
    sendChat(value);
    el.chatInput.value = "";
  });

  el.chatInput.addEventListener("keydown", (e) => {
    // isComposing/keyCode===229 means an IME is mid-composition (CJK input
    // methods use Enter to confirm a character). Submitting on that Enter
    // would eat the in-progress composition.
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      el.chatForm.requestSubmit();
    }
  });

  /* ============================================================== */
  /* Theme toggle                                                   */
  /* ============================================================== */
  //
  // The initial theme is applied by an inline <script> in <head> so there's
  // no flash. Here we just wire up the toggle button to flip between dark
  // and light, persist the choice, and reflect it on <html data-theme>.

  const THEME_KEY = "visuallm-theme";
  const themeToggle = $("themeToggle");
  function syncThemeToggleLabel() {
    if (!themeToggle) return;
    // Label the button by the ACTION it will perform, not the current state —
    // SR users tab onto it and hear "Switch to light theme" so they know what
    // will happen on press. The static "Toggle light or dark theme" never
    // told them which state they were in or where the click would land.
    const isLight = document.documentElement.dataset.theme === "light";
    themeToggle.setAttribute(
      "aria-label",
      isLight ? "Switch to dark theme" : "Switch to light theme",
    );
  }
  syncThemeToggleLabel();
  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      const current = document.documentElement.dataset.theme || "dark";
      const next = current === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      syncThemeToggleLabel();
      try {
        localStorage.setItem(THEME_KEY, next);
      } catch (e) {
        /* private mode etc — non-fatal */
      }
    });
  }

  /* ============================================================== */
  /* Boot                                                           */
  /* ============================================================== */

  refreshStatus();
  fetchResources();
  state.chat = [
    {
      role: "assistant",
      content:
        "Type any STEM idea or equation and press Visualize. I'll generate a " +
        "custom animation, then answer questions about it here.",
    },
  ];
  renderChat();

  // NOTE: we intentionally do NOT auto-visualize on load. Every generation
  // costs an AI call (the operator's API credits on a public deployment),
  // so the first one should be a deliberate click.

  // Dev/test hook: run a scene straight through the sandbox from the console
  // (or automated tests) without an AI round-trip.
  window.__visuallm = {
    runScene: (code) => runner.run(code),
    runner,
    state,
  };
})();
