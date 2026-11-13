"""Contract tests: run the draft validator on findings files.

Run from the repo root:  python -m unittest discover -s tests -v
(pytest also works if installed.)
"""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "contract"))
import validate_findings as vf  # noqa: E402

MOCK = os.path.join(ROOT, "contract", "mock_findings.json")


def load():
    with open(MOCK) as fh:
        return json.load(fh)


class TestMockFindings(unittest.TestCase):
    def test_every_mock_finding_is_valid(self):
        for f in load()["findings"]:
            with self.subTest(finding=f["id"]):
                self.assertEqual(vf.check_finding(f), [])

    def test_mock_file_is_labelled_mock(self):
        doc = load()
        self.assertTrue(doc["is_mock"])
        self.assertTrue(doc["mock_warning"].strip())

    def test_ids_are_unique(self):
        ids = [f["id"] for f in load()["findings"]]
        self.assertEqual(len(ids), len(set(ids)))


class TestValidatorCatchesBadData(unittest.TestCase):
    def setUp(self):
        self.good = copy.deepcopy(load()["findings"][0])

    def test_empty_limitation_fails(self):
        self.good["limitation"] = ""
        self.assertTrue(vf.check_finding(self.good))

    def test_bad_verdict_fails(self):
        self.good["verdict"] = "maybe"
        self.assertTrue(vf.check_finding(self.good))

    def test_growing_cohort_fails(self):
        self.good["cohort_trace"][1]["n_after"] = 99999
        self.assertTrue(vf.check_finding(self.good))

    def test_review_without_reason_fails(self):
        self.good["needs_human_review"] = True
        self.good["review_reason"] = None
        self.assertTrue(vf.check_finding(self.good))

    def test_n_samples_over_denominator_fails(self):
        self.good["evidence"]["n_samples"] = self.good["evidence"]["denominator"] + 1
        self.assertTrue(vf.check_finding(self.good))

    def test_unsupported_verdict_needs_next_action(self):
        f = copy.deepcopy(load()["findings"][1])  # contradicted
        f["next_actions"] = []
        self.assertTrue(vf.check_finding(f))


class TestGuardrailInvariantsOnFindings(unittest.TestCase):
    """Rules that must hold for any findings file, mock or real."""

    def test_blocked_findings_never_show_a_number_or_supported(self):
        blocked = {"clinical_claim_blocked", "individual_level_request_blocked",
                   "reidentification_blocked", "phi_like_input",
                   "prompt_injection_suspected"}
        for f in load()["findings"]:
            if blocked & set(f["guardrail_flags"]):
                with self.subTest(finding=f["id"]):
                    self.assertEqual(f["verdict"], "insufficient_evidence")
                    self.assertIsNone(f["evidence"]["value"])
                    self.assertTrue(f["needs_human_review"])

    def test_cannot_answer_is_insufficient(self):
        for f in load()["findings"]:
            if "data_cannot_answer" in f["guardrail_flags"]:
                with self.subTest(finding=f["id"]):
                    self.assertEqual(f["verdict"], "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
