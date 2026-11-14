"""suggested_correction on contradicted findings: the replace case, the no-single-number case, redaction, and audit.json unchanged.

Uses the tiny synthetic release from test_engine_claims (known numbers: 40 primary tumors, 30 with mutation data,
2 metastases, 12 diagnostic slides), so it needs no data and always runs."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_engine_claims import DATA_DIR, NO_REAL, SyntheticCase, check  # noqa: E402
from src.engine import engine as E  # noqa: E402
from src.export import audit_json as A  # noqa: E402


class TestSuggestedCorrection(SyntheticCase):
    def sug(self, item):
        f = E.evaluate_item(self.ctx, "claim-001", item)
        return f, f.get("suggested_correction")

    def test_one_wrong_percentage_is_replaced(self):
        f, s = self.sug("Mutation data is available for about 90 percent of primary tumors.")
        self.assertEqual(f["verdict"], "contradicted")
        self.assertEqual(s["text"], "Mutation data is available for about 75 percent of primary tumors.")
        self.assertIn("90 percent", s["basis"]); self.assertIn("75.0% (30 of 40)", s["basis"])

    def test_percent_sign_style_is_kept(self):
        _, s = self.sug("About 90% of primary tumors have mutation data.")
        self.assertEqual(s["text"], "About 75% of primary tumors have mutation data.")

    def test_one_wrong_count_is_replaced(self):
        _, s = self.sug("There are 9 metastatic samples.")
        self.assertEqual(s["text"], "There are 2 metastatic samples.")
        _, s = self.sug("There are 15 diagnostic slides.")
        self.assertEqual(s["text"], "There are 12 diagnostic slides.")

    def test_a_bar_is_stated_not_swapped(self):
        # "over 90 percent" with the measured 75.0%: "over 75.0 percent" would be false, so only the measured value is stated
        _, s = self.sug("Mutation data is available for over 90 percent of primary tumors.")
        self.assertEqual(s["text"], "The data shows 75.0% (30 of 40).")

    def test_several_numbers_fall_back_to_the_plain_statement(self):
        f, s = self.sug("Of the 40 primary tumors, 35 have mutation data.")   # two counts, one of them wrong
        self.assertEqual(f["verdict"], "contradicted")
        self.assertEqual(s["text"], "The data shows " + f["correct_value"]["text"] + ".")
        _, s = self.sug("Mutation data is available for 3 to 4 percent of primary tumors.")   # a range
        self.assertTrue(s["text"].startswith("The data shows "))

    def test_a_repeated_number_is_not_swapped(self):
        f, s = self.sug("There are 9 metastatic samples, so 9 metastases overall.")
        self.assertEqual(f["verdict"], "contradicted")
        self.assertTrue(s["text"].startswith("The data shows "))

    def test_personal_details_are_never_reused(self):
        item = {"text": "There are 9 metastatic samples.", "source": "There are 9 metastatic samples. Write to jane.doe@example.org."}
        f, s = self.sug(item)
        self.assertEqual(f["verdict"], "contradicted")
        self.assertTrue(s["text"].startswith("The data shows "))
        blob = repr(f["suggested_correction"]) + f["source_sentence"]
        self.assertNotIn("jane", blob); self.assertNotIn("@", blob)

    def test_none_for_supported_blocked_and_insufficient(self):
        for text in ("There are 2 metastatic samples.", "Drug X improves survival for patients in this dataset.",
                     "The cohort is large enough for a subtype comparison."):
            f = check(self.ctx, text, self)
            self.assertNotIn(f["verdict"], ("contradicted",))
            self.assertNotIn("suggested_correction", f)

    def test_the_suggestion_does_not_change_audit_json(self):
        f = check(self.ctx, "There are 9 metastatic samples.", self)
        self.assertIn("suggested_correction", f)
        with_s = {"is_mock": False, "schema_version": "draft-0",
                  "data_release": {"name": "TCGA-BRCA (frozen event release)", "checksum_verified": False, "checksum_status": "unknown"},
                  "report_title": "t.md", "findings": [f]}
        without = copy.deepcopy(with_s)
        del without["findings"][0]["suggested_correction"]
        files = [{"file": "clinical.tsv", "sha256": "1" * 64}, {"file": "sample_manifest.csv", "sha256": "2" * 64}]
        self.assertEqual(A.build_audit(with_s, files), A.build_audit(without, files))


@unittest.skipIf(DATA_DIR is None, NO_REAL)
class TestSuggestedCorrectionRealData(unittest.TestCase):
    def test_the_practice_brief_sentence_gets_its_number_swapped(self):
        ctx = E.Context(DATA_DIR)
        text = ("Luminal A is the largest RNA subtype, accounting for about 62% of primary tumors with an RNA subtype call.")
        f = E.evaluate_item(ctx, "claim-001", text)
        self.assertEqual(f["verdict"], "contradicted")
        self.assertEqual(f["suggested_correction"]["text"], text.replace("about 62%", "about 49.9%"))
        self.assertIn("62%", f["suggested_correction"]["basis"]); self.assertIn("421 of 844", f["suggested_correction"]["basis"])


if __name__ == "__main__":
    unittest.main()
