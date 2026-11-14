"""The multiple-reports view's pure helpers (app/js/batch_logic.js), checked with Node if it is installed.

Reports get anonymous labels, blocked claims are counted on their own, and sample barcodes are replaced by
per-report pseudonyms. The page itself (carousel, keyboard, 390 px width) is checked in a browser, not here.
Skips when node is not on PATH. Standard library only.
"""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")


@unittest.skipIf(NODE is None, "node not found; the multiple-reports helpers are not checked")
class TestBatchLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run = subprocess.run([NODE, os.path.join(ROOT, "tests", "js", "batch_logic.mjs")], cwd=ROOT, capture_output=True, text=True, timeout=60)
        if run.returncode != 0:
            raise AssertionError("node failed:\n" + run.stderr[-2000:])
        cls.r = json.loads(run.stdout.strip().splitlines()[-1])

    def test_labels_are_anonymous_and_ordered(self):
        self.assertEqual(self.r["labels"], ["Report A", "Report B", "Report Z", "Report 27", "Report 28"])

    def test_blocked_claims_are_counted_on_their_own(self):
        self.assertEqual(self.r["tally"], {"total": 5, "supported": 2, "contradicted": 1, "insufficient": 1, "blocked": 1, "review": 2})

    def test_pseudonyms_are_numbered_per_report_in_order_of_use(self):
        self.assertEqual(self.r["first"], ["Sample 1", "Sample 2", "Sample 1"])  # the same barcode keeps its name
        self.assertEqual(self.r["other"], ["Sample 1"])                          # another report starts again at 1

    def test_masked_groups_carry_no_barcodes(self):
        self.assertFalse(self.r["leaks"])
        self.assertEqual(self.r["masked"][0]["ids"], ["Sample 1", "Sample 2"])
        self.assertEqual(self.r["masked"][0]["total"], 3)  # totals stay exact


if __name__ == "__main__":
    unittest.main()
