"""Guardrail tests driven by tests/edge_cases.csv.

D implements src/guardrails/__init__.py with:

    check_claim(text: str) -> dict
        {"allowed": bool, "flags": [str], "reason": str}

Rules for the return value:
- allowed is True only if the claim may go on to the evidence engine.
- flags use the names in contract/validate_findings.py (GUARDRAIL_FLAGS).
- reason is a short human-readable sentence the UI can show.

Rows marked engine_refuses are for the evidence engine, not this module,
so they are skipped here. Until check_claim exists, this module skips itself.
"""
import csv
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

try:
    from guardrails import check_claim
except ImportError:  # not written yet
    check_claim = None

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "edge_cases.csv")


def rows():
    with open(CSV_PATH, newline="") as fh:
        return list(csv.DictReader(fh))


@unittest.skipIf(check_claim is None, "src/guardrails/check_claim not implemented yet")
class TestEdgeCaseBank(unittest.TestCase):
    def test_bank_rows(self):
        for r in rows():
            action = r["expected_action"]
            if action == "engine_refuses":
                continue
            with self.subTest(case=r["id"], category=r["category"]):
                result = check_claim(r["claim_text"])
                self.assertIn("allowed", result)
                self.assertIn("flags", result)
                self.assertTrue(str(result.get("reason", "")).strip() or result["allowed"])
                if action == "allow":
                    self.assertTrue(result["allowed"], r["notes"])
                else:
                    self.assertFalse(result["allowed"], r["notes"])
                    self.assertIn(r["expected_flag"], result["flags"])

    def test_never_crashes_on_odd_input(self):
        odd = ["", " ", "\n\t", "a" * 20000, "\u0000", "💥" * 50,
               "RNA data is available. " * 1000, "<script>alert(1)</script>"]
        for text in odd:
            with self.subTest(sample=repr(text[:20])):
                result = check_claim(text)
                self.assertIn("allowed", result)


if __name__ == "__main__":
    unittest.main()
