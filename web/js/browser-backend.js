/* VisualLM — browser backend shim.
 *
 * Intercepts window.fetch for /api/* routes so the UNMODIFIED desktop frontend
 * (app.js) runs with no Python server. Everything deterministic (chemistry,
 * 333 demos, 50 curated scenes, balancing) is answered locally; free-form AI
 * generation and the AI tutor return a friendly "use the desktop app" notice.
 *
 * Must load AFTER planner.js/chemistry.js/matching.js and BEFORE app.js.
 */
(function (global) {
  "use strict";

  const realFetch = global.fetch.bind(global);

  function json(obj, status) {
    return new Response(JSON.stringify(obj), {
      status: status || 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Inert in-browser resource store (no AI consumes it; keeps the UI working).
  const resources = [];
  let nextId = 1;

  function browserHealth() {
    return {
      generator: "browser",
      ok: true,
      browser: { engine: "client-side", features: ["chemistry", "demos", "scenes", "balancing"] },
      claude: { available: false }, openai: { available: false },
      gemini: { available: false },
    };
  }

  const TUTOR_NOTICE =
    "**The AI tutor runs in the desktop app.**\n\n" +
    "This is the free browser edition — it works entirely in your browser with no server, " +
    "so it can't run the AI tutor (that needs a model + API key on a server).\n\n" +
    "What *does* work here, instantly:\n" +
    "- **Molecules** — type a formula like `CH4`, `C6H6`, or `glucose` for a 3D structure.\n" +
    "- **Balancing** — type a reaction like `C3H8 + O2 -> CO2 + H2O`.\n" +
    "- **333 interactive demos** + **50 curated scenes** — name a topic (e.g. *quadratic vertex*, *projectile motion*).\n\n" +
    "For full AI generation and tutoring, run the desktop app (see the project README).";

  // The browser edition has no LLM, but every rendered scene carries its own
  // explanation (summary + key points + params) locally. So rather than always
  // returning the generic notice, answer questions about the CURRENT scene from
  // that data — this makes the Quick Questions genuinely functional offline.
  function buildOfflineAnswer(question, scene) {
    const q = (question || "").toLowerCase();
    const note =
      "\n\n*Browser edition — answered offline from this scene. " +
      "Full conversational AI tutoring is in the desktop app.*";

    // Step-by-step solving is deterministic and runs from the PROMPT box, not
    // the chat — point the student there (it works offline, no AI).
    if (/\bsolve\b|step[- ]?by[- ]?step|worked/.test(q)) {
      return (
        "**Step-by-step solutions run from the prompt box** (top-right), not the chat. " +
        "Type your actual problem there — e.g. `side a=12, b=14, angle A=40` or " +
        "`x^2 - 5x + 6 = 0` — and press **Visualize**. You'll get animated worked-solution " +
        "slides with your own numbers, fully offline." +
        note
      );
    }

    const hasScene =
      scene && (scene.summary || (scene.bullets && scene.bullets.length) || scene.title);
    if (!hasScene) return TUTOR_NOTICE;

    const title = scene.title ? "**" + scene.title + "**" : "**This scene**";

    // "What do the controls / sliders do?"
    if (
      /param|slider|control|value|knob|adjust|drag/.test(q) &&
      scene.params &&
      scene.params.length
    ) {
      const lines = scene.params.map(function (p) {
        return (
          "- **" + (p.label || p.name) + "** — from " + p.min + " to " + p.max +
          " (currently " + p.value + ")."
        );
      });
      return (
        title + " has " + scene.params.length + " live control" +
        (scene.params.length > 1 ? "s" : "") +
        " — drag any of them and the visualization updates instantly:\n\n" +
        lines.join("\n") + note
      );
    }

    // Everything else → explain the scene from its stored summary + key points.
    const parts = [title];
    if (/equation|formula|mean|rule/.test(q) && scene.equation) {
      parts.push("The rule on screen is `" + scene.equation + "`.");
    }
    if (scene.summary) parts.push(scene.summary);
    if (scene.bullets && scene.bullets.length) {
      parts.push(
        "**Key points:**\n" +
          scene.bullets.map(function (b) { return "- " + b; }).join("\n"),
      );
    }
    if (parts.length === 1) return TUTOR_NOTICE; // nothing scene-specific to add
    return parts.join("\n\n") + note;
  }

  /* ---- DLC (Downloadable Content) packs ------------------------------------
   * A DLC is a pack of demos (+ experiments). Official packs are lightweight
   * area-filter manifests (data/dlc/*.dlc.json) resolved against the built-in
   * demo index; custom / AI / user packs embed full demo objects and are stored
   * in localStorage. Everything here is offline; a pack's `code` only ever runs
   * in the sandboxed worker, exactly like any other demo. */
  const DLC_KEY = "visuallm-dlc-packs";

  function loadCustomPacks() {
    try {
      const arr = JSON.parse(localStorage.getItem(DLC_KEY) || "[]");
      return Array.isArray(arr) ? arr : [];
    } catch (e) {
      return [];
    }
  }
  function saveCustomPacks(packs) {
    try {
      localStorage.setItem(DLC_KEY, JSON.stringify(packs));
    } catch (e) {
      /* quota / private mode — non-fatal */
    }
  }

  // Validate an imported DLC. Returns { ok, errors[] }.
  function dlcValidate(obj) {
    const errors = [];
    if (!obj || typeof obj !== "object") return { ok: false, errors: ["Not a JSON object."] };
    if (String(obj.format || "").split("/")[0] !== "visuallm-dlc")
      errors.push('Missing or bad `format` (expected "visuallm-dlc/1").');
    if (!obj.id || typeof obj.id !== "string") errors.push("Missing `id`.");
    if (!obj.name || typeof obj.name !== "string") errors.push("Missing `name`.");
    const demos = Array.isArray(obj.demos) ? obj.demos : [];
    const exps = Array.isArray(obj.experiments) ? obj.experiments : [];
    const areas = Array.isArray(obj.areas) ? obj.areas : [];
    if (!demos.length && !exps.length && !areas.length)
      errors.push("Pack is empty (no demos, experiments, or areas).");
    // Every embedded item runs in the sandbox, so it needs an id + code.
    demos.concat(exps).forEach((d, i) => {
      if (!d || typeof d !== "object") { errors.push("Item " + i + " is not an object."); return; }
      if (!d.id) errors.push("Item " + i + " is missing `id`.");
      if (typeof d.code !== "string" || !d.code.trim())
        errors.push("Item " + (d.id || i) + " is missing animation `code`.");
    });
    return { ok: errors.length === 0, errors: errors };
  }

  function packMeta(p) {
    const areaCount = (p.areas && p.areas.length)
      ? global.VisualLMPlanner.getDemoIndex().filter((d) => p.areas.indexOf(d.area) >= 0).length
      : 0;
    return {
      id: p.id,
      name: p.name || p.id,
      description: p.description || "",
      category: p.category || "custom",
      icon: p.icon || (p.source === "official" ? "📦" : "🧩"),
      source: p.source || "user",
      demoCount: areaCount + (p.demos || []).length,
      experimentCount: (p.experiments || []).length,
    };
  }

  // Official pack manifests, loaded once from data/dlc/index.json.
  let officialPacksP = null;
  function officialPacks() {
    if (!officialPacksP) {
      officialPacksP = (async () => {
        try {
          const list = await realFetch("data/dlc/index.json").then((r) => (r.ok ? r.json() : []));
          const packs = await Promise.all(
            (list || []).map((f) =>
              realFetch("data/dlc/" + f).then((r) => (r.ok ? r.json() : null)).catch(() => null)),
          );
          return packs.filter(Boolean).map((p) => Object.assign({ source: "official" }, p));
        } catch (e) {
          return [];
        }
      })();
    }
    return officialPacksP;
  }

  // Resolve a pack into a browsable catalog: demo descriptors grouped by
  // area -> topic, plus experiments. Official packs pull descriptors from the
  // built-in index by `areas`; embedded demos come straight from the pack.
  async function packCatalog(pack) {
    const groups = {};
    const push = (area, topic, d) => {
      area = area || "General";
      topic = topic || "Demos";
      groups[area] = groups[area] || {};
      (groups[area][topic] = groups[area][topic] || []).push(d);
    };
    if (pack.areas && pack.areas.length) {
      const areaSet = pack.areas;
      for (const d of global.VisualLMPlanner.getDemoIndex()) {
        if (areaSet.indexOf(d.area) >= 0)
          push(d.area, d.topic, { id: d.id, title: d.title, equation: d.equation });
      }
    }
    (pack.demos || []).forEach((d) =>
      push(d.area, d.topic, { id: d.id, title: d.title, equation: d.equation }));
    const sections = Object.keys(groups)
      .sort()
      .map((area) => ({
        area,
        topics: Object.keys(groups[area])
          .sort()
          .map((topic) => ({ topic, demos: groups[area][topic] })),
      }));
    const experiments = (pack.experiments || []).map((e) => ({
      id: e.id,
      title: e.title,
      blurb: e.blurb || "",
    }));
    return {
      id: pack.id,
      name: pack.name,
      description: pack.description || "",
      icon: pack.icon || "📦",
      source: pack.source || "official",
      sections: sections,
      experiments: experiments,
    };
  }

  // Build a runnable scene for any demo/experiment id — a built-in demo (official
  // ref), or an embedded item inside an installed / official pack.
  async function resolveDemoScene(id) {
    const idx = global.VisualLMPlanner.getDemoIndex();
    const desc = idx.find((d) => d.id === id);
    if (desc) {
      const body = await global.VisualLMPlanner.fetchDemoBody(id);
      return global.VisualLMPlanner.demoScene(Object.assign({}, desc, body), desc.title);
    }
    const searchPacks = loadCustomPacks().concat(await officialPacks());
    for (const p of searchPacks) {
      const found = (p.demos || []).concat(p.experiments || []).find((d) => d.id === id);
      if (found) return global.VisualLMPlanner.demoScene(found, found.title);
    }
    return null;
  }

  async function handleApi(path, init) {
    const method = ((init && init.method) || "GET").toUpperCase();
    let body = {};
    if (init && init.body && typeof init.body === "string") {
      try { body = JSON.parse(init.body); } catch (e) { body = {}; }
    }

    if (path === "/api/health") return json(browserHealth());

    if (path === "/api/visualize" && method === "POST") {
      await global.VisualLMPlanner.ready;
      const scene = await global.VisualLMPlanner.plan(body.prompt || "", body.preferred_mode || "auto");
      return json(scene);
    }

    // No AI in the browser, so "repair" can't fix anything — echo the code back
    // unchanged, which trips app.js's unchanged-code guard -> graceful fallback.
    if (path === "/api/repair" && method === "POST") {
      return json({ code: body.code || "", engine: "browser", model: "browser" });
    }

    if (path === "/api/chat" && method === "POST") {
      return json({
        answer: buildOfflineAnswer(body.question || "", body.visualization || {}),
        model: "browser",
        engine: "browser",
      });
    }

    if (path === "/api/resources" && method === "GET") {
      return json({ resources: resources.slice() });
    }
    if (path === "/api/resources" && method === "POST") {
      const r = { id: String(nextId++), name: body.name || "file", chars: (body.content || "").length, truncated: false };
      resources.push(r);
      return json({ resources: resources.slice(), resource: r });
    }
    if (path.indexOf("/api/resources/") === 0 && method === "DELETE") {
      const id = decodeURIComponent(path.slice("/api/resources/".length));
      const i = resources.findIndex((r) => r.id === id);
      if (i >= 0) resources.splice(i, 1);
      return json({ resources: resources.slice() });
    }

    // ---- DLC / Study Packs ----
    if (path === "/api/packs" && method === "GET") {
      await global.VisualLMPlanner.ready;
      const off = (await officialPacks()).map(packMeta);
      const custom = loadCustomPacks().map(packMeta);
      return json({ packs: off.concat(custom) });
    }
    if (path === "/api/pack" && method === "POST") {
      await global.VisualLMPlanner.ready;
      const pack =
        (await officialPacks()).find((p) => p.id === body.id) ||
        loadCustomPacks().find((p) => p.id === body.id);
      if (!pack) return json({ error: "Pack not found." }, 404);
      return json(await packCatalog(pack));
    }
    if (path === "/api/demo" && method === "POST") {
      await global.VisualLMPlanner.ready;
      const scene = await resolveDemoScene(body.id);
      if (!scene) return json({ error: "Demo not found." }, 404);
      return json(scene);
    }
    if (path === "/api/dlc/import" && method === "POST") {
      const v = dlcValidate(body.dlc);
      if (!v.ok)
        return json({ error: "Invalid pack — " + v.errors.slice(0, 3).join(" "), errors: v.errors }, 400);
      const packs = loadCustomPacks().filter((p) => p.id !== body.dlc.id);
      packs.push(Object.assign({}, body.dlc, { source: "user" }));
      saveCustomPacks(packs);
      return json({ ok: true, pack: packMeta(Object.assign({ source: "user" }, body.dlc)) });
    }
    if (path === "/api/dlc/remove" && method === "POST") {
      saveCustomPacks(loadCustomPacks().filter((p) => p.id !== body.id));
      return json({ ok: true });
    }
    if (path === "/api/dlc/export" && method === "POST") {
      await global.VisualLMPlanner.ready;
      const pack =
        loadCustomPacks().find((p) => p.id === body.id) ||
        (await officialPacks()).find((p) => p.id === body.id);
      if (!pack) return json({ error: "Pack not found." }, 404);
      return json({ dlc: pack });
    }

    return json({ error: "Not available in the browser edition." }, 404);
  }

  global.fetch = function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    if (path.indexOf("/api/") === 0) return handleApi(path, init);
    return realFetch(input, init);
  };
})(typeof window !== "undefined" ? window : this);
