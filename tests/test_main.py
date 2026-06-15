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

    def test_strips_import_lines(self):
        out = main.sanitize_code("import x from 'y';\nH.background();")
        self.assertNotIn("import", out)

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
        main.plan_visualization = lambda prompt, mode: fake
        try:
            status, body = self.request("POST", "/api/visualize", {"prompt": "p"})
        finally:
            main.plan_visualization = original
        self.assertEqual(status, 200)
        self.assertEqual(body["title"], "T")
        self.assertEqual(body["dimension"], "3D")

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
        def boom(prompt, mode):
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


if __name__ == "__main__":
    unittest.main()
