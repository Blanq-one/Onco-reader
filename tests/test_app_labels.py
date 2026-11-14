"""The app's visible wording: no DEMO labels on the real-data path, and honest source labels.

Static checks over app/ (no browser needed). The synthetic-data warning is the only loud banner,
and it is shown only for is_mock findings.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")


def app_files():
    for base, _dirs, files in os.walk(APP):
        for name in files:
            if name.endswith((".js", ".html", ".css")):
                path = os.path.join(base, name)
                with open(path, encoding="utf-8") as fh:
                    yield os.path.relpath(path, ROOT), fh.read()


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class TestNoDemoLabels(unittest.TestCase):
    def test_no_demo_in_app_text(self):
        # DEMO_FILE (an identifier) is fine: \b stops at the underscore.
        hits = []
        for rel, text in app_files():
            for n, line in enumerate(text.splitlines(), 1):
                if re.search(r"\bDEMO\b", line) or re.search(r"demo mode", line, re.I):
                    hits.append(f"{rel}:{n}: {line.strip()}")
        self.assertEqual(hits, [], "DEMO wording found in app/:\n" + "\n".join(hits))

    def test_example_report_label(self):
        start = read("app/js/pages/start.js")
        self.assertIn("'Open the example report'", start)
        self.assertNotIn("btn big', type: 'button', id: 'example-btn'", start)  # normal size, not a big button
        self.assertIn("Live auditing starts when the local server is running: python server\\\\serve.py", start)


class TestSourceLabels(unittest.TestCase):
    def test_source_line_wording(self):
        ui = read("app/js/ui.js")
        self.assertIn("'Live audit of: '", ui)
        self.assertIn("'Example report: '", ui)
        self.assertIn("'Example'", ui)
        # Live only when the server audited the report in this session.
        self.assertRegex(ui, r"const live = state\.mode === 'live';")

    def test_source_line_on_results_and_summary(self):
        self.assertIn("sourceLine()", read("app/js/pages/results.js"))
        self.assertIn("sourceLine()", read("app/js/pages/more.js"))

    def test_live_mode_set_only_by_server_audit(self):
        sets = []
        for rel, text in app_files():
            for m in re.finditer(r"state\.mode = '([a-z-]+)'", text):
                sets.append((rel, m.group(1)))
        live = [rel for rel, mode in sets if mode == "live"]
        self.assertEqual(live, [os.path.join("app", "js", "live.js")])


class TestMockWarning(unittest.TestCase):
    def test_plain_synthetic_warning_only_for_mock(self):
        app = read("app/js/app.js")
        self.assertIn("'Synthetic sample data. These numbers are not real results.'", app)
        self.assertRegex(app, r"d && d\.is_mock \? h\('div', \{ class: 'banner'")
        self.assertNotIn("SAMPLE DATA", app)


if __name__ == "__main__":
    unittest.main()
