"""POST /api/audit and /api/audit-json with {"claims": [...]}: reviewer-edited and reviewer-added claims.

Starts the real server on a free port over the tiny synthetic release (test_engine_claims), no TCGA data needed.
Checks the reviewer's wording is what gets audited and exported, that the evidence says a person edited or
added it, that the limits and guardrails match /api/audit, and that nothing about a claim reaches the log."""
import http.client
import io
import json
import os
import sys
import threading
import unittest
from contextlib import redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_engine_claims import write_release  # noqa: E402
import tempfile  # noqa: E402
from server import serve as S  # noqa: E402
from src.engine import engine as E  # noqa: E402

FILES = [{"file": "clinical.tsv", "sha256": "1" * 64}, {"file": "sample_manifest.csv", "sha256": "2" * 64}]
JSON = {"Content-Type": "application/json"}
WORDING = "Mutation data is available for about 75 percent of primary tumors."


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        write_release(cls.tmp.name, mutation_rows={"TP53": []})
        cls.srv = S.Server(("127.0.0.1", 0), E.Context(cls.tmp.name), FILES, True)
        cls.port = cls.srv.server_address[1]
        cls.log = io.StringIO()
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        with redirect_stderr(cls.log):
            cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close(); cls.tmp.cleanup()

    def post(self, path, body, raw=None):
        with redirect_stderr(self.log):  # the server logs one line per request; keep the test output clean
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
            c.request("POST", path, raw if raw is not None else json.dumps(body), JSON)
            r = c.getresponse()
            data = json.loads(r.read().decode())
            c.close()
        return r.status, data


class TestReviewerClaims(ServerCase):
    def test_edited_and_added_claims_are_audited_as_worded(self):
        status, doc = self.post("/api/audit", {"claims": [
            {"text": WORDING, "source": WORDING, "origin": "edited"},
            {"text": "There are 2 metastatic samples.", "source": "There are 2 metastatic samples.", "origin": "added"},
            {"text": "There are 5 normal-tissue samples.", "source": "There are 5 normal-tissue samples."}]})
        self.assertEqual(status, 200)
        a, b, c = doc["findings"]
        self.assertEqual((a["claim_text"], a["evidence"]["reviewer_origin"]), (WORDING, "edited"))
        self.assertEqual(b["evidence"]["reviewer_origin"], "added")
        self.assertIn("A reviewer edited this claim", a["evidence"]["calculation"])
        self.assertIn("A reviewer added this claim", b["evidence"]["calculation"])
        self.assertNotIn("reviewer_origin", c["evidence"])          # untouched claim: nothing added
        self.assertEqual(a["verdict"], "supported")                  # still measured, not just labelled

    def test_audit_json_takes_claims_and_keeps_the_reviewers_wording(self):
        status, audit = self.post("/api/audit-json", {"claims": [{"text": WORDING, "source": WORDING, "origin": "edited"}]})
        self.assertEqual(status, 200)
        f = audit["findings"][0]
        self.assertEqual(f["claim_text"], WORDING)
        self.assertIn("A reviewer edited this claim", json.dumps(f))
        self.assertEqual(self.post("/api/audit-json", {"claims": [WORDING]})[0], 200)   # plain strings still work

    def test_report_path_is_unchanged(self):
        status, doc = self.post("/api/audit", {"report": "1. There are 2 metastatic samples.\n"})
        self.assertEqual(status, 200)
        self.assertNotIn("reviewer_origin", doc["findings"][0]["evidence"])
        self.assertEqual(self.post("/api/audit-json", {"report": "1. There are 2 metastatic samples.\n"})[0], 200)

    def test_unknown_origin_is_ignored(self):
        _, doc = self.post("/api/audit", {"claims": [{"text": WORDING, "origin": "robot"}]})
        self.assertNotIn("reviewer_origin", doc["findings"][0]["evidence"])

    def test_same_limits_on_both_endpoints(self):
        for path in ("/api/audit", "/api/audit-json"):
            self.assertEqual(self.post(path, {"claims": [WORDING] * (S.MAX_CLAIMS + 1)})[0], 413)
            self.assertEqual(self.post(path, {"claims": ["x" * (S.MAX_CLAIM_CHARS + 1)]})[0], 413)
            self.assertEqual(self.post(path, {"claims": [WORDING] * 3 + [{"text": 5}]})[0], 400)
            self.assertEqual(self.post(path, {"claims": []})[0], 400)
            self.assertEqual(self.post(path, {"claims": [WORDING], "report": "x"})[0], 400)
            self.assertEqual(self.post(path, None, raw=json.dumps({"claims": ["a" * 1000] * 120}))[0], 413)   # over 100 KB
        self.assertEqual(self.post("/api/audit-json", {"claims": [WORDING] * S.MAX_CLAIMS})[0], 200)

    def test_guardrails_still_apply_to_a_reviewers_wording(self):
        # a clinical request and a participant barcode stay blocked even when a reviewer typed them
        _, doc = self.post("/api/audit", {"claims": [
            {"text": "Drug X improves survival for patients in this dataset.", "origin": "added"},
            {"text": "Sample TCGA-ZZ-0001-01 has RNA data.", "origin": "edited"}]})
        for f in doc["findings"]:
            self.assertEqual(f["verdict"], "insufficient_evidence")
            self.assertTrue(f["guardrail_flags"])
            self.assertIsNone(f["evidence"]["value"])
            self.assertIn(f["evidence"]["reviewer_origin"], ("added", "edited"))
        self.assertNotIn("TCGA-ZZ-0001", json.dumps(doc["findings"][1]["claim_text"]))

    def test_nothing_about_a_claim_reaches_the_log(self):
        marker = "Zyxwvut-claim-marker"
        buf = io.StringIO()
        with redirect_stderr(buf):
            self.post("/api/audit", {"claims": [{"text": WORDING + " " + marker, "origin": "edited"}]})
            self.post("/api/audit", {"claims": [{"text": 5}]})
        self.assertNotIn(marker, buf.getvalue() + self.log.getvalue())


if __name__ == "__main__":
    unittest.main()
