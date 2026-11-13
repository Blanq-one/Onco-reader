"""Tests for the audit.json exporter (src/export/audit_json.py) and scripts/make_audit.py.

Run from the repo root:  python -m unittest discover -s tests -v

The unit tests use a small hand-written findings document, so they need no data.
Schema checks use the organizers' own validator (challenge-ref/format/validate.py)
and skip if it or jsonschema is missing. The end-to-end test runs make_audit.py on
the practice brief and skips if the TCGA-BRCA data is not found.
"""
import contextlib
import copy
import csv
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.export import audit_json as AJ  # noqa: E402

MAKE_AUDIT = os.path.join(ROOT, "scripts", "make_audit.py")


def find_data_dir():
    """The frozen release: $TCGA_DATA_DIR (relative paths are from the repo root), else ../challenge-ref."""
    for cand in (os.environ.get("TCGA_DATA_DIR"), os.path.join("..", "challenge-ref", "data", "tcga-brca")):
        if not cand:
            continue
        path = cand if os.path.isabs(cand) else os.path.join(ROOT, cand)
        if os.path.isfile(os.path.join(path, "raw", "clinical.tsv")):
            return os.path.abspath(path)
    return None


DATA_DIR = find_data_dir()
CHALLENGE = os.path.abspath(os.path.join(DATA_DIR, "..", "..")) if DATA_DIR else os.path.join(ROOT, "..", "challenge-ref")
VALIDATE_PY = os.path.join(CHALLENGE, "format", "validate.py")
BRIEF = os.path.join(CHALLENGE, "products", "research-claim-auditor", "practice_brief.md")


def load_format_validator():
    """The organizers' format/validate.py as a module, or None if it or jsonschema is missing."""
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        return None
    if not os.path.isfile(VALIDATE_PY):
        return None
    spec = importlib.util.spec_from_file_location("_format_validate", VALIDATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VALIDATOR = load_format_validator()
NO_VALIDATOR = "challenge-ref/format/validate.py or jsonschema not found"

FILES = [{"file": "clinical.tsv", "sha256": "1" * 64}, {"file": "survival.tsv", "sha256": "2" * 64}]
CLINICAL_MISSING = "Treatment, drug-response or outcome-by-treatment records."


def make_doc():
    """Three findings in the engine's shape: supported, contradicted (two parts), blocked."""
    return {
        "is_mock": False, "schema_version": "draft-0",
        "data_release": {"name": "TCGA-BRCA (frozen event release)", "checksum_verified": True, "checksum_status": "verified"},
        "report_title": "brief.md",
        "findings": [
            {"id": "claim-001", "claim_text": "There are 1,101 primary tumors.", "verdict": "supported",
             "evidence": {"metric_name": "population_size_primary", "value": 1101, "n_samples": 1101, "denominator": 1101,
                          "source_files": ["sample_manifest.csv"], "calculation": "primary tumor samples: 1101."},
             "cohort_trace": [{"step": "primary tumor samples", "n_before": 1101, "n_after": 1101}],
             "limitation": "Counts come from the release's sample list.", "needs_human_review": False,
             "review_reason": None, "guardrail_flags": [], "next_actions": ["Say which sample types the count covers."],
             "robustness": None, "correct_value": None, "missing_evidence": None,
             "source_sentence": "There are 1,101 primary tumors."},
            {"id": "claim-002",
             "claim_text": "Luminal A is the largest RNA subtype, accounting for about 62% of tumors with a call.",
             "verdict": "contradicted",
             "evidence": {"metric_name": "share_luminal_a", "value": 0.4988, "n_samples": 421, "denominator": 844,
                          "source_files": ["clinical.tsv", "sample_manifest.csv (slides_for_sample)"],
                          "calculation": "Luminal A among tumors with a call: 421 / 844 = 49.9%.",
                          "sub_checks": [
                              {"claim": "Luminal A is the largest RNA subtype.", "verdict": "supported",
                               "value": 421, "n_samples": 421, "denominator": 844},
                              {"claim": "Luminal A accounts for about 62%.", "verdict": "contradicted",
                               "value": 0.4988, "n_samples": 421, "denominator": 844}]},
             "cohort_trace": [{"step": "primary tumor samples", "n_before": 1101, "n_after": 1101},
                              {"step": "has PAM50 subtype recorded", "n_before": 1101, "n_after": 844},
                              {"step": "Luminal A", "n_before": 844, "n_after": 421}],
             "limitation": "The values themselves were not verified.", "needs_human_review": False,
             "review_reason": None, "guardrail_flags": [], "next_actions": ["Restate the claim with 421 of 844."],
             "robustness": {"alt_rule": "count unrecorded samples too", "alt_value": 0.3824, "verdict_changes": False},
             "correct_value": {"value": 49.9, "unit": "percent", "text": "49.9% (421 of 844)"},
             "missing_evidence": None,
             "source_sentence": "Luminal A is the largest RNA subtype, accounting for about 62% of tumors with a call."},
            {"id": "claim-003", "claim_text": "Tumors with the highest protein responded best to therapy.",
             "verdict": "insufficient_evidence",
             "evidence": {"metric_name": "not_computed", "value": None, "n_samples": 0, "denominator": 1101,
                          "source_files": [], "calculation": "not run: Blocked: this reads as a treatment response claim."},
             "cohort_trace": [], "limitation": "This tool checks data readiness only.", "needs_human_review": True,
             "review_reason": "Blocked: this reads as a treatment response claim.",
             "guardrail_flags": ["clinical_claim_blocked"], "next_actions": ["Rewrite the claim."],
             "robustness": None, "correct_value": None, "missing_evidence": CLINICAL_MISSING,
             "source_sentence": "Tumors with the highest protein responded best to therapy, which suggests more."},
        ],
    }


def by_id(audit):
    return {f["id"]: f for f in audit["findings"]}


def read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def refs(finding, kind):
    return [r for r in finding["evidence"] if r["kind"] == kind]


class TestAuditExport(unittest.TestCase):
    def setUp(self):
        self.doc = make_doc()
        self.audit = AJ.build_audit(self.doc, FILES)
        self.f = by_id(self.audit)

    @unittest.skipIf(VALIDATOR is None, NO_VALIDATOR)
    def test_validates_with_the_organizers_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.json")
            AJ.write_json(self.audit, path)
            self.assertEqual(VALIDATOR.check(path), [])

    def test_top_level_fields(self):
        a = self.audit
        self.assertEqual(a["format_version"], "0.2")
        self.assertEqual(a["producer"], {"team": "onco-evidence", "product": "Research Claim Auditor",
                                         "track": "evidence-navigator"})
        self.assertEqual(a["data"]["dataset"], "TCGA-BRCA")
        self.assertEqual(a["data"]["releases"], [{"name": "raw", "files": FILES}])
        self.assertIn("brief.md", a["question"])
        self.assertNotIn("decisions", a)
        custom = AJ.build_audit(self.doc, FILES, release="A", team="t", question="Can we trust it?")
        self.assertEqual((custom["data"]["releases"][0]["name"], custom["producer"]["team"], custom["question"]),
                         ("A", "t", "Can we trust it?"))

    def test_one_claim_check_per_claim(self):
        self.assertEqual([f["id"] for f in self.audit["findings"]], ["claim-001", "claim-002", "claim-003"])
        self.assertTrue(all(f["kind"] == "claim_check" for f in self.audit["findings"]))
        self.assertEqual([f["claim_verdict"] for f in self.audit["findings"]],
                         ["supported", "contradicted", "insufficient_evidence"])

    def test_claim_text_is_the_sentence_as_written(self):
        f3 = self.f["claim-003"]
        self.assertEqual(f3["claim_text"], self.doc["findings"][2]["source_sentence"])
        self.assertEqual(refs(f3, "claim")[0]["note"], "Checked as: " + self.doc["findings"][2]["claim_text"])
        doc = make_doc()
        doc["findings"][2]["source_sentence"] = None  # older engine: falls back to claim_text
        self.assertEqual(by_id(AJ.build_audit(doc, FILES))["claim-003"]["claim_text"], doc["findings"][2]["claim_text"])

    def test_correct_value_only_for_contradicted(self):
        self.assertEqual(self.f["claim-002"]["correct_value"], "49.9% (421 of 844)")
        self.assertIn("49.9% (421 of 844)", self.f["claim-002"]["summary"])
        self.assertNotIn("correct_value", self.f["claim-001"])
        self.assertNotIn("correct_value", self.f["claim-003"])

    def test_contradicted_without_correct_value_uses_the_measured_figure(self):
        doc = make_doc()
        doc["findings"][1]["correct_value"] = None
        self.assertEqual(by_id(AJ.build_audit(doc, FILES))["claim-002"]["correct_value"], "49.9% (421 of 844)")

    def test_insufficient_evidence_says_what_data_is_needed(self):
        f3 = self.f["claim-003"]
        self.assertIn("Data needed: " + CLINICAL_MISSING, f3["summary"])
        self.assertIn(CLINICAL_MISSING, refs(f3, "release")[0]["note"])
        self.assertEqual(refs(f3, "release")[0]["id"], "raw")
        doc = make_doc()
        doc["findings"][2]["missing_evidence"] = None
        summary = by_id(AJ.build_audit(doc, FILES))["claim-003"]["summary"]
        self.assertIn("Data needed: Blocked: this reads as a treatment response claim.", summary)

    def test_evidence_carries_calculation_trace_and_files(self):
        f2 = self.f["claim-002"]
        calc = [r for r in refs(f2, "analysis") if r["id"] == "share_luminal_a"][0]
        self.assertIn("421 / 844 = 49.9%", calc["note"])
        self.assertIn("421 of 844 samples", calc["note"])
        self.assertEqual(calc["release"], "raw")
        trace = [r for r in refs(f2, "analysis") if r["id"] == "cohort_trace"][0]
        self.assertIn("has PAM50 subtype recorded: 1101 -> 844", trace["note"])
        rob = [r for r in refs(f2, "analysis") if r["id"] == "robustness"][0]
        self.assertIn("0.3824", rob["note"])
        files = {r["id"]: r for r in refs(f2, "file")}
        self.assertEqual(set(files), {"clinical.tsv", "sample_manifest.csv"})
        self.assertEqual(files["clinical.tsv"]["release"], "raw")
        self.assertNotIn("note", files["clinical.tsv"])
        self.assertIn("slides_for_sample", files["sample_manifest.csv"]["note"])
        self.assertIn("not listed in sources.csv", files["sample_manifest.csv"]["note"])
        parts = [r for r in refs(f2, "claim") if r["id"].startswith("claim-002.")]
        self.assertEqual(len(parts), 2)
        self.assertIn("Verdict: contradicted; measured 49.9% (421 of 844)", parts[1]["note"])

    def test_blocked_finding_shows_no_number_and_its_flags(self):
        f3 = self.f["claim-003"]
        calc = [r for r in refs(f3, "analysis") if r["id"] == "not_computed"][0]
        self.assertTrue(calc["note"].startswith("not run:"))
        self.assertNotIn("release", calc)
        self.assertEqual(refs(f3, "file"), [])
        notes = " ".join(r.get("note", "") for r in f3["evidence"])
        self.assertIn("clinical_claim_blocked", notes)
        self.assertIn("A person must check this before it is used", notes)

    def test_limitation_review_severity_confidence(self):
        for src, out in zip(self.doc["findings"], self.audit["findings"]):
            self.assertEqual(out["limitation"], src["limitation"])
            self.assertEqual(out["needs_human_review"], src["needs_human_review"])
        self.assertEqual([f["severity"] for f in self.audit["findings"]], ["none", "high", "medium"])
        self.assertEqual([f["confidence"] for f in self.audit["findings"]], ["high", "high", "medium"])
        doc = make_doc()
        doc["findings"][1]["robustness"]["verdict_changes"] = True
        self.assertEqual(by_id(AJ.build_audit(doc, FILES))["claim-002"]["confidence"], "low")

    def test_checksum_warning_on_every_limitation_when_not_verified(self):
        doc = make_doc()
        doc["data_release"]["checksum_status"] = "mismatch"
        audit = AJ.build_audit(doc, FILES)
        for src, out in zip(doc["findings"], audit["findings"]):
            self.assertTrue(out["limitation"].startswith(src["limitation"]))
            self.assertIn("checksum status: mismatch", out["limitation"])

    def test_refuses_bad_input(self):
        doc = make_doc()
        doc["is_mock"] = True
        with self.assertRaises(ValueError):
            AJ.build_audit(doc, FILES)
        doc = make_doc()
        doc["findings"][0]["verdict"] = "maybe"
        with self.assertRaises(ValueError):
            AJ.build_audit(doc, FILES)
        doc = make_doc()
        doc["findings"][1]["id"] = "claim-001"
        with self.assertRaises(ValueError):
            AJ.build_audit(doc, FILES)
        with self.assertRaises(ValueError):
            AJ.build_audit(make_doc(), [])
        with self.assertRaises(ValueError):
            AJ.build_audit({"no": "findings"}, FILES)

    def test_engine_document_is_not_changed(self):
        doc = make_doc()
        before = copy.deepcopy(doc)
        AJ.build_audit(doc, FILES)
        AJ.build_review(doc, {"claim-001": {"decision": "reject", "verdict": "contradicted"}})
        self.assertEqual(doc, before)

    def test_written_file_is_ascii(self):
        doc = make_doc()
        doc["findings"][0]["source_sentence"] = "At least 90% ≥ cohort, café."
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sub", "audit.json")
            AJ.write_json(AJ.build_audit(doc, FILES), path)
            with open(path, "rb") as fh:
                raw = fh.read()
        raw.decode("ascii")  # raises if any byte is not ASCII
        self.assertEqual(json.loads(raw)["findings"][0]["claim_text"], doc["findings"][0]["source_sentence"])


class TestReadSources(unittest.TestCase):
    def write(self, tmp, rows, header=("file", "layer", "sha256", "bytes")):
        with open(os.path.join(tmp, "sources.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)

    def test_reads_files_and_checksums_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, [("b.tsv", "x", "A" * 64, "1"), ("a.tsv.gz", "y", "0" * 64, "2")])
            self.assertEqual(AJ.read_sources(tmp), [{"file": "b.tsv", "sha256": "a" * 64},
                                                    {"file": "a.tsv.gz", "sha256": "0" * 64}])

    def test_rejects_bad_checksums_and_missing_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, [("b.tsv", "x", "not-a-hash", "1")])
            with self.assertRaises(ValueError):
                AJ.read_sources(tmp)
            self.write(tmp, [("b.tsv", "x", "1")], header=("file", "layer", "bytes"))
            with self.assertRaises(ValueError):
                AJ.read_sources(tmp)
            self.write(tmp, [])
            with self.assertRaises(ValueError):
                AJ.read_sources(tmp)

    @unittest.skipIf(DATA_DIR is None, "TCGA-BRCA data not found")
    def test_real_sources_csv(self):
        files = AJ.read_sources(DATA_DIR)
        self.assertEqual(len(files), 6)
        self.assertIn("rna_hiseq.tsv.gz", [f["file"] for f in files])


class TestReview(unittest.TestCase):
    def test_pending_queue_by_default(self):
        review = AJ.build_review(make_doc())
        self.assertEqual([i["status"] for i in review["items"]], ["pending"] * 3)
        self.assertEqual(review["counts"]["pending"], 3)
        self.assertEqual(review["items"][2]["review_reason"], "Blocked: this reads as a treatment response claim.")
        self.assertIn("never changed", review["about"])

    def test_decisions_keep_machine_and_human_verdicts(self):
        decisions = {
            "claim-001": {"decision": "approve", "note": "ok", "at": "2026-11-13T10:00:00Z"},
            "claim-002": {"decision": "reject", "verdict": "supported", "reviewer_role": "biostatistician"},
            "claim-003": {"decision": "more"},
            "claim-999": {"decision": "approve"},
        }
        items = {i["finding_id"]: i for i in AJ.build_review(make_doc(), decisions)["items"]}
        self.assertEqual((items["claim-001"]["status"], items["claim-001"]["human_verdict"]), ("accepted", "supported"))
        self.assertEqual(items["claim-001"]["decided_at"], "2026-11-13T10:00:00Z")
        self.assertEqual((items["claim-002"]["machine_verdict"], items["claim-002"]["human_verdict"],
                          items["claim-002"]["status"]), ("contradicted", "supported", "overridden"))
        self.assertEqual(items["claim-002"]["reviewer_role"], "biostatistician")
        self.assertEqual((items["claim-003"]["status"], items["claim-003"]["human_verdict"]),
                         ("more_evidence_requested", None))
        self.assertEqual(AJ.build_review(make_doc(), decisions)["ignored_decision_ids"], ["claim-999"])

    def test_bad_decisions_rejected(self):
        for bad in ({"claim-001": {"decision": "maybe"}}, {"claim-001": {"verdict": "true"}},
                    {"claim-001": "approve"}, ["claim-001"]):
            with self.assertRaises(ValueError):
                AJ.build_review(make_doc(), bad)


class TestBlockedReview(unittest.TestCase):
    """A blocked claim (claim-003, clinical_claim_blocked) may only be accepted or sent back for more evidence."""

    BLOCKED_TEXT = "highest protein responded best to therapy"

    def assertRefused(self, decision):
        with self.assertRaises(ValueError) as cm:
            AJ.build_review(make_doc(), {"claim-003": decision})
        msg = str(cm.exception)
        self.assertEqual(msg, "claim-003: " + AJ.BLOCKED_OVERRIDE_ERROR)
        self.assertNotIn(self.BLOCKED_TEXT, msg)  # never echoes claim text or the note
        self.assertNotIn("secret note", msg)

    def test_override_of_a_blocked_claim_is_refused(self):
        for verdict in ("supported", "contradicted", "insufficient_evidence", None):
            with self.subTest(verdict=verdict):
                self.assertRefused({"decision": "reject", "verdict": verdict, "note": "secret note"})

    def test_any_other_verdict_on_a_blocked_claim_is_refused(self):
        for d in ({"verdict": "supported"}, {"decision": "approve", "verdict": "supported"},
                  {"decision": "approve", "verdict": "contradicted"}, {"decision": "more", "verdict": "supported"}):
            with self.subTest(decision=d):
                self.assertRefused(dict(d, note="secret note"))

    def test_every_blocking_flag_is_guarded(self):
        for flag in sorted(AJ.BLOCKING_FLAGS):
            doc = make_doc()
            doc["findings"][0]["guardrail_flags"] = [flag]  # claim-001 is "supported" in the engine document
            with self.subTest(flag=flag), self.assertRaises(ValueError) as cm:
                AJ.build_review(doc, {"claim-001": {"decision": "reject", "verdict": "contradicted"}})
            self.assertIn(AJ.BLOCKED_OVERRIDE_ERROR, str(cm.exception))

    def test_low_event_count_is_not_a_block(self):
        doc = make_doc()
        doc["findings"][0]["guardrail_flags"] = ["low_event_count", "data_cannot_answer"]
        items = AJ.build_review(doc, {"claim-001": {"decision": "reject", "verdict": "contradicted"}})["items"]
        self.assertEqual(items[0]["status"], "overridden")

    def test_accept_records_insufficient_evidence(self):
        for d in ({"decision": "approve"}, {"decision": "approve", "verdict": "insufficient_evidence"}):
            with self.subTest(decision=d):
                item = AJ.build_review(make_doc(), {"claim-003": d})["items"][2]
                self.assertEqual((item["status"], item["human_decision"], item["human_verdict"], item["machine_verdict"]),
                                 ("accepted", "approve", "insufficient_evidence", "insufficient_evidence"))

    def test_accept_of_a_blocked_claim_never_counts_as_an_override(self):
        doc = make_doc()
        doc["findings"][0]["guardrail_flags"] = ["prompt_injection_suspected"]  # machine verdict "supported"
        item = AJ.build_review(doc, {"claim-001": {"decision": "approve"}})["items"][0]
        self.assertEqual((item["status"], item["human_verdict"]), ("accepted", "insufficient_evidence"))

    def test_ask_for_more_evidence_is_allowed(self):
        for d in ({"decision": "more"}, {"decision": "more", "verdict": "insufficient_evidence"}):
            with self.subTest(decision=d):
                review = AJ.build_review(make_doc(), {"claim-003": dict(d, note="needs records")})
                item = review["items"][2]
                self.assertEqual(item["status"], "more_evidence_requested")
                self.assertEqual(item["note"], "needs records")
                self.assertEqual(review["counts"]["overridden"], 0)

    def test_pending_blocked_claim_is_allowed(self):
        item = AJ.build_review(make_doc(), {"claim-003": {"note": "looked at it"}})["items"][2]
        self.assertEqual((item["status"], item["human_verdict"]), ("pending", None))

    def test_unblocked_claims_can_still_be_overridden(self):
        items = AJ.build_review(make_doc(), {"claim-002": {"decision": "reject", "verdict": "supported"}})["items"]
        self.assertEqual(items[1]["status"], "overridden")

    def test_flag_set_matches_the_guardrails_and_the_app(self):
        from src.guardrails import BLOCKING_FLAGS
        self.assertEqual(AJ.BLOCKING_FLAGS, BLOCKING_FLAGS)
        with open(os.path.join(ROOT, "app", "js", "state.js"), encoding="utf-8") as fh:
            js = fh.read()
        block = js[js.index("export const BLOCKED = ["):]
        block = block[:block.index("];")]
        self.assertEqual(set(re.findall(r"'([a-z_]+)'", block)), set(AJ.BLOCKING_FLAGS))
        self.assertIn("'" + AJ.BLOCKED_OVERRIDE_ERROR + "'", js)  # the app shows the same fixed message

    def test_make_audit_refuses_a_blocked_override_without_claim_text(self):
        mod = load_make_audit()
        with tempfile.TemporaryDirectory() as tmp:
            dec = os.path.join(tmp, "decisions.json")
            with open(dec, "w", encoding="utf-8") as fh:
                json.dump({"claim-003": {"decision": "reject", "verdict": "supported"}}, fh)
            data = os.path.join(tmp, "data")
            os.makedirs(data)
            with open(os.path.join(data, "sources.csv"), "w", encoding="utf-8", newline="") as fh:
                fh.write("file,sha256\n" + "".join(f"{x['file']},{x['sha256']}\n" for x in FILES))
            report = os.path.join(tmp, "r.md")
            with open(report, "w", encoding="utf-8") as fh:
                fh.write("x\n")
            fake_ctx = mock.Mock(checksums={"status": "verified"})
            err = io.StringIO()
            with mock.patch.object(mod.E, "extract_claims", return_value=(["c"], [])), \
                    mock.patch.object(mod.E, "Context", return_value=fake_ctx), \
                    mock.patch.object(mod.E, "audit", return_value=make_doc()), \
                    contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = mod.main([report, "--data-dir", data, "--out", os.path.join(tmp, "audit.json"), "--decisions", dec])
            self.assertEqual(code, 2)
            self.assertIn(AJ.BLOCKED_OVERRIDE_ERROR, err.getvalue())
            self.assertNotIn(self.BLOCKED_TEXT, err.getvalue())
            self.assertFalse(os.path.exists(os.path.join(tmp, "audit.json")))


def load_make_audit():
    spec = importlib.util.spec_from_file_location("make_audit", MAKE_AUDIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMakeAuditPostCheck(unittest.TestCase):
    """A post-check refusal writes nothing and never prints claim text."""

    def test_postcheck_error_is_caught_without_claim_text(self):
        ma = load_make_audit()
        secret = "Zebracorn"
        with tempfile.TemporaryDirectory() as tmp:
            report = os.path.join(tmp, "report.md")
            with open(report, "w", encoding="utf-8") as fh:
                fh.write(f"{secret} tumors have RNA data for most samples.\n")
            data = os.path.join(tmp, "data")
            os.makedirs(data)
            with open(os.path.join(data, "sources.csv"), "w", encoding="utf-8") as fh:
                fh.write("file,sha256\nclinical.tsv," + "1" * 64 + "\n")
            out = os.path.join(tmp, "out", "audit.json")
            problems = [f"claim-001: cohort step '{secret} tumors' grows the cohort",
                        f'claim-001: unknown guardrail flag "{secret}"']
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(ma.E, "Context", lambda *a, **k: object()), \
                    mock.patch.object(ma.E, "audit", side_effect=ma.E.PostCheckError(problems)), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = ma.main([report, "--data-dir", data, "--out", out])
            printed = stdout.getvalue() + stderr.getvalue()
            self.assertEqual(code, 3)
            self.assertNotIn(secret, printed)
            self.assertIn("2 problem(s)", printed)
            self.assertIn("claim-001: cohort step [withheld] grows the cohort", printed)
            self.assertFalse(os.path.exists(out))
            self.assertFalse(os.path.exists(os.path.join(tmp, "out", "review.json")))


@unittest.skipIf(DATA_DIR is None or not os.path.isfile(BRIEF), "TCGA-BRCA data or the practice brief not found")
class TestPracticeBriefEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        out = os.path.join(cls.tmp.name, "audit.json")
        cls.proc = subprocess.run([sys.executable, MAKE_AUDIT, BRIEF, "--data-dir", DATA_DIR, "--out", out],
                                  cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=900)
        cls.out = out
        cls.audit = read_json(out)
        cls.review = read_json(os.path.join(cls.tmp.name, "review.json"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_runs_and_writes_both_files(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr[-2000:])
        self.assertIsNotNone(self.audit)
        self.assertEqual(len(self.review["items"]), len(self.audit["findings"]))

    def test_practice_verdicts(self):
        f = by_id(self.audit)
        self.assertEqual([x["claim_verdict"] for x in self.audit["findings"]],
                         ["supported", "contradicted", "insufficient_evidence"])
        self.assertEqual(f["claim-002"]["correct_value"], "49.9% (421 of 844)")
        self.assertIn("62%", f["claim-002"]["claim_text"])
        self.assertIn("Data needed:", f["claim-003"]["summary"])
        self.assertTrue(f["claim-003"]["needs_human_review"])

    def test_release_checksums_come_from_sources_csv(self):
        self.assertEqual(self.audit["data"]["releases"][0]["files"], AJ.read_sources(DATA_DIR))

    @unittest.skipIf(VALIDATOR is None, NO_VALIDATOR)
    def test_validates_with_the_organizers_validator(self):
        self.assertEqual(VALIDATOR.check(self.out), [])


if __name__ == "__main__":
    unittest.main()
