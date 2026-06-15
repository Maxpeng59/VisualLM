# stem-viz — a portable STEM-visualization skill + plugin

A self-contained capability pack that teaches any AI to turn a STEM question into
an **animated 2D/3D explanation**, and gives it the tools to run and verify the
result. Extracted from [VisualLM](https://github.com/Maxpeng59/VisualLM) so the
capability travels — as a **Claude Skill** (portable across Claude Code, the Agent
SDK, claude.ai, the Skills API) and as a **Claude Code plugin** (this folder).

## What's inside

```
stem-viz-plugin/
├── .claude-plugin/plugin.json      # plugin manifest (Claude Code installs this)
└── skills/stem-viz/                # the skill (portable on its own)
    ├── SKILL.md                    # the contract + workflow + when to use
    ├── references/
    │   ├── helper-api.md           # full H / plot2d / cam3d / surface3d / mesh3d API + output schema
    │   ├── examples.md             # 8 complete, validator-passing scenes (2D + 3D)
    │   ├── concepts.md             # concept → visualization playbook (ML/STEM topics → recipes)
    │   └── repair.md               # error-class → minimal-change self-repair protocol
    ├── runtime/
    │   ├── sandbox-worker.js       # the real rendering engine (Web Worker + OffscreenCanvas + H)
    │   ├── host.html               # minimal no-build page: paste a scene, watch it render
    │   └── README.md               # how to embed the runtime in any app
    └── scripts/
        └── validate_scene.js       # headless Node validator (run before shipping a scene)
```

The skill does three things, end to end:
1. **Generate** — write `scene(ctx, t, H)` animation code from a STEM prompt.
2. **Self-repair** — fix code that throws, by error class, with minimal edits.
3. **Teach** — map concepts (gradient descent, Fourier series, projectile motion…)
   to proven visual recipes.

…and bundles the **runtime** so generated scenes actually run outside VisualLM,
plus a **headless validator** so an agent can verify a scene in ~1s without a
browser.

## Use it as a Claude Code plugin

Add the marketplace (the repo or a local clone) and install:

```
/plugin marketplace add Maxpeng59/VisualLM      # or: add /path/to/VisualLM
/plugin install stem-viz
```

Once installed, the `stem-viz` skill triggers automatically when you ask to
visualize/animate/illustrate a STEM idea. (Claude Code discovers the skill under
`skills/` from the plugin manifest.)

## Use it as a standalone Skill

The `skills/stem-viz/` folder is a complete, portable skill — drop it into any
skills directory (Claude Code `~/.claude/skills/`, an Agent SDK skills path,
claude.ai, or the Skills API). Nothing in it depends on the plugin wrapper.

## Try the runtime right now

```bash
cd skills/stem-viz/runtime
python3 -m http.server 8000
# open http://localhost:8000/host.html — paste a scene from references/examples.md
```

## Validate a scene headlessly

```bash
node skills/stem-viz/scripts/validate_scene.js <<'SCENE'
H.background();
const v = H.plot2d({ xMin: -6, xMax: 6, yMin: -2, yMax: 2 });
v.grid(); v.axes();
v.fn(x => Math.sin(x + t), { color: H.colors.accent, width: 3 });
H.text("sine", 24, 30, { color: H.colors.ink, size: 18, weight: 700 });
SCENE
# → {"ok":true,"error":null,"painted":true,"text":true,"paint":N,"onscreen":true}
```

## Keeping it in sync

`runtime/sandbox-worker.js` (the engine), `scripts/validate_scene.js` (its mock),
and `references/helper-api.md` (the docs) describe the same `H` API. If you extend
the helper library, update all three together.

## License
MIT (matches VisualLM).
