"""Unit + endpoint tests for the VisualLM server.

Run with:  python3 -m unittest discover -s tests -v

Only the standard library is required, matching the server itself. Endpoint
tests run a real ThreadingHTTPServer on an ephemeral port with the generator
functions monkeypatched, so no AI backend is needed.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402


class LanguageTests(unittest.TestCase):
    def test_supported_language_codes(self):
        for code in ("en", "zh", "es", "hi", "fr", "de"):
            self.assertEqual(main.normalize_language(code), code)
        self.assertEqual(main.normalize_language("zh-CN"), "zh")
        self.assertEqual(main.normalize_language("unknown"), "en")

    def test_generation_prompt_requests_selected_language(self):
        prompt = main._prompt_for_language("Explain gravity", "de")
        self.assertTrue(prompt.startswith("Explain gravity"))
        self.assertIn("German", prompt)
        self.assertIn("learner-facing canvas text", prompt)
        self.assertEqual(main._prompt_for_language("Explain gravity", "en"), "Explain gravity")


class SanitizeCodeTests(unittest.TestCase):
    def test_strips_markdown_fence(self):
        code = "```js\nH.background();\n```"
        self.assertEqual(main.sanitize_code(code), "H.background();")

    def test_unwraps_scene_function(self):
        code = "function scene(ctx, t) {\nH.background();\nH.text('hi', 1, 2);\n}"
        out = main.sanitize_code(code)
        self.assertNotIn("function scene", out)
        self.assertIn("H.background();", out)

    def test_rewrites_reserved_bindings(self):
        out = main.sanitize_code("const W = H.W, H = H.H;")
        self.assertIn("_H = H.H", out)
        self.assertNotIn(", H =", out)

    def test_keeps_real_redeclarations_renamed(self):
        # Genuine TDZ/shadow declarations must still be renamed.
        self.assertEqual(main.sanitize_code("const W = H.W, H = H.H;"), "const W = H.W, _H = H.H;")
        self.assertEqual(main.sanitize_code("let H, ctx;"), "let _H, _ctx;")

    def test_does_not_rewrite_reserved_used_as_values(self):
        # t/H/ctx used as a VALUE inside a declaration's expression (after a
        # comma within ()/[]) is NOT a declarator — renaming it to _t/_H would
        # create an undefined reference and break a very common scene pattern.
        for code in (
            "const y = H.lerp(a, b, t);",
            "const p = [Math.cos(t), t];",
            "const v = H.map(x, 0, 10, t);",
            "const r = Math.sin(t);",
        ):
            self.assertEqual(main.sanitize_code(code), code)

    def test_strips_import_lines(self):
        out = main.sanitize_code("import x from 'y';\nH.background();")
        self.assertNotIn("import", out)

    def test_unwrap_handles_nested_braces_and_string_braces(self):
        # rfind('}') must land on the function's OWN closing brace even when the
        # body has nested blocks or a '}' inside a string literal.
        out = main.sanitize_code(
            "function scene(ctx, t) { const f = () => { return 1; }; H.circle(f(),1,2); }"
        )
        self.assertNotIn("function scene", out)
        self.assertIn("const f = () => { return 1; };", out)
        self.assertIn("H.circle(f(),1,2);", out)
        self.assertEqual(
            main.sanitize_code('function scene(ctx, t) { H.text("a } b", 1, 2); }'),
            'H.text("a } b", 1, 2);',
        )

    def test_fence_and_function_wrapper_both_stripped(self):
        self.assertEqual(
            main.sanitize_code("```js\nfunction scene(ctx, t) {\n  H.background();\n}\n```"),
            "H.background();",
        )

    def test_non_string_returns_empty(self):
        self.assertEqual(main.sanitize_code(None), "")
        self.assertEqual(main.sanitize_code(42), "")


class ExtractJsonTests(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(main._extract_json_object('{"a": 1}'), {"a": 1})

    def test_object_embedded_in_prose(self):
        raw = 'Sure! Here is the scene: {"title": "X", "code": "H.background();"} hope it helps'
        self.assertEqual(main._extract_json_object(raw)["title"], "X")

    def test_picks_first_parseable_of_multiple(self):
        raw = 'junk {not json} more {"ok": true} tail'
        self.assertEqual(main._extract_json_object(raw), {"ok": True})

    def test_braces_inside_strings(self):
        raw = '{"code": "if (x) { y(); }"}'
        self.assertEqual(main._extract_json_object(raw)["code"], "if (x) { y(); }")

    def test_no_object_raises(self):
        with self.assertRaises(json.JSONDecodeError):
            main._extract_json_object("no json here")


class PaintDetectionTests(unittest.TestCase):
    def test_2d_helpers_count(self):
        self.assertTrue(main.code_paints_something("H.background(); H.text('x',1,2);"))

    def test_new_3d_helpers_count(self):
        self.assertTrue(main.code_paints_something("H.surface3d(cam, f, {});"))
        self.assertTrue(main.code_paints_something("H.mesh3d(cam, f, {});"))
        self.assertTrue(main.code_paints_something("cam.sphere([0,0,0], 1, {});"))

    def test_setup_only_code_is_blank(self):
        self.assertFalse(main.code_paints_something("const a = 1; const b = a * 2;"))
        self.assertFalse(main.code_paints_something(""))


class QualityGateTests(unittest.TestCase):
    def test_animated_detection(self):
        self.assertTrue(main.code_is_animated("const a = Math.sin(t * 0.5);"))
        self.assertTrue(main.code_is_animated("cam.yaw = 0.3 * t;"))
        # identifiers merely containing "t" don't count
        self.assertFalse(main.code_is_animated("const theta = 1; tris.sort();"))
        self.assertFalse(main.code_is_animated(""))

    def test_label_detection(self):
        self.assertTrue(main.code_has_labels('H.text("v = 1", 1, 2);'))
        self.assertTrue(main.code_has_labels("H.legend([{label:'a',color:'red'}], 1, 2);"))
        self.assertFalse(main.code_has_labels("H.line(0,0,1,1);"))

    def test_scene_problems_tiers(self):
        self.assertEqual(main.scene_problems("const a = 1;"), ["blank"])
        good = 'H.background(); H.text("x = " + t.toFixed(1), 1, 2); H.line(0,0,1,1);'
        self.assertEqual(main.scene_problems(good), [])
        static_unlabeled = "H.background(); H.line(0,0,1,1); H.circle(1,2,3,{});"
        self.assertEqual(main.scene_problems(static_unlabeled), ["static", "unlabeled"])

    def test_try_generate_retries_with_feedback_then_succeeds(self):
        prompts_seen = []

        def fake_generator(prompt, mode):
            prompts_seen.append(prompt)
            if len(prompts_seen) == 1:
                return {"code": "H.background(); H.line(0,0,1,1); H.circle(1,2,3,{});"}
            return {"code": 'H.background(); H.line(0,0,1,1); H.text("v=" + t, 1, 2);'}

        scene = main._try_generate(fake_generator, "orig", "auto", "Test")
        self.assertEqual(scene["recovered_after_retry"], 1)
        self.assertNotIn("quality_warnings", scene)
        # The retry prompt must name the actual problems.
        self.assertIn("NOTHING MOVED", prompts_seen[1])
        self.assertIn("NO text labels", prompts_seen[1])

    def test_try_generate_ships_imperfect_scene_as_last_resort(self):
        def always_static(prompt, mode):
            return {"code": "H.background(); H.line(0,0,1,1); H.circle(1,2,3,{});"}

        scene = main._try_generate(always_static, "orig", "auto", "Test")
        self.assertEqual(scene["quality_warnings"], ["static", "unlabeled"])

    def test_try_generate_raises_after_three_blanks(self):
        def always_blank(prompt, mode):
            return {"code": "const a = 1;"}

        with self.assertRaises(RuntimeError):
            main._try_generate(always_blank, "orig", "auto", "Test")


class RepairHintTests(unittest.TestCase):
    def test_error_classes_get_specific_hints(self):
        self.assertIn("declared", main._repair_hint("ReferenceError: radius is not defined"))
        self.assertIn("real helper", main._repair_hint("TypeError: H.glow is not a function"))
        self.assertIn(
            "undefined/null",
            main._repair_hint("TypeError: Cannot read properties of undefined (reading 'x')"),
        )
        self.assertIn("parse", main._repair_hint("SyntaxError: Unexpected token '}'"))

    def test_every_hint_demands_a_minimal_change(self):
        for err in ["x is not defined", "boom", "", "Cannot read properties of null"]:
            self.assertIn("SMALLEST change", main._repair_hint(err))

    def test_handles_non_string_error(self):
        self.assertIn("SMALLEST change", main._repair_hint(None))


class RepairVisualizationTests(unittest.TestCase):
    """repair_visualization folds the sandbox's offending line into the error
    text handed to the provider, and leaves it clean when there's no location."""

    def _capture_repair_error(self, error, where):
        captured = {}

        def fake_repair(prompt, code, err):
            captured["error"] = err
            return {"code": "H.background(); H.text('x', 1, 2);", "engine": "claude"}

        orig_avail, orig_repair = main.claude_available, main.repair_with_claude
        main.claude_available = lambda: {"available": True}
        main.repair_with_claude = fake_repair
        try:
            main.repair_visualization("draw it", "H.circle(p.x,1,2);", error, where=where)
        finally:
            main.claude_available = orig_avail
            main.repair_with_claude = orig_repair
        return captured["error"]

    def test_offending_line_is_folded_in(self):
        err = self._capture_repair_error(
            "Cannot read properties of undefined", "line 5: H.circle(p.x, 1, 2)"
        )
        self.assertIn("Cannot read properties of undefined", err)
        self.assertIn("line 5: H.circle(p.x, 1, 2)", err)

    def test_no_where_leaves_error_clean(self):
        err = self._capture_repair_error("boom", "")
        self.assertEqual(err, "boom")


class NormalizeSceneTests(unittest.TestCase):
    def test_dimension_normalization(self):
        scene = main.normalize_scene({"dimension": "3d surface"}, "p")
        self.assertEqual(scene["dimension"], "3D")
        scene = main.normalize_scene({"dimension": "anything else"}, "p")
        self.assertEqual(scene["dimension"], "2D")

    def test_defaults_fill_missing_fields(self):
        scene = main.normalize_scene({}, "my prompt")
        self.assertTrue(scene["title"])
        self.assertEqual(len(scene["bullets"]), 3)
        self.assertEqual(scene["prompt"], "my prompt")

    def test_code_is_sanitized(self):
        scene = main.normalize_scene({"code": "```\nH.background();\n```"}, "p")
        self.assertEqual(scene["code"], "H.background();")


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        main._rate_hits.clear()
        self._old = main.RATE_LIMIT_PER_MIN
        main.RATE_LIMIT_PER_MIN = 3

    def tearDown(self):
        main.RATE_LIMIT_PER_MIN = self._old
        main._rate_hits.clear()

    def test_allows_under_limit_blocks_over(self):
        for _ in range(3):
            self.assertTrue(main.rate_limit_ok("1.2.3.4", now=1000.0))
        self.assertFalse(main.rate_limit_ok("1.2.3.4", now=1000.0))

    def test_window_slides(self):
        for _ in range(3):
            self.assertTrue(main.rate_limit_ok("1.2.3.4", now=1000.0))
        self.assertTrue(main.rate_limit_ok("1.2.3.4", now=1061.0))

    def test_ips_are_independent(self):
        for _ in range(3):
            main.rate_limit_ok("a", now=1000.0)
        self.assertTrue(main.rate_limit_ok("b", now=1000.0))

    def test_zero_disables(self):
        main.RATE_LIMIT_PER_MIN = 0
        for _ in range(50):
            self.assertTrue(main.rate_limit_ok("x", now=1000.0))


class AccessCodeTests(unittest.TestCase):
    def tearDown(self):
        main.ACCESS_CODE = ""

    def test_open_when_unset(self):
        main.ACCESS_CODE = ""
        self.assertTrue(main.access_code_ok(None))
        self.assertTrue(main.access_code_ok("anything"))

    def test_enforced_when_set(self):
        main.ACCESS_CODE = "sesame"
        self.assertTrue(main.access_code_ok("sesame"))
        self.assertTrue(main.access_code_ok("  sesame  "))
        self.assertFalse(main.access_code_ok("wrong"))
        self.assertFalse(main.access_code_ok(None))


class EndpointTests(unittest.TestCase):
    """Real HTTP round-trips against a server on an ephemeral port."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), main.VisualLMHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        main._rate_hits.clear()
        main.ACCESS_CODE = ""
        with main._resources_lock:
            main._resources.clear()

    def request(self, method, path, body=None, headers=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_unknown_api_route_404(self):
        status, _ = self.request("POST", "/api/nope", {})
        self.assertEqual(status, 404)

    def test_visualize_requires_prompt(self):
        status, body = self.request("POST", "/api/visualize", {"prompt": "  "})
        self.assertEqual(status, 400)
        self.assertIn("prompt", body["error"])

    def test_non_object_body_400(self):
        status, _ = self.request("POST", "/api/visualize", ["not", "an", "object"])
        self.assertEqual(status, 400)

    def test_visualize_happy_path_with_stubbed_generator(self):
        fake = main.normalize_scene(
            {"title": "T", "dimension": "3D", "code": "H.background(); H.text('x',1,2); H.line(0,0,1,1);"},
            "p",
        )
        original = main.plan_visualization
        received = {}
        def fake_plan(prompt, mode, language="en"):
            received.update(prompt=prompt, mode=mode, language=language)
            return fake
        main.plan_visualization = fake_plan
        try:
            status, body = self.request(
                "POST", "/api/visualize", {"prompt": "p", "language": "fr"}
            )
        finally:
            main.plan_visualization = original
        self.assertEqual(status, 200)
        self.assertEqual(body["title"], "T")
        self.assertEqual(body["dimension"], "3D")
        self.assertEqual(received, {"prompt": "p", "mode": "auto", "language": "fr"})

    def test_access_code_gate(self):
        main.ACCESS_CODE = "sesame"
        status, body = self.request("POST", "/api/visualize", {"prompt": "p"})
        self.assertEqual(status, 401)
        self.assertTrue(body.get("code_required"))
        # Correct code passes the gate (and then fails validation, not auth).
        status, _ = self.request(
            "POST", "/api/visualize", {"prompt": ""}, headers={"X-Access-Code": "sesame"}
        )
        self.assertEqual(status, 400)

    def test_rate_limit_429(self):
        old = main.RATE_LIMIT_PER_MIN
        main.RATE_LIMIT_PER_MIN = 2
        try:
            self.request("POST", "/api/visualize", {"prompt": ""})
            self.request("POST", "/api/visualize", {"prompt": ""})
            status, body = self.request("POST", "/api/visualize", {"prompt": ""})
        finally:
            main.RATE_LIMIT_PER_MIN = old
        self.assertEqual(status, 429)
        self.assertIn("Rate limit", body["error"])

    def test_resources_crud(self):
        status, body = self.request(
            "POST", "/api/resources", {"name": "notes.md", "content": "E = mc^2"}
        )
        self.assertEqual(status, 200)
        rid = body["resource"]["id"]
        self.assertEqual(len(body["resources"]), 1)

        status, body = self.request("DELETE", f"/api/resources/{rid}")
        self.assertEqual(status, 200)
        self.assertEqual(body["resources"], [])

    def test_resource_rejects_binary(self):
        status, body = self.request(
            "POST", "/api/resources", {"name": "blob.bin", "content": "\x00\x01\x02" * 200}
        )
        self.assertEqual(status, 400)
        self.assertIn("binary", body["error"].lower())

    def test_handler_exception_returns_500(self):
        # An UNEXPECTED exception in a handler (not the RuntimeError that
        # handlers already convert to 503) must come back as a clean 500, not a
        # dropped connection. stderr is suppressed because the guard logs the
        # traceback by design.
        def boom(prompt, mode, language="en"):
            raise ValueError("unexpected handler bug")

        original = main.plan_visualization
        main.plan_visualization = boom
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                status, body = self.request("POST", "/api/visualize", {"prompt": "p"})
        finally:
            main.plan_visualization = original
        self.assertEqual(status, 500)
        self.assertIn("error", body)


class AutofixTests(unittest.TestCase):
    def test_prefixes_bare_math(self):
        out = main.autofix_code("r = sqrt(x*x) + sin(t) + abs(v);")
        self.assertIn("Math.sqrt(", out)
        self.assertIn("Math.sin(", out)
        self.assertIn("Math.abs(", out)

    def test_bare_constants(self):
        self.assertIn("Math.PI", main.autofix_code("a = 2 * PI;"))
        self.assertIn("H.TAU", main.autofix_code("a = TAU;"))

    def test_does_not_touch_qualified_or_user_names(self):
        out = main.autofix_code("Math.sin(x); obj.max(1,2); mySin(3); api(1);")
        self.assertEqual(out, "Math.sin(x); obj.max(1,2); mySin(3); api(1);")

    def test_skips_strings_and_comments(self):
        out = main.autofix_code('H.text("use sin(x) here"); // call cos(y)\nr = sin(z);')
        self.assertIn('"use sin(x) here"', out)   # string untouched
        self.assertIn("// call cos(y)", out)       # comment untouched
        self.assertIn("Math.sin(z)", out)          # real call fixed

    def test_idempotent(self):
        once = main.autofix_code("r = sqrt(2);")
        self.assertEqual(once, main.autofix_code(once))

    def test_does_not_corrupt_locally_declared_names(self):
        # A scene that declares its own PI/TAU/function must be left intact —
        # rewriting `const PI` -> `const Math.PI` is a syntax error, and a local
        # `log(...)` is the scene's function, not Math.log.
        self.assertEqual(
            main.autofix_code("const PI = Math.PI; const r = PI * 2;"),
            "const PI = Math.PI; const r = PI * 2;",
        )
        self.assertEqual(
            main.autofix_code("const TAU = 6.28; const a = TAU;"),
            "const TAU = 6.28; const a = TAU;",
        )
        out = main.autofix_code("const log = (x) => x + 1; const y = log(5);")
        self.assertNotIn("Math.log", out)
        # ...but a genuinely bare call/constant (no local decl) is still fixed.
        self.assertIn("Math.sin(", main.autofix_code("r = sin(t);"))
        self.assertIn("Math.PI", main.autofix_code("a = 2 * PI;"))

    def test_sanitize_runs_autofix(self):
        self.assertIn("Math.sin", main.sanitize_code("H.background(); const y = sin(t);"))


@unittest.skipUnless(main.node_validator_available(), "node validator not installed")
class HeadlessValidatorTests(unittest.TestCase):
    def test_valid_scene_passes(self):
        r = main.headless_validate(
            'H.background(); const v = H.plot2d({}); v.grid(); v.axes();'
            ' v.fn(x => Math.sin(x + t)); H.text("t=" + t, 24, 30, {});'
        )
        self.assertTrue(r["ok"])
        self.assertTrue(r["painted"])
        self.assertTrue(r["text"])

    def test_runtime_throw_caught(self):
        r = main.headless_validate("H.background(); const a = nope.bar; H.text('x',1,2,{});")
        self.assertFalse(r["ok"])
        self.assertIn("nope", r["error"])

    def test_blank_detected(self):
        r = main.headless_validate("const a = 1; const b = a * 2;")
        self.assertTrue(r["ok"])
        self.assertFalse(r["painted"])

    def test_infinite_loop_is_killed(self):
        r = main.headless_validate("H.background(); while (true) {}")
        self.assertFalse(r["ok"])
        self.assertIn("hung", r["error"].lower())

    def test_const_v_shadow_does_not_collide(self):
        # The whole reason H/cam/view/v are globals, not params.
        r = main.headless_validate(
            'H.background(); const v = H.plot2d({}); v.grid(); v.axes(); v.fn(x=>x); H.text("x",1,2,{});'
        )
        self.assertTrue(r["ok"])

    def test_offscreen_draws_detected(self):
        # The classic data-vs-pixel mixup: wrapping data-space v.line args in
        # v.X()/v.Y() double-maps them off the canvas. Runs fine, paints, but
        # nothing is visible.
        r = main.headless_validate(
            "const v = H.plot2d({xMin:-5,xMax:5,yMin:-5,yMax:5}); v.grid(); v.axes();"
            " v.line(v.X(0), v.Y(0), v.X(3), v.Y(3), {}); v.text('t', 24, 30, {});"
        )
        self.assertTrue(r["ok"])
        self.assertTrue(r["painted"])
        self.assertFalse(r["onscreen"])

    def test_onscreen_content_passes(self):
        r = main.headless_validate(
            "const v = H.plot2d({xMin:-5,xMax:5,yMin:-5,yMax:5}); v.grid(); v.axes();"
            " v.line(0, 0, 3, 3, {}); H.text('t', 24, 30, {});"
        )
        self.assertTrue(r["onscreen"])

    def test_unbounded_drift_off_screen_detected(self):
        # pos = t*4 with no loop: by the late frame the moving content has
        # sailed off the canvas and never returns.
        r = main.headless_validate(
            "const v = H.plot2d({xMin:-10,xMax:10,yMin:-5,yMax:5}); v.grid(); v.axes();"
            " const pos = t*4; for (let i=-5;i<=5;i++){ v.dot(pos+i, 0, {}); }"
            " v.text('x='+pos.toFixed(1), v.X(pos), v.Y(2), {});"
        )
        self.assertTrue(r["ok"])
        self.assertFalse(r["onscreen"])

    def test_looping_motion_stays_on_screen(self):
        r = main.headless_validate(
            "const v = H.plot2d({xMin:-10,xMax:10,yMin:-5,yMax:5}); v.grid(); v.axes();"
            " const pos = ((t*4+10)%20)-10; for (let i=-3;i<=3;i++){ v.dot(pos+i*0.3, 0, {}); }"
            " H.text('looping', 24, 30, {});"
        )
        self.assertTrue(r["onscreen"])

    def test_drifting_subject_with_fixed_labels_detected(self):
        # The hard case from the live Doppler run: a moving subject
        # (xSource = -3*t) drifts off, but fixed annotations (title, origin
        # marker) remain. On-screen content COLLAPSES from abundant early to
        # sparse late — caught even though a few fixed elements stay visible.
        r = main.headless_validate(
            "const v = H.plot2d({xMin:-10,xMax:10,yMin:-5,yMax:5}); v.grid(); v.axes();"
            " const xs = -3*t; v.dot(0,0,{});"
            " for (let i=-3;i<=3;i++){ const x=xs+i*2; if(x>=-10&&x<=10) v.line(x,-0.5,x,0.5,{}); }"
            " v.dot(xs,0,{}); v.text('x='+xs.toFixed(1), v.X(xs), v.Y(-0.5), {});"
            " H.text('Doppler', 24, 30, {});"
        )
        self.assertTrue(r["ok"])
        self.assertFalse(r["onscreen"])

    def test_host_escape_is_contained(self):
        # process must be unreachable inside the sandbox.
        r = main.headless_validate(
            'H.background(); const p = ({}).constructor.constructor("return typeof process")();'
            ' H.text(""+p, 1, 2, {}); H.line(0,0,1,1,{}); H.circle(1,1,1,{});'
        )
        self.assertTrue(r["ok"])  # didn't crash, and couldn't reach process


class EvaluateSceneTests(unittest.TestCase):
    """evaluate_scene with the validator forced on/off via monkeypatch, so the
    behaviour is deterministic regardless of whether node is installed."""

    def setUp(self):
        self._orig = main.headless_validate

    def tearDown(self):
        main.headless_validate = self._orig

    def test_fatal_on_runtime_error(self):
        main.headless_validate = lambda code, timeout=6.0: {"ok": False, "error": "boom", "painted": False, "text": False}
        ev = main.evaluate_scene("whatever")
        self.assertTrue(ev["fatal"])
        self.assertIn("boom", ev["error"])

    def test_fatal_on_blank(self):
        main.headless_validate = lambda code, timeout=6.0: {"ok": True, "error": None, "painted": False, "text": False}
        ev = main.evaluate_scene("H.clear();")
        self.assertTrue(ev["fatal"])

    def test_static_and_unlabeled(self):
        main.headless_validate = lambda code, timeout=6.0: {"ok": True, "error": None, "painted": True, "text": False}
        ev = main.evaluate_scene("H.background(); H.line(0,0,1,1,{});")  # no t, no text
        self.assertFalse(ev["fatal"])
        self.assertEqual(set(ev["problems"]), {"static", "unlabeled"})

    def test_clean_scene(self):
        main.headless_validate = lambda code, timeout=6.0: {"ok": True, "error": None, "painted": True, "text": True, "onscreen": True}
        ev = main.evaluate_scene('H.background(); H.text("t="+t,1,2,{});')
        self.assertFalse(ev["fatal"])
        self.assertEqual(ev["problems"], [])

    def test_fatal_on_offscreen(self):
        main.headless_validate = lambda code, timeout=6.0: {"ok": True, "error": None, "painted": True, "text": True, "onscreen": False}
        ev = main.evaluate_scene("v.line(v.X(0),v.Y(0),v.X(3),v.Y(3),{});")
        self.assertTrue(ev["fatal"])
        self.assertIn("OFF-SCREEN", ev["error"])

    def test_falls_back_to_static_gate_without_node(self):
        main.headless_validate = lambda code, timeout=6.0: None
        self.assertTrue(main.evaluate_scene("const a = 1;")["fatal"])  # blank → fatal
        self.assertEqual(main.evaluate_scene('H.background(); H.text("t="+t,1,2); H.line(0,0,1,1);')["problems"], [])


class SceneCacheTests(unittest.TestCase):
    def setUp(self):
        with main._scene_cache_lock:
            main._scene_cache.clear()

    def tearDown(self):
        with main._scene_cache_lock:
            main._scene_cache.clear()

    def test_roundtrip_and_normalization(self):
        scene = {"title": "T", "code": "H.background();"}
        main.scene_cache_put("Show A Wave", "auto", scene)
        # case/whitespace-insensitive key
        hit = main.scene_cache_get("  show a   wave ", "auto")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["title"], "T")

    def test_does_not_cache_imperfect_or_fallback(self):
        main.scene_cache_put("p", "auto", {"title": "x", "is_fallback": True})
        main.scene_cache_put("q", "auto", {"title": "y", "quality_warnings": ["static"]})
        self.assertIsNone(main.scene_cache_get("p", "auto"))
        self.assertIsNone(main.scene_cache_get("q", "auto"))

    def test_mode_is_part_of_key(self):
        main.scene_cache_put("orbit", "2d", {"title": "flat"})
        self.assertIsNone(main.scene_cache_get("orbit", "3d"))


class LibraryMatchTests(unittest.TestCase):
    def test_strong_match(self):
        # The library may hold more than one Fourier scene (hand-written +
        # workflow-generated); any of them is a correct match for this prompt.
        sc, score = main.library_match("show a fourier series building a square wave", "auto")
        self.assertIsNotNone(sc)
        self.assertIn("fourier", sc["id"])
        self.assertGreaterEqual(score, 3.0)

    def test_no_match_for_unrelated(self):
        sc, score = main.library_match("my favorite pasta recipe", "auto")
        self.assertEqual(score, 0.0)
        self.assertIsNone(sc)

    def test_mode_mismatch_penalized(self):
        # dna-double-helix is 3D; forcing 2D should drop its score.
        _, s3 = main.library_match("dna double helix", "3d")
        _, s2 = main.library_match("dna double helix", "2d")
        self.assertGreater(s3, s2)

    def test_every_library_scene_is_runnable(self):
        if not main.node_validator_available():
            self.skipTest("node validator not installed")
        for sc in main.SCENE_LIBRARY:
            r = main.headless_validate(sc["code"])
            self.assertIsNotNone(r, sc["id"])
            self.assertTrue(r["ok"], f"{sc['id']} threw: {r.get('error')}")
            self.assertTrue(r["painted"], f"{sc['id']} drew nothing")
            self.assertTrue(r["text"], f"{sc['id']} had no labels")


class DemoLibraryTests(unittest.TestCase):
    """The parameterized 'fill in the values' curriculum demos."""

    def test_library_nonempty(self):
        self.assertGreater(len(main.DEMO_LIBRARY), 0)

    def test_each_demo_well_formed(self):
        seen_ids = set()
        for d in main.DEMO_LIBRARY:
            did = d.get("id")
            self.assertTrue(did, "demo missing id")
            self.assertNotIn(did, seen_ids, f"duplicate demo id {did}")
            seen_ids.add(did)
            for key in ("title", "area", "topic", "explanation", "code", "keywords", "params"):
                self.assertIn(key, d, f"{did} missing {key}")
            self.assertTrue(d["code"].strip(), f"{did} has empty code")
            self.assertTrue(d["explanation"].strip(), f"{did} has no explanation")
            self.assertTrue(d["params"], f"{did} has no params to fill in")
            for p in d["params"]:
                for key in ("name", "label", "min", "max", "step", "value"):
                    self.assertIn(key, p, f"{did}.{p.get('name')} missing {key}")
                self.assertLessEqual(p["min"], p["value"], f"{did}.{p['name']} value < min")
                self.assertLessEqual(p["value"], p["max"], f"{did}.{p['name']} value > max")
                self.assertGreater(p["step"], 0, f"{did}.{p['name']} step must be > 0")
                # The code must actually read the parameter (P.<name>).
                self.assertIn(f"P.{p['name']}", d["code"], f"{did} never reads P.{p['name']}")

    def test_every_demo_is_runnable(self):
        if not main.node_validator_available():
            self.skipTest("node validator not installed")
        for d in main.DEMO_LIBRARY:
            code = main.sanitize_code(d["code"])
            r = main.headless_validate(code)
            self.assertIsNotNone(r, d["id"])
            self.assertTrue(r["ok"], f"{d['id']} threw: {r.get('error')}")
            self.assertTrue(r["painted"], f"{d['id']} drew nothing")
            self.assertTrue(r["text"], f"{d['id']} had no labels")

    def test_match_routes_curriculum_prompt(self):
        cases = [
            ("slope intercept form of a line", "linear-slope-intercept"),
            ("graph a quadratic and show the vertex", "quadratic-vertex"),
            ("discriminant of a quadratic equation", "quadratic-discriminant"),
            ("exponential growth and decay", "exponential-growth-decay"),
            ("unit circle with degrees", "unit-circle"),
            ("sine wave amplitude and period", "sine-wave"),
        ]
        for prompt, expected in cases:
            d, score = main.demo_match(prompt)
            self.assertIsNotNone(d, prompt)
            self.assertEqual(d["id"], expected, prompt)
            self.assertGreaterEqual(score, main._DEMO_THRESHOLD, prompt)

    def test_no_match_for_unrelated(self):
        d, score = main.demo_match("my favorite pasta recipe")
        self.assertIsNone(d)
        self.assertEqual(score, 0.0)

    def test_demo_scene_shape(self):
        d, _ = main.demo_match("slope intercept form of a line")
        scene = main._demo_scene(d, "slope intercept form of a line")
        self.assertTrue(scene["from_demo"])
        self.assertEqual(scene["engine"], "demo")
        self.assertTrue(scene["code"].strip())
        self.assertTrue(scene["explanation"].strip())
        self.assertTrue(scene["params"])
        self.assertIn(scene["dimension"], ("2D", "3D"))
        # params must be copies, not aliases into the library (UI mutates them).
        self.assertIsNot(scene["params"][0], d["params"][0])

    def test_plan_routes_to_demo(self):
        # A clear topic prompt should resolve to the interactive demo before any
        # network/generative path (demo check sits after the exact-prompt cache).
        plan = main.plan_visualization("show me slope intercept form of a line", "auto")
        self.assertTrue(plan.get("from_demo"), plan.get("engine"))
        self.assertEqual(plan["demo_id"], "linear-slope-intercept")


import chemistry  # noqa: E402


class ChemistryFormulaTests(unittest.TestCase):
    def test_parse_simple(self):
        self.assertEqual(chemistry.parse_formula("H2O"), {"H": 2, "O": 1})
        self.assertEqual(chemistry.parse_formula("C6H12O6"), {"C": 6, "H": 12, "O": 6})

    def test_parse_parentheses(self):
        self.assertEqual(chemistry.parse_formula("Ca(OH)2"), {"Ca": 1, "O": 2, "H": 2})

    def test_parse_strips_charge(self):
        self.assertEqual(chemistry.parse_formula("SO4^2-"), {"S": 1, "O": 4})
        self.assertEqual(chemistry.parse_formula("NH4+"), {"N": 1, "H": 4})

    def test_parse_rejects_nonformula(self):
        self.assertIsNone(chemistry.parse_formula("xyz"))
        self.assertIsNone(chemistry.parse_formula("2H2O"))  # leading coefficient
        self.assertIsNone(chemistry.parse_formula(""))


class ChemistryBalanceTests(unittest.TestCase):
    def test_combustion_propane(self):
        self.assertEqual(
            chemistry.balance_equation(["C3H8", "O2"], ["CO2", "H2O"]), [1, 5, 3, 4]
        )

    def test_water_synthesis(self):
        self.assertEqual(chemistry.balance_equation(["H2", "O2"], ["H2O"]), [2, 1, 2])

    def test_rust(self):
        self.assertEqual(chemistry.balance_equation(["Fe", "O2"], ["Fe2O3"]), [4, 3, 2])

    def test_redox_permanganate(self):
        # A genuinely hard balance — exercises the rational null-space solver.
        self.assertEqual(
            chemistry.balance_equation(
                ["KMnO4", "HCl"], ["KCl", "MnCl2", "H2O", "Cl2"]
            ),
            [2, 16, 2, 2, 8, 5],
        )

    def test_unbalanceable_returns_none(self):
        # No carbon source for the product — mass can't be conserved.
        self.assertIsNone(chemistry.balance_equation(["H2", "O2"], ["CO2"]))


class ChemistryVseprTests(unittest.TestCase):
    def test_known_shapes(self):
        cases = {
            "CH4": "tetrahedral",
            "NH3": "trigonal pyramidal",
            "H2O": "bent",
            "SF6": "octahedral",
            "PCl5": "trigonal bipyramidal",
            "BF3": "trigonal planar",
            "BeCl2": "linear",
            "XeF4": "square planar",
        }
        for formula, shape in cases.items():
            mol = chemistry.vsepr_molecule(formula)
            self.assertIsNotNone(mol, formula)
            self.assertEqual(mol["shape"], shape, formula)
            counts = chemistry.parse_formula(formula)
            self.assertEqual(len(mol["atoms"]), sum(counts.values()), formula)

    def test_co2_not_vsepr(self):
        # CO2 has double bonds — not the single-bond hydride/halide VSEPR path.
        self.assertIsNone(chemistry.vsepr_molecule("CO2"))


class ChemistryDetectionTests(unittest.TestCase):
    def test_formula_is_molecule(self):
        self.assertEqual(chemistry.detect_chemistry("CH4"), ("molecule", "CH4"))

    def test_reaction_is_balance(self):
        kind, payload = chemistry.detect_chemistry("2H2 + O2 -> 2H2O")
        self.assertEqual(kind, "balance")
        self.assertEqual(payload, (["H2", "O2"], ["H2O"]))

    def test_balance_command_prefix(self):
        kind, payload = chemistry.detect_chemistry("balance Fe + O2 -> Fe2O3")
        self.assertEqual(kind, "balance")
        self.assertEqual(payload, (["Fe", "O2"], ["Fe2O3"]))

    def test_bare_name(self):
        self.assertEqual(chemistry.detect_chemistry("benzene"), ("molecule", "benzene"))

    def test_does_not_hijack_math_or_physics(self):
        for p in [
            "Explain heat diffusion across a metal plate",
            "y = sin(x) + 0.35 sin(3x)",
            "derivative of x^2",
            "Show a projectile launched at 22 m/s",
            "x = 5",
        ]:
            self.assertIsNone(chemistry.detect_chemistry(p), p)

    def test_ambiguous_word_needs_cue(self):
        self.assertIsNone(chemistry.detect_chemistry("water"))
        self.assertEqual(
            chemistry.detect_chemistry("structure of water"), ("molecule", "water")
        )


class ChemistrySceneTests(unittest.TestCase):
    def test_molecule_scene_shape(self):
        sc = chemistry.chemistry_scene("CH4")
        self.assertEqual(sc["kind"], "molecule")
        self.assertEqual(sc["dimension"], "3D")
        for needle in ("H.background", "cam.sphere", "H.text"):
            self.assertIn(needle, sc["code"])

    def test_balance_scene_shape(self):
        sc = chemistry.chemistry_scene("C3H8 + O2 -> CO2 + H2O")
        self.assertEqual(sc["kind"], "balance")
        self.assertIn("5", sc["equation"])  # balanced coefficient present
        self.assertIn("H.background", sc["code"])

    def test_plan_routes_formula_to_chemistry(self):
        plan = main.plan_visualization("CH4", "auto")
        self.assertTrue(plan.get("from_chemistry"), plan.get("engine"))
        self.assertEqual(plan["chem_kind"], "molecule")
        self.assertEqual(plan["engine"], "chemistry")

    def test_plan_routes_reaction_to_chemistry(self):
        plan = main.plan_visualization("2H2 + O2 -> 2H2O", "auto")
        self.assertTrue(plan.get("from_chemistry"))
        self.assertEqual(plan["chem_kind"], "balance")

    def test_plan_does_not_hijack_physics(self):
        plan = main.plan_visualization("Show a projectile launched at 22 m/s", "auto")
        self.assertFalse(plan.get("from_chemistry"))

    def test_every_library_molecule_renders(self):
        # Each curated molecule's rendered scene must run, paint, and label.
        if not main.node_validator_available():
            self.skipTest("node validator not installed")
        for canon in chemistry.MOLECULES:
            mol = chemistry.lookup_molecule(chemistry.MOLECULES[canon].get("formula", canon))
            self.assertIsNotNone(mol, canon)
            code = main.sanitize_code(chemistry._molecule_code(mol))
            r = main.headless_validate(code)
            self.assertIsNotNone(r, canon)
            self.assertTrue(r["ok"], f"{canon} threw: {r.get('error')}")
            self.assertTrue(r["painted"], f"{canon} drew nothing")
            self.assertTrue(r["text"], f"{canon} had no labels")


if __name__ == "__main__":
    unittest.main()
