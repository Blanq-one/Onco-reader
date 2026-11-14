"""audit.json for any release folder, including one with no sources.csv.

With sources.csv the checksums come from it, exactly as before (the output for the frozen release is byte-for-byte the
committed out/audit.json). Without it, the SHA-256 of every data file found in the folder is computed and listed, and the
document and every limitation say so. A file a release does not have is not listed and nothing crashes.
Synthetic folders always run; the opened practice release and the frozen release run when they are there."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import http.client
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_engine_claims import DATA_DIR, write_release  # noqa: E402
from server import serve as S  # noqa: E402
from src.engine import engine as E  # noqa: E402
from src.export import audit_json as AJ  # noqa: E402

_spec = importlib.util.spec_from_file_location("make_audit", os.path.join(ROOT, "scripts", "make_audit.py"))
make_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_audit)

CHALLENGE = os.path.abspath(os.path.join(ROOT, "..", "challenge-ref"))
PRACTICE_RELEASE = os.path.join(CHALLENGE, "envelopes", "opened", "practice", "release")
VALIDATOR = os.path.join(CHALLENGE, "format", "validate.py")
BRIEF = os.path.join(ROOT, "app", "samples", "practice_brief.md")
SENTENCE = "Checksums not checked against a frozen list"
REPORT = "1. There are 2 metastatic samples.\n2. Mutation data is available for about 90 percent of primary tumors.\n"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def validate(path):
    """Run the organizers' validator; returns (ok, message), or None when it cannot run here."""
    if not os.path.isfile(VALIDATOR) or importlib.util.find_spec("jsonschema") is None:
        return None
    run = subprocess.run([sys.executable, VALIDATOR, path], capture_output=True, text=True, timeout=60)
    return run.returncode == 0, (run.stdout + run.stderr).strip()


def make(report_path, data_dir, out_dir):
    out = os.path.join(out_dir, "audit.json")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        code = make_audit.main([report_path, "--data-dir", data_dir, "--out", out, "--review-out", os.path.join(out_dir, "review.json")])
    return code, out


class TestComputeFiles(unittest.TestCase):
    def test_lists_every_data_file_sorted_with_its_own_checksum(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "raw"))
            for name, text in (("raw/clinical.tsv", "a"), ("raw/survival.tsv", "b"), ("sample_manifest.csv", "c"), ("raw/rna_hiseq.tsv.gz", "d")):
                with open(os.path.join(d, name), "w") as fh:
                    fh.write(text)
            files = AJ.compute_files(d)
            self.assertEqual([f["file"] for f in files], ["clinical.tsv", "rna_hiseq.tsv.gz", "sample_manifest.csv", "survival.tsv"])
            for f in files:
                path = os.path.join(d, "raw", f["file"]) if os.path.exists(os.path.join(d, "raw", f["file"])) else os.path.join(d, f["file"])
                self.assertEqual(f["sha256"], sha(path))

    def test_skips_hidden_non_data_and_sources_csv_and_folders(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("clinical.tsv", ".hidden.tsv", "README.txt", "sources.csv", "notes.md"):
                with open(os.path.join(d, name), "w") as fh:
                    fh.write("x")
            os.makedirs(os.path.join(d, "folder.tsv"))
            self.assertEqual([f["file"] for f in AJ.compute_files(d)], ["clinical.tsv"])

    def test_an_empty_folder_is_an_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            AJ.compute_files(d)

    def test_release_files_prefers_sources_csv(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "clinical.tsv"), "w") as fh:
                fh.write("x")
            self.assertEqual(AJ.release_files(d)[1], AJ.COMPUTED)
            with open(os.path.join(d, "sources.csv"), "w") as fh:
                fh.write("file,sha256\nclinical.tsv," + "a" * 64 + "\n")
            files, how = AJ.release_files(d)
            self.assertEqual((how, files[0]["sha256"]), ("sources.csv", "a" * 64))


class TestSyntheticReleaseWithoutSources(unittest.TestCase):
    def audit_of(self, remove=(), flat=True, manifests=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        write_release(tmp.name, mutation_rows={"TP53": []}, flat=flat, manifests=manifests)
        for name in remove:
            for folder in (tmp.name, os.path.join(tmp.name, "raw")):
                if os.path.exists(os.path.join(folder, name)):
                    os.remove(os.path.join(folder, name))
        report = os.path.join(tmp.name, "report.md")
        with open(report, "w") as fh:
            fh.write(REPORT)
        code, out = make(report, tmp.name, tmp.name)
        self.assertEqual(code, 0)
        with open(out) as fh:
            return tmp, json.load(fh), out

    def check_computed(self, tmp, audit, out, expect_files):
        rel = audit["data"]["releases"][0]
        self.assertEqual([f["file"] for f in rel["files"]], sorted(expect_files))
        self.assertEqual(rel["checksum_source"], "computed locally")
        self.assertIn("not compared with a frozen list", rel["checksum_note"])
        for f in audit["findings"]:
            self.assertTrue(f["limitation"].endswith("so these results may not describe the frozen release."))
            self.assertEqual(f["limitation"].count(SENTENCE), 1)
        for f in rel["files"]:
            path = next(p for p in (os.path.join(tmp.name, f["file"]), os.path.join(tmp.name, "raw", f["file"])) if os.path.exists(p))
            self.assertEqual(f["sha256"], sha(path))
        v = validate(out)
        if v is not None:
            self.assertTrue(v[0], v[1])

    def test_all_files_present(self):
        tmp, audit, out = self.audit_of()
        self.check_computed(tmp, audit, out, ["clinical.tsv", "survival.tsv", "mutation_gene_level.tsv.gz", "sample_manifest.csv", "slide_manifest.csv"])

    def test_missing_survival_and_mutation_files(self):
        tmp, audit, out = self.audit_of(remove=("survival.tsv", "mutation_gene_level.tsv.gz"))
        self.check_computed(tmp, audit, out, ["clinical.tsv", "sample_manifest.csv", "slide_manifest.csv"])

    def test_no_manifests_and_raw_layout(self):
        tmp, audit, out = self.audit_of(flat=False, manifests=False)
        self.check_computed(tmp, audit, out, ["clinical.tsv", "survival.tsv", "mutation_gene_level.tsv.gz"])

    def test_only_the_clinical_file(self):
        tmp, audit, out = self.audit_of(remove=("survival.tsv", "mutation_gene_level.tsv.gz", "sample_manifest.csv", "slide_manifest.csv"))
        self.check_computed(tmp, audit, out, ["clinical.tsv"])

    def test_a_file_the_release_lacks_is_not_called_unlisted_in_sources_csv(self):
        _, audit, _ = self.audit_of(manifests=False, flat=False)
        notes = [e.get("note") or "" for f in audit["findings"] for e in f["evidence"] if e["kind"] == "file"]
        self.assertFalse(any("sources.csv" in n for n in notes))
        self.assertTrue(any("not found in this release folder" in n for n in notes))


@unittest.skipUnless(os.path.isdir(PRACTICE_RELEASE), "the opened practice release folder is not there")
class TestOpenedPracticeRelease(unittest.TestCase):
    def test_audit_json_lists_the_files_that_exist_with_their_checksums(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = make(BRIEF, PRACTICE_RELEASE, d)
            self.assertEqual(code, 0)
            with open(out) as fh:
                audit = json.load(fh)
            rel = audit["data"]["releases"][0]
            present = sorted(n for n in os.listdir(PRACTICE_RELEASE) if os.path.isfile(os.path.join(PRACTICE_RELEASE, n)))
            self.assertEqual([f["file"] for f in rel["files"]], present)
            for f in rel["files"]:
                self.assertEqual(f["sha256"], sha(os.path.join(PRACTICE_RELEASE, f["file"])))
            self.assertEqual(rel["checksum_source"], "computed locally")
            self.assertTrue(all(SENTENCE in f["limitation"] for f in audit["findings"]))
            v = validate(out)
            if v is not None:
                self.assertTrue(v[0], v[1])


@unittest.skipIf(DATA_DIR is None, "TCGA-BRCA data not found")
class TestFrozenReleaseUnchanged(unittest.TestCase):
    def test_output_is_byte_for_byte_the_committed_audit_json(self):
        committed = os.path.join(ROOT, "out", "audit.json")
        with tempfile.TemporaryDirectory() as d:
            code, out = make(BRIEF, DATA_DIR, d)
            self.assertEqual(code, 0)
            with open(out, "rb") as a, open(committed, "rb") as b:
                self.assertEqual(a.read(), b.read())

    def test_a_frozen_release_has_no_computed_marker(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = make(BRIEF, DATA_DIR, d)
            with open(out) as fh:
                rel = json.load(fh)["data"]["releases"][0]
            self.assertNotIn("checksum_source", rel)


class TestServerWithoutSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        write_release(cls.tmp.name, mutation_rows={"TP53": []}, flat=True)
        files, how = AJ.release_files(cls.tmp.name)
        cls.srv = S.Server(("127.0.0.1", 0), E.Context(cls.tmp.name), files, True, how)
        cls.port = cls.srv.server_address[1]
        cls.log = io.StringIO()
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close(); cls.tmp.cleanup()

    def post(self, path, body):
        with contextlib.redirect_stderr(self.log):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
            c.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
            r = c.getresponse()
            data = json.loads(r.read().decode())
            c.close()
        return r.status, data

    def test_the_app_is_told_the_checksums_were_not_checked_against_a_frozen_list(self):
        status, doc = self.post("/api/audit", {"report": REPORT})
        self.assertEqual(status, 200)
        self.assertEqual(doc["data_release"]["checksum_status"], "not checked against a frozen list")
        for f in doc["findings"]:
            self.assertEqual(f["limitation"].count(SENTENCE), 1)

    def test_audit_json_is_computed_marked_and_says_it_once(self):
        status, audit = self.post("/api/audit-json", {"report": REPORT})
        self.assertEqual(status, 200)
        rel = audit["data"]["releases"][0]
        self.assertEqual(rel["checksum_source"], "computed locally")
        self.assertEqual([f["file"] for f in rel["files"]], sorted(f["file"] for f in rel["files"]))
        for f in audit["findings"]:
            self.assertEqual(f["limitation"].count(SENTENCE), 1)

    def test_a_verified_release_is_left_alone(self):
        doc = {"data_release": {"checksum_status": "verified"}, "findings": [{"limitation": "L."}]}
        self.assertEqual(S.mark_unfrozen_checksums(doc), {"data_release": {"checksum_status": "verified"}, "findings": [{"limitation": "L."}]})


if __name__ == "__main__":
    unittest.main()
