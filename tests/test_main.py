"""Unit + endpoint tests for the VisualLM server.

Run with:  python3 -m unittest discover -s tests -v

Only the standard library is required, matching the server itself. Endpoint
tests run a real ThreadingHTTPServer on an ephemeral port with the generator
functions monkeypatched, so no AI backend is needed.
"""
from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
