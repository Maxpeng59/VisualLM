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


if __name__ == "__main__":
    unittest.main()
