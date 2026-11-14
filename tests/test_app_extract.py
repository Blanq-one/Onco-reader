"""The Extraction view's edit rules (app/js/extract_logic.js), checked with Node if it is installed.

Editing a claim, adding one, and checking a skipped sentence anyway; what the server is sent; and the
reviewer_edits list that review.json records (a withheld original is recorded as "withheld" only).
The page itself (buttons, keyboard, 390 px width) is checked in a browser, not here. Skips when node is missing."""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")


@unittest.skipIf(NODE is None, "node not found; the Extraction edit rules are not checked")
class TestExtractLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run = subprocess.run([NODE, os.path.join(ROOT, "tests", "js", "extract_logic.mjs")], cwd=ROOT, capture_output=True, text=True, timeout=60)
        if run.returncode != 0:
            raise AssertionError("node failed:\n" + run.stderr[-2000:])
        cls.r = json.loads(run.stdout.strip().splitlines()[-1])

    def test_empty_or_long_text_is_refused(self):
        self.assertFalse(self.r["editBad"]["ok"]); self.assertFalse(self.r["editLong"]["ok"]); self.assertFalse(self.r["addBad"]["ok"])

    def test_an_edit_uses_the_new_wording_as_the_source_too(self):
        c = self.r["afterEdit"]
        self.assertEqual((c["text"], c["source"], c["origin"]), ("RNA covers 99 percent.", "RNA covers 99 percent.", "edited"))
        self.assertEqual(self.r["twice"], "RNA covers 90 percent.")   # the original stays the extracted claim

    def test_putting_the_text_back_removes_the_edit(self):
        c = self.r["reverted"]
        self.assertEqual(c["text"], "RNA covers 90 percent.")
        self.assertEqual(c["source"], "RNA covers 90 percent of tumors, as noted.")
        self.assertNotIn("origin", c); self.assertNotIn("edit", c)

    def test_check_anyway_moves_the_sentence_and_never_a_withheld_one(self):
        self.assertTrue(self.r["anyway"]["ok"])
        self.assertFalse(self.r["anywayWithheld"]["ok"])
        self.assertEqual(self.r["skippedLeft"], ["[withheld]"])

    def test_server_payload_marks_only_what_a_person_touched(self):
        p = self.r["payload"]
        self.assertTrue(self.r["changes"]); self.assertFalse(self.r["untouched"])
        self.assertEqual([("origin" in c) for c in p], [False, False, True, True])
        self.assertEqual(p[2]["origin"], "added")

    def test_only_added_claims_can_be_removed(self):
        self.assertFalse(self.r["removeExtracted"]); self.assertTrue(self.r["removeAdded"])

    def test_reviewer_edits_list(self):
        e = self.r["edits"]
        self.assertEqual([x["kind"] for x in e], ["edited", "added", "checked_anyway"])
        self.assertEqual(e[0], {"kind": "edited", "original_text": "withheld", "new_text": "withheld"})   # the original was withheld
        self.assertEqual(e[1], {"kind": "added", "original_text": None, "new_text": "Added claim text."})
        self.assertEqual(e[2], {"kind": "checked_anyway", "original_text": "Protein covers most tumors.", "new_text": "Protein covers most tumors."})

    def test_the_fifty_claim_limit(self):
        self.assertFalse(self.r["limitAdd"]["ok"]); self.assertFalse(self.r["limitAnyway"]["ok"])

    def test_withheld_markers(self):
        self.assertEqual(self.r["isWithheld"], [True, True, False])


if __name__ == "__main__":
    unittest.main()
