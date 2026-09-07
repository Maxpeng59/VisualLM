"""Contract tests for the browser language pack and localized markup."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class BrowserI18nTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("node is required for the i18n contract test")

    def test_every_markup_key_exists_in_every_language(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        html += (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        keys = sorted(set(re.findall(r'data-i18n(?:-placeholder|-aria-label)?="([^"]+)"', html)))
        script = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const keys = JSON.parse(process.argv[2]);
const document = {
  readyState: 'complete',
  documentElement: {},
  querySelectorAll: () => [],
  getElementById: () => null,
};
const window = { dispatchEvent: () => {} };
const context = {
  window, document, navigator: { language: 'en' },
  localStorage: { getItem: () => null, setItem: () => {} },
  CustomEvent: function CustomEvent() {}, console,
};
vm.runInNewContext(source, context);
const api = window.VisualLMI18n;
for (const code of ['en', 'zh', 'es', 'hi', 'fr', 'de']) {
  api.setLocale(code, false);
  for (const key of keys) {
    if (api.t(key) === key) throw new Error(`${code} is missing ${key}`);
  }
}
process.stdout.write(JSON.stringify({ languages: Object.keys(api.languages()), keys: keys.length }));
"""
        proc = subprocess.run(
            ["node", "-e", script, str(ROOT / "web" / "i18n.js"), json.dumps(keys)],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(proc.stdout)
        self.assertEqual(result["languages"], ["en", "zh", "es", "hi", "fr", "de"])
        self.assertGreaterEqual(result["keys"], 30)

    def test_both_editions_load_the_language_pack(self):
        desktop = (ROOT / "index.html").read_text(encoding="utf-8")
        browser = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('./web/i18n.js?v=1', desktop)
        self.assertIn('./i18n.js?v=1', browser)
        for code in ("zh", "es", "hi", "fr", "de"):
            self.assertIn(f'<option value="{code}">', desktop)
            self.assertIn(f'<option value="{code}">', browser)


if __name__ == "__main__":
    unittest.main()
