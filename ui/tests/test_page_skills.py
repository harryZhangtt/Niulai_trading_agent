"""Behavioral checks for the locally adapted landing-page generator."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ui/skills/landing-page-generator/scripts/landing_page_scaffolder.py"
spec = importlib.util.spec_from_file_location("landing_page_skill", SCRIPT)
landing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(landing)


class LandingPageSkillTests(unittest.TestCase):
    def test_executable_links_rejected_in_html_and_tsx(self):
        for url in ["javascript:alert(1)", "java\tscript:alert(1)", "data:text/html,<script>1</script>", "vbscript:msgbox(1)"]:
            for generator in [landing.generate_html, landing.generate_tsx]:
                with self.subTest(url=url, generator=generator.__name__), self.assertRaises(ValueError):
                    generator({"hero": {"primary_cta": {"url": url}}})

    def test_bad_shape_style_and_css_fail_at_boundary(self):
        for config in [[], {"hero": []}, {"pricing": {"plans": ["not an object"]}},
                       {"design_style": "clean-minimal\nthrow new Error('injected')"},
                       {"theme": {"font": "sans-serif;</style><script>1</script>"}}]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                landing.generate_html(config)

    def test_metacharacters_compile_and_render_as_literal_jsx(self):
        text = 'R&D {globalThis.__SKILL_CANARY = true} <script>throw 1</script> "quoted"'
        config = {"brand": text, "title": text + "\nsecond line", "meta_description": text,
                  "hero": {"headline": text, "primary_cta": {"text": "Plans", "url": "#pricing"}},
                  "pricing": {"plans": [{"name": "Local", "features": [text], "cta_url": "#hero"}]}}
        parent = ROOT / "ui/runtime/tmp"
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent, prefix="page jsx ") as tmp:
            source = Path(tmp) / "Page.tsx"
            source.write_text(landing.generate_tsx(config))
            program = r"""
const fs = require('node:fs');
const {createRequire} = require('node:module');
const req = createRequire(process.argv[2]);
const ts = req('typescript');
const result = ts.transpileModule(fs.readFileSync(process.argv[1], 'utf8'), {
  compilerOptions: {jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022},
  reportDiagnostics: true
});
if (result.diagnostics?.length) throw Error(ts.formatDiagnosticsWithColorAndContext(result.diagnostics, {getCurrentDirectory:()=>process.cwd(),getCanonicalFileName:x=>x,getNewLine:()=> '\n'}));
const mod = {exports:{}};
new Function('require','module','exports',result.outputText)(req,mod,mod.exports);
const html = req('react-dom/server').renderToStaticMarkup(req('react').createElement(mod.exports.default));
if (globalThis.__SKILL_CANARY) throw Error('Configuration executed as source');
process.stdout.write(JSON.stringify({title:mod.exports.metadata.title,html}));
"""
            result = subprocess.run(["node", "-e", program, str(source), str(ROOT / "ui/verification/package.json")],
                                    capture_output=True, text=True, timeout=20,
                                    env={**os.environ, "TMPDIR": str(parent)})
            self.assertEqual(result.returncode, 0, result.stderr)
            rendered = json.loads(result.stdout)
            self.assertEqual(rendered["title"], config["title"])
            self.assertIn("R&amp;D {globalThis.__SKILL_CANARY = true}", rendered["html"])
            self.assertNotIn("<script>", rendered["html"])
            self.assertIn('id="pricing"', rendered["html"])

    def test_invalid_cli_input_does_not_overwrite_prior_artifact(self):
        parent = ROOT / "ui/runtime/tmp"
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as tmp:
            config, output = Path(tmp) / "bad.json", Path(tmp) / "page.html"
            config.write_text(json.dumps({"hero": {"primary_cta": {"url": "javascript:SKILL_CANARY"}}}))
            output.write_text("prior verified artifact")
            result = subprocess.run(["python3", "-B", str(SCRIPT), str(config), "--format", "html", "--output", str(output)],
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_text(), "prior verified artifact")
            self.assertNotIn("SKILL_CANARY", result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
