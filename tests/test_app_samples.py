"""The ten example reports behind "Add the 10 example reports" (Start and the Reports page).

Every file listed in app/js/pages/batch.js exists, says it is made up, and goes through the engine with
the guardrails post-check passing (so no example fails in the Reports view). The engine part needs the data
($TCGA_DATA_DIR, else ../challenge-ref/data/tcga-brca) and skips without it. Standard library only.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES_DIR = os.path.join(ROOT, "app", "samples")


def listed_samples():
    with open(os.path.join(ROOT, "app", "js", "pages", "batch.js"), encoding="utf-8") as fh:
        js = fh.read()
    block = js[js.index("export const SAMPLES = ["):js.index("];", js.index("export const SAMPLES = ["))]
    return re.findall(r"\['([\w.-]+\.md)', '([^']+)'\]", block)


def find_data_dir():
    for cand in (os.environ.get("TCGA_DATA_DIR"), os.path.join("..", "challenge-ref", "data", "tcga-brca")):
        if not cand:
            continue
        path = cand if os.path.isabs(cand) else os.path.join(ROOT, cand)
        if os.path.isfile(os.path.join(path, "raw", "clinical.tsv")):
            return os.path.abspath(path)
    return None


class TestExampleList(unittest.TestCase):
    def test_ten_examples_listed_and_present(self):
        samples = listed_samples()
        self.assertEqual(len(samples), 10)
        self.assertEqual(len({f for f, _ in samples}), 10)
        for name, _label in samples:
            self.assertTrue(os.path.isfile(os.path.join(SAMPLES_DIR, name)), name)

    def test_examples_say_they_are_made_up(self):
        for name, _label in listed_samples():
            if name == "practice_brief.md":
                continue  # the organizers' practice brief, kept as is
            with open(os.path.join(SAMPLES_DIR, name), encoding="utf-8") as fh:
                self.assertIn("made-up report", fh.read(), name)

    def test_start_offers_the_ten(self):
        with open(os.path.join(ROOT, "app", "js", "pages", "start.js"), encoding="utf-8") as fh:
            start = fh.read()
        self.assertIn("'Add the 10 example reports'", start)
        self.assertIn("state.batchPreset = 'examples'", start)


@unittest.skipIf(find_data_dir() is None, "TCGA-BRCA data not found; the engine run on the examples is skipped")
class TestExamplesRunThroughEngine(unittest.TestCase):
    def test_each_example_passes_the_post_check(self):
        data = find_data_dir()
        with tempfile.TemporaryDirectory() as tmp:
            for name, _label in listed_samples():
                out = os.path.join(tmp, name + ".json")
                run = subprocess.run([sys.executable, os.path.join("src", "engine", "engine.py"), "--data-dir", data,
                                      "--report", os.path.join(SAMPLES_DIR, name), "--out", out],
                                     cwd=ROOT, capture_output=True, text=True, timeout=600)
                self.assertEqual(run.returncode, 0, name + ":\n" + (run.stdout + run.stderr)[-1500:])
                with open(out, encoding="utf-8") as fh:
                    self.assertGreater(len(json.load(fh)["findings"]), 0, name)


if __name__ == "__main__":
    unittest.main()
