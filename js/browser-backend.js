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
      gemini: { available: false }, ollama: { available: false },
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

  async function handleApi(path, init) {
    const method = ((init && init.method) || "GET").toUpperCase();
    let body = {};
    if (init && init.body && typeof init.body === "string") {
      try { body = JSON.parse(init.body); } catch (e) { body = {}; }
    }

    if (path === "/api/health") return json(browserHealth());

    if (path === "/api/visualize" && method === "POST") {
      await global.VisualLMPlanner.ready;
      const scene = global.VisualLMPlanner.plan(body.prompt || "", body.preferred_mode || "auto");
      return json(scene);
    }

    // No AI in the browser, so "repair" can't fix anything — echo the code back
    // unchanged, which trips app.js's unchanged-code guard -> graceful fallback.
    if (path === "/api/repair" && method === "POST") {
      return json({ code: body.code || "", engine: "browser", model: "browser" });
    }

    if (path === "/api/chat" && method === "POST") {
      return json({ answer: TUTOR_NOTICE, model: "browser", engine: "browser" });
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

    return json({ error: "Not available in the browser edition." }, 404);
  }

  global.fetch = function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    if (path.indexOf("/api/") === 0) return handleApi(path, init);
    return realFetch(input, init);
  };
})(typeof window !== "undefined" ? window : this);
