"""Contract tests: run the draft validator on findings files.

Run from the repo root:  python -m unittest discover -s tests -v
(pytest also works if installed.)

The real-data classes run src/engine/engine.py on the frozen TCGA-BRCA release.
They look for the data in $TCGA_DATA_DIR, then ../challenge-ref/data/tcga-brca,
and skip cleanly if neither exists.
"""
import copy
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "contract"))
sys.path.insert(0, os.path.join(ROOT, "src"))
import validate_findings as vf  # noqa: E402

try:
    import guardrails as G  # noqa: E402
except ImportError:  # not written yet
    G = None

MOCK = os.path.join(ROOT, "contract", "mock_findings.json")
ENGINE = os.path.join(ROOT, "src", "engine", "engine.py")
BANK = os.path.join(ROOT, "tests", "edge_cases.csv")
# Flags set by the guardrail pre-check. invalid_input is left out on purpose:
# the engine also sets it for impossible percentages on claims the pre-check allowed.
PRECHECK_FLAGS = {"clinical_claim_blocked", "individual_level_request_blocked", "reidentification_blocked",
                  "phi_like_input", "prompt_injection_suspected"}


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
NO_DATA = "TCGA-BRCA data not found (set TCGA_DATA_DIR or fetch ../challenge-ref)"


def run_engine(args, io_encoding="utf-8"):
    """Run the engine into a temp file. Returns (CompletedProcess, findings doc or None)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "findings.json")
        env = dict(os.environ, PYTHONIOENCODING=io_encoding)
        proc = subprocess.run([sys.executable, ENGINE, "--data-dir", DATA_DIR, "--out", out] + list(args),
                              cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=900)
        doc = None
        if os.path.exists(out):
            with open(out, encoding="utf-8") as fh:
                doc = json.load(fh)
    return proc, doc


def bank_rows():
    with open(BANK, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


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


@unittest.skipIf(G is None, "src/guardrails not implemented yet")
class TestPostCheck(unittest.TestCase):
    """guardrails.check_finding: the contract validator plus stricter invariants."""

    def setUp(self):
        self.doc = load()
        self.by_id = {f["id"]: copy.deepcopy(f) for f in self.doc["findings"]}

    def test_mock_file_passes(self):
        self.assertEqual(G.check_document(self.doc), [])

    def test_blocked_finding_with_a_number_fails(self):
        f = self.by_id["mock-004"]  # clinical_claim_blocked
        f["evidence"]["value"] = 0.5
        self.assertTrue(G.check_finding(f))
        f = self.by_id["mock-007"]  # individual_level_request_blocked
        f["verdict"] = "supported"
        self.assertTrue(G.check_finding(f))

    def test_blocked_finding_without_review_fails(self):
        f = self.by_id["mock-004"]
        f["needs_human_review"], f["review_reason"] = False, None
        self.assertTrue(G.check_finding(f))

    def test_cannot_answer_with_a_verdict_fails(self):
        f = self.by_id["mock-008"]
        f["verdict"] = "contradicted"
        self.assertTrue(G.check_finding(f))

    def test_low_event_count_without_review_fails(self):
        f = self.by_id["mock-003"]
        f["needs_human_review"], f["review_reason"] = False, None
        self.assertTrue(G.check_finding(f))

    def test_thin_breakdown_without_low_event_flag_fails(self):
        f = self.by_id["mock-001"]
        f["evidence"]["breakdown"] = [{"group": "A", "n": 50, "events": G.POSTCHECK_CONFIG["min_events"] - 1}]
        self.assertTrue(G.check_finding(f))

    def test_value_that_does_not_match_its_counts_fails(self):
        f = self.by_id["mock-001"]
        f["evidence"]["metric_name"] = "coverage_has_rna"
        f["evidence"]["value"] = 0.5
        f["evidence"]["n_samples"], f["evidence"]["denominator"] = 90, 100
        f["cohort_trace"] = [{"step": "primary tumor samples", "n_before": 100, "n_after": 100},
                             {"step": "has RNA", "n_before": 100, "n_after": 90}]
        self.assertTrue(G.check_finding(f))
        f["evidence"]["value"] = 0.9
        self.assertEqual(G.check_finding(f), [])

    def test_trace_that_does_not_end_at_n_samples_fails(self):
        f = self.by_id["mock-002"]
        f["cohort_trace"][-1]["n_after"] = f["evidence"]["n_samples"] - 1
        self.assertTrue(any("trace ends" in p for p in G.check_finding(f)))

    def test_overclaiming_text_fails(self):
        f = self.by_id["mock-001"]
        f["limitation"] = "This finding is production ready."  # allow-phrase
        self.assertTrue(G.check_finding(f))

    def test_real_output_needs_release_and_real_guardrails(self):
        doc = copy.deepcopy(self.doc)
        doc["is_mock"] = False
        doc["data_release"] = {"name": "TCGA-BRCA", "checksum_status": "verified"}
        doc["guardrails_source"] = "built-in fallback"
        self.assertTrue(any("guardrails_source" in p for p in G.check_document(doc)))
        doc["guardrails_source"] = "src/guardrails"
        self.assertEqual(G.check_document(doc), [])
        del doc["data_release"]["checksum_status"]
        self.assertTrue(G.check_document(doc))

    def test_garbage_does_not_crash(self):
        for bad in [None, [], {}, {"findings": None}, {"findings": [None, 3, {}]}]:
            with self.subTest(bad=repr(bad)):
                self.assertIsInstance(G.check_document(bad), list)


@unittest.skipIf(DATA_DIR is None, NO_DATA)
class TestRealFindingsDemoReport(unittest.TestCase):
    """Run the engine on contract/demo_report.md and check every real finding."""

    @classmethod
    def setUpClass(cls):
        cls.proc, cls.doc = run_engine(["--report", os.path.join("contract", "demo_report.md"), "--notes"])

    def setUp(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr[-2000:])
        self.assertIsNotNone(self.doc, "engine wrote no findings file")
        self.findings = {f["id"]: f for f in self.doc["findings"]}

    def test_engine_uses_src_guardrails(self):
        self.assertIn("Guardrails: src/guardrails", self.proc.stdout)
        self.assertEqual(self.doc["guardrails_source"], "src/guardrails")

    def test_every_finding_passes_the_contract_validator(self):
        self.assertEqual(len(self.findings), 11)
        for fid, f in self.findings.items():
            with self.subTest(finding=fid):
                self.assertEqual(vf.check_finding(f), [])

    @unittest.skipIf(G is None, "src/guardrails not implemented yet")
    def test_every_finding_passes_the_post_check(self):
        self.assertEqual(G.check_document(self.doc), [])

    def test_release_and_checksum_are_reported(self):
        rel = self.doc["data_release"]
        self.assertTrue(rel["name"])
        self.assertTrue(rel["checksum_status"])
        self.assertFalse(self.doc["is_mock"])

    def test_clinical_and_individual_claims_are_blocked_without_numbers(self):
        expected = {"claim-009": "clinical_claim_blocked", "claim-010": "individual_level_request_blocked"}
        for fid, flag in expected.items():
            with self.subTest(finding=fid):
                f = self.findings[fid]
                self.assertIn(flag, f["guardrail_flags"])
                self.assertEqual(f["verdict"], "insufficient_evidence")
                self.assertIsNone(f["evidence"]["value"])
                self.assertEqual(f["evidence"]["n_samples"], 0)
                self.assertTrue(f["needs_human_review"])
                self.assertTrue(f["review_reason"])

    def test_missing_field_is_data_cannot_answer(self):
        f = self.findings["claim-011"]  # smoking history
        self.assertEqual(f["verdict"], "insufficient_evidence")
        self.assertIn("data_cannot_answer", f["guardrail_flags"])

    def test_data_questions_are_not_blocked(self):
        for i in range(1, 9):
            f = self.findings[f"claim-{i:03d}"]
            with self.subTest(finding=f["id"], claim=f["claim_text"]):
                self.assertFalse(PRECHECK_FLAGS & set(f["guardrail_flags"]), "false block on a data question")

    def test_every_number_has_a_calculation_and_source(self):
        for fid, f in self.findings.items():
            if f["evidence"]["value"] is None:
                continue
            with self.subTest(finding=fid):
                self.assertTrue(f["evidence"]["calculation"].strip())
                self.assertTrue(f["evidence"]["source_files"])
                self.assertTrue(f["cohort_trace"])
                self.assertTrue(f["limitation"].strip())


@unittest.skipIf(DATA_DIR is None, NO_DATA)
class TestRealFindingsSampleClaims(unittest.TestCase):
    """contract/sample_claims_v11.md holds 14 data questions: none may be blocked."""

    @classmethod
    def setUpClass(cls):
        cls.proc, cls.doc = run_engine(["--report", os.path.join("contract", "sample_claims_v11.md")])

    def test_no_false_blocks_and_contract_holds(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr[-2000:])
        self.assertEqual(len(self.doc["findings"]), 14)
        for f in self.doc["findings"]:
            with self.subTest(finding=f["id"], claim=f["claim_text"]):
                self.assertFalse(PRECHECK_FLAGS & set(f["guardrail_flags"]))
                self.assertEqual(vf.check_finding(f), [])
        if G is not None:
            self.assertEqual(G.check_document(self.doc), [])


@unittest.skipIf(DATA_DIR is None, NO_DATA)
class TestBankThroughTheEngine(unittest.TestCase):
    """Every row of tests/edge_cases.csv, end to end through the real engine."""

    @classmethod
    def setUpClass(cls):
        cls.rows = [r for r in bank_rows() if r["claim_text"].strip()]  # the CLI drops empty claims
        args = []
        for r in cls.rows:
            args += ["--claim", r["claim_text"]]
        cls.proc, cls.doc = run_engine(args)

    def setUp(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr[-2000:])
        self.pairs = list(zip(self.rows, self.doc["findings"]))
        self.assertEqual(len(self.pairs), len(self.rows))

    def test_blocked_rows_never_show_a_number_or_supported(self):
        for r, f in self.pairs:
            if r["expected_action"] not in ("block", "reject_input"):
                continue
            with self.subTest(case=r["id"]):
                self.assertIn(r["expected_flag"], f["guardrail_flags"])
                self.assertEqual(f["verdict"], "insufficient_evidence")
                self.assertIsNone(f["evidence"]["value"])
                self.assertTrue(f["needs_human_review"])

    def test_allowed_rows_are_not_blocked_by_the_engine_either(self):
        for r, f in self.pairs:
            if r["expected_action"] != "allow":
                continue
            with self.subTest(case=r["id"]):
                self.assertFalse(PRECHECK_FLAGS & set(f["guardrail_flags"]))

    def test_every_finding_passes_the_contract(self):
        for r, f in self.pairs:
            with self.subTest(case=r["id"]):
                self.assertEqual(vf.check_finding(f), [])
                if G is not None:
                    self.assertEqual(G.check_finding(f), [])

    def test_engine_level_rows_get_no_verdict(self):
        for r, f in self.pairs:
            if r["expected_action"] != "engine_refuses":
                continue
            with self.subTest(case=r["id"]):
                self.assertEqual(f["verdict"], "insufficient_evidence")

    def test_engine_level_rows_carry_their_expected_flag(self):
        # Regression test for engine v1.1.2: association claims on a field that is not
        # loaded ("Smoking history correlates with survival") are data_cannot_answer,
        # and readiness claims on a loaded field (e01, e08) show group sizes with
        # low_event_count. Each row names the flag it needs in expected_flag.
        for r, f in self.pairs:
            if r["expected_action"] != "engine_refuses":
                continue
            with self.subTest(case=r["id"]):
                self.assertIn(r["expected_flag"], f["guardrail_flags"])

    def test_stored_claim_text_carries_no_identifiers(self):
        # Regression test for engine v1.1.2: claims blocked for personal details are
        # withheld, and individual-level or re-identification claims are stored redacted.
        for r, f in self.pairs:
            flags = set(f["guardrail_flags"])
            if not flags & {"phi_like_input", "individual_level_request_blocked", "reidentification_blocked"}:
                continue
            with self.subTest(case=r["id"]):
                stored = f["claim_text"]
                if "phi_like_input" in flags:
                    self.assertNotEqual(stored, r["claim_text"], "personal details must be withheld")
                # Text with nothing identifying in it ("Look up the patients on social media") is kept as is.
                self.assertIsNone(re.search(r"tcga-[a-z0-9]{2}-[a-z0-9]{4}", stored, re.I))
                if G is not None:
                    self.assertNotIn("phi_like_input", G.check_claim(stored)["flags"])


@unittest.skipIf(DATA_DIR is None, NO_DATA)
class TestEngineOutputEncoding(unittest.TestCase):
    def test_claim_with_non_cp1252_character_still_writes_findings(self):
        # Regression test for engine v1.1.2: on Windows a piped stdout is cp1252, and
        # printing a claim with a sign such as "greater than or equal" used to crash
        # the engine before it wrote the JSON. Now the JSON is written first and the
        # streams replace characters they cannot show.
        proc, doc = run_engine(["--claim", "RNA data is available for ≥ 90 percent of samples."], io_encoding="cp1252")
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIsNotNone(doc)
        self.assertIn("≥", doc["findings"][0]["claim_text"])


@unittest.skipIf(DATA_DIR is None, NO_DATA)
class TestEngineRequiresGuardrails(unittest.TestCase):
    """Regression test for engine v1.1.2: no silent fallback when src/guardrails is missing."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = cls.tmp.name
        for part in (("src", "engine"), ("src", "data"), ("contract",)):
            shutil.copytree(os.path.join(ROOT, *part), os.path.join(root, *part),
                            ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(os.path.join(ROOT, "src", "__init__.py"), os.path.join(root, "src", "__init__.py"))
        cls.engine = os.path.join(root, "src", "engine", "engine.py")
        cls.out = os.path.join(root, "findings.json")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_copy(self, *extra):
        return subprocess.run([sys.executable, self.engine, "--data-dir", DATA_DIR, "--out", self.out,
                               "--claim", "RNA data is available for most samples."] + list(extra),
                              cwd=self.tmp.name, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=900)

    def test_refuses_to_run_without_guardrails(self):
        proc = self.run_copy()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("src/guardrails is missing", proc.stderr)
        self.assertFalse(os.path.exists(self.out))

    @unittest.skipIf(G is None, "src/guardrails not implemented yet")
    def test_unsafe_fallback_is_caught_by_the_post_check(self):
        proc = self.run_copy("--unsafe-no-guardrails")
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        with open(self.out, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertTrue(any("guardrails_source" in p for p in G.check_document(doc)))


class TestEngineParsesNegativeNumbers(unittest.TestCase):
    """Regression test for engine v1.1.2: the engine itself rejects negative numbers,
    even if a claim reached it without the guardrail pre-check."""

    def test_negative_numbers_are_invalid(self):
        sys.path.insert(0, ROOT)
        try:
            from src.engine import engine as E
        finally:
            sys.path.remove(ROOT)
        self.assertEqual(E.parse_claim("Protein data covers -20 percent of the cohort.")["type"], "invalid")
        self.assertEqual(E.parse_claim("At least -5 samples have RNA data.")["type"], "invalid")
        self.assertNotEqual(E.parse_claim("Between 10-20 percent of tumors are lobular.")["type"], "invalid")


if __name__ == "__main__":
    unittest.main()
