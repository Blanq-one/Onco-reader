"""The app's review rule for blocked claims (app/js/state.js), checked with Node if it is installed.

A claim stopped by a guardrail may only be accepted (as insufficient evidence) or sent
back with "ask for more evidence". The app's decide() refuses anything else, and its
review.json builder refuses a stale override with the same fixed message as
src/export/audit_json.py build_review. The page itself (no override control on a
blocked claim) is checked in a browser, not here.

Run from the repo root:  python -m unittest discover -s tests -v
Skips when node is not on PATH. Standard library only.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.export import audit_json as AJ  # noqa: E402

NODE = shutil.which("node")
SCRIPT = os.path.join(ROOT, "tests", "js", "review_guard.mjs")


@unittest.skipIf(NODE is None, "node not found; the app's review rule is not checked")
class TestAppReviewGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run = subprocess.run([NODE, SCRIPT], cwd=ROOT, capture_output=True, text=True, timeout=60)
        if run.returncode != 0:
            raise AssertionError("node failed:\n" + run.stderr[-2000:])
        cls.r = json.loads(run.stdout.strip().splitlines()[-1])

    def test_override_of_a_blocked_claim_is_refused(self):
        r = self.r
        self.assertEqual((r["reject"], r["approveSupported"], r["moreSupported"], r["bareVerdict"]), (False,) * 4)
        self.assertIsNone(r["rejectSaved"])
        self.assertIsNone(r["afterRefusals"])

    def test_every_blocking_flag_is_guarded(self):
        self.assertEqual(set(self.r["flags"]), set(AJ.BLOCKING_FLAGS))
        self.assertEqual(set(self.r["flags"].values()), {False})

    def test_accept_as_insufficient_evidence_is_allowed(self):
        r = self.r
        self.assertTrue(r["accept"])
        self.assertEqual(r["acceptStatus"], "accepted")
        item = r["acceptItem"]
        self.assertEqual((item["status"], item["human_decision"], item["human_verdict"], item["machine_verdict"]),
                         ("accepted", "approve", "insufficient_evidence", "insufficient_evidence"))

    def test_ask_for_more_evidence_is_allowed(self):
        r = self.r
        self.assertTrue(r["more"])
        self.assertEqual(r["moreStatus"], "more_evidence_requested")
        self.assertEqual((r["moreItem"]["status"], r["moreItem"]["human_verdict"]), ("more_evidence_requested", None))

    def test_unblocked_claims_can_still_be_overridden(self):
        self.assertTrue(self.r["overrideOk"])
        self.assertEqual(self.r["overrideStatus"], "overridden")

    def test_stale_override_is_refused_with_the_fixed_message(self):
        r = self.r
        self.assertEqual(r["message"], AJ.BLOCKED_OVERRIDE_ERROR)
        self.assertEqual(r["staleError"], "claim-003: " + AJ.BLOCKED_OVERRIDE_ERROR)
        self.assertFalse(r["secretInError"])


if __name__ == "__main__":
    unittest.main()
