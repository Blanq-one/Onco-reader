"""Engine claim types added in v1.3: sample-type and slide counts, sentences with several counts,
ranges, gene-level mutation claims, and survival comparisons.

Run from the repo root:  python -m unittest discover -s tests -v

Two kinds of test:
  - Synthetic: a tiny release written to a temp folder, so the expected numbers are known exactly.
    These need no data and always run.
  - Real data: the engine's numbers on the frozen TCGA-BRCA release are compared with an
    independent pandas calculation. They skip when the data folder or pandas is missing.
Every finding is also run through the guardrails post-check.
"""
import csv
import gzip
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.engine import engine as E  # noqa: E402
from src.guardrails.postcheck import check_finding  # noqa: E402

try:
    import pandas as pd
except ImportError:  # pandas is only needed for the independent checks on real data
    pd = None


def find_data_dir():
    for cand in (os.environ.get("TCGA_DATA_DIR"), os.path.join("..", "challenge-ref", "data", "tcga-brca")):
        if not cand:
            continue
        path = cand if os.path.isabs(cand) else os.path.join(ROOT, cand)
        if os.path.isfile(os.path.join(path, "raw", "clinical.tsv")):
            return os.path.abspath(path)
    return None


DATA_DIR = find_data_dir()
NO_REAL = "TCGA-BRCA data or pandas not found"


# ---------- a tiny synthetic release ----------
def _bc(i, code="01"):
    return f"TCGA-ZZ-{i:04d}-{code}"


PRIMARY = [_bc(i) for i in range(1, 41)]                      # 40 primary tumors, patients 1..40
NORMAL = [_bc(i, "11") for i in (1, 2, 3, 4, 5)]               # 5 normal tissue samples
METASTASIS = [_bc(i, "06") for i in (6, 7)]                    # 2 metastases
SLIDE_KINDS = ["diagnostic (FFPE)"] * 12 + ["frozen, top section"] * 6 + ["frozen, bottom section"] * 3   # 21 slides
# Gene-level mutation file: the first 30 primary tumors were profiled; 1 means mutated.
MUTATIONS = {"PIK3CA": PRIMARY[:12], "TP53": PRIMARY[:10], "GATA3": PRIMARY[:4], "CDH1": PRIMARY[:2], "TTN": []}


def write_release(folder, mutation_rows=None, er=None):
    """Write sample_manifest.csv, slide_manifest.csv and raw/ files; returns the folder."""
    raw = os.path.join(folder, "raw")
    os.makedirs(raw, exist_ok=True)
    samples = PRIMARY + NORMAL + METASTASIS
    types = {"01": "Primary Tumor", "11": "Solid Tissue Normal", "06": "Metastatic"}
    with open(os.path.join(folder, "sample_manifest.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sample_id", "patient_id", "sample_type", "in_clinical", "has_survival", "has_mutation",
                    "has_copy_number", "has_rna", "has_protein", "slides_for_sample"])
        for s in samples:
            w.writerow([s, s[:12], types[s[13:15]], True, True, s in PRIMARY[:30], False, False, False, 1])
    with open(os.path.join(folder, "slide_manifest.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["slide_barcode", "sample_id", "patient_id", "slide_kind", "objective"])
        for i, kind in enumerate(SLIDE_KINDS):
            s = PRIMARY[i % len(PRIMARY)]
            w.writerow([f"{s}A-01-X{i}", s, s[:12], kind, 40])
    er = er or {s: ("Positive" if i < 30 else "Negative") for i, s in enumerate(PRIMARY)}
    with open(os.path.join(raw, "clinical.tsv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["sampleID", "breast_carcinoma_estrogen_receptor_status", "radiation_therapy",
                    "targeted_molecular_therapy", "additional_pharmaceutical_therapy"])
        for s in samples:
            w.writerow([s, er.get(s, ""), "YES", "NO", ""])
    with open(os.path.join(raw, "survival.tsv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["sample", "OS", "OS.time"])
        for i, s in enumerate(samples):
            w.writerow([s, 1 if i % 4 == 0 else 0, 100 + i])
    if mutation_rows is not None:
        cols = PRIMARY[:30]
        with gzip.open(os.path.join(raw, "mutation_gene_level.tsv.gz"), "wt", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["sample"] + cols)
            for gene, mutated in mutation_rows.items():
                w.writerow([gene] + [1 if c in mutated else 0 for c in cols])
    return folder


def check(ctx, text, case):
    """Evaluate one sentence the way the engine does, and fail on any post-check problem."""
    f = E.evaluate_item(ctx, "claim-001", {"text": text, "source": text})
    problems = check_finding(f)
    case.assertEqual(problems, [], f"post-check problems for {text!r}: {problems}")
    return f


def cv_text(f):
    return (f.get("correct_value") or {}).get("text")


class SyntheticCase(unittest.TestCase):
    mutation_rows = MUTATIONS

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        write_release(cls.tmp.name, mutation_rows=cls.mutation_rows)
        cls.ctx = E.Context(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def verdict(self, text):
        return check(self.ctx, text, self).get("verdict")


@unittest.skipIf(DATA_DIR is None or pd is None, NO_REAL)
class RealCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = E.Context(DATA_DIR)
        cls.manifest = pd.read_csv(os.path.join(DATA_DIR, "sample_manifest.csv"))
        cls.slides = pd.read_csv(os.path.join(DATA_DIR, "slide_manifest.csv"))

    def run_claim(self, text):
        return check(self.ctx, text, self)


# ---------- item 1: sample-type and slide counts ----------
class TestSampleTypeAndSlideCountsSynthetic(SyntheticCase):
    def test_sample_type_counts(self):
        f = check(self.ctx, "There are 5 normal-tissue samples.", self)
        self.assertEqual((f["verdict"], f["evidence"]["n_samples"], f["evidence"]["denominator"]), ("supported", 5, 47))
        self.assertEqual(f["evidence"]["source_files"], ["sample_manifest.csv (sample_type)"])
        self.assertEqual(self.verdict("There are 2 metastatic samples."), "supported")
        self.assertEqual(self.verdict("Only 2 samples are metastases."), "supported")
        self.assertEqual(self.verdict("There are 2 metastases."), "supported")
        self.assertEqual(self.verdict("There are 5 normal tissue samples."), "supported")

    def test_wrong_sample_type_count_gives_the_real_count(self):
        f = check(self.ctx, "There are 9 metastatic samples.", self)
        self.assertEqual(f["verdict"], "contradicted")
        self.assertEqual(f["correct_value"]["value"], 2)
        self.assertIn("2 metastasis samples", cv_text(f))

    def test_release_and_primary_counts(self):
        self.assertEqual(self.verdict("The release holds 47 samples."), "supported")
        self.assertEqual(self.verdict("There are 40 patients."), "supported")
        self.assertEqual(self.verdict("There are 40 primary tumor samples."), "supported")  # not all 47 samples

    def test_slide_counts_by_kind(self):
        for text, n in (("There are 12 diagnostic slides.", 12), ("There are 9 frozen sections.", 9),
                        ("There are 21 slides.", 21), ("There are 3 bottom sections.", 3)):
            f = check(self.ctx, text, self)
            self.assertEqual((f["verdict"], f["evidence"]["n_samples"], f["evidence"]["denominator"]), ("supported", n, 21), text)
            self.assertTrue(f["evidence"]["source_files"][0].startswith("slide_manifest.csv"))
        f = check(self.ctx, "There are 15 diagnostic slides.", self)
        self.assertEqual((f["verdict"], f["correct_value"]["value"]), ("contradicted", 12))
        self.assertEqual(self.verdict("At least 10 diagnostic slides are listed."), "supported")
        self.assertEqual(self.verdict("Fewer than 5 frozen sections exist."), "contradicted")

    def test_samples_with_slides_is_still_a_sample_count(self):
        f = check(self.ctx, "40 primary tumors have a pathology slide.", self)
        self.assertFalse(f["evidence"]["metric_name"].startswith("count_slides"))

    def test_no_slide_manifest_means_cannot_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_release(tmp)
            os.remove(os.path.join(tmp, "slide_manifest.csv"))
            f = check(E.Context(tmp), "There are 12 diagnostic slides.", self)
            self.assertEqual((f["verdict"], f["guardrail_flags"]), ("insufficient_evidence", ["data_cannot_answer"]))


class TestSampleTypeAndSlideCountsReal(RealCase):
    def test_sample_types_match_pandas(self):
        types = self.manifest.sample_type.value_counts()
        for text, name in (("There are {} metastatic samples.", "Metastatic"),
                           ("There are {} normal-tissue samples.", "Solid Tissue Normal")):
            n = int(types[name])
            f = self.run_claim(text.format(n))
            self.assertEqual((f["verdict"], f["evidence"]["n_samples"], f["evidence"]["denominator"]),
                             ("supported", n, len(self.manifest)))
            wrong = self.run_claim(text.format(n + 3))
            self.assertEqual((wrong["verdict"], wrong["correct_value"]["value"]), ("contradicted", n))
        self.assertEqual(self.run_claim(f"The release holds {len(self.manifest):,} samples.")["verdict"], "supported")

    def test_slide_counts_match_pandas(self):
        kinds = self.slides.slide_kind.str.lower()
        diag = int(kinds.str.contains("diagnostic|ffpe").sum())
        frozen = int(kinds.str.contains("frozen").sum())
        for text, n in ((f"There are {diag:,} diagnostic slides.", diag), (f"There are {frozen:,} frozen sections.", frozen),
                        (f"There are {len(self.slides):,} slides.", len(self.slides))):
            f = self.run_claim(text)
            self.assertEqual((f["verdict"], f["evidence"]["n_samples"]), ("supported", n), text)
        self.assertEqual((diag, frozen, len(self.slides)), (1133, 1978, 3111))  # the data README's numbers


# ---------- item 2: one check per count in a sentence ----------
def parts(f):
    return [(p["claim"], p["verdict"], p["n_samples"]) for p in f["evidence"].get("sub_checks", [])]


class TestSeveralCountsSynthetic(SyntheticCase):
    def test_shared_noun_is_borrowed(self):
        f = check(self.ctx, "There are 2 metastatic and 5 normal-tissue samples.", self)
        self.assertEqual(parts(f), [("There are 2 metastatic samples.", "supported", 2),
                                    ("There are 5 normal-tissue samples.", "supported", 5)])
        self.assertEqual(f["verdict"], "supported")

    def test_elided_noun_after_the_number(self):
        f = check(self.ctx, "Only 2 samples are metastases, and 5 are normal tissue.", self)
        self.assertEqual([p[1:] for p in parts(f)], [("supported", 2), ("supported", 5)])

    def test_samples_from_patients(self):
        f = check(self.ctx, "The release holds 47 samples from 40 patients.", self)
        self.assertEqual([p[1:] for p in parts(f)], [("supported", 47), ("supported", 40)])

    def test_one_wrong_count_contradicts_the_sentence_and_names_the_real_value(self):
        f = check(self.ctx, "The release holds 50 samples from 40 patients.", self)
        self.assertEqual([p[1] for p in parts(f)], ["contradicted", "supported"])
        self.assertEqual(f["verdict"], "contradicted")
        self.assertIn("47", cv_text(f))
        f = check(self.ctx, "There are 3 metastatic and 5 normal-tissue samples.", self)
        self.assertEqual((f["verdict"], [p[1] for p in parts(f)]), ("contradicted", ["contradicted", "supported"]))
        self.assertIn("2 metastasis samples", cv_text(f))

    def test_three_counts_and_slides(self):
        f = check(self.ctx, "The release has 40 primary tumors, 5 normal tissue samples and 2 metastases.", self)
        self.assertEqual([p[1:] for p in parts(f)], [("supported", 40), ("supported", 5), ("supported", 2)])
        f = check(self.ctx, "There are 12 diagnostic slides and 9 frozen sections.", self)
        self.assertEqual([p[1:] for p in parts(f)], [("supported", 12), ("supported", 9)])

    def test_not_split(self):
        for text in ("In 2018, 40 patients were enrolled.",                      # a year is not a count
                     "At least 30 ER-positive tumors and 10 deaths are recorded.",  # the second count depends on the first
                     "Between 30 and 50 primary tumors have survival data."):      # a range is one check
            self.assertEqual(E.split_subclaims(text), [text], text)


class TestSeveralCountsReal(RealCase):
    def test_counts_match_pandas(self):
        n_samples, n_patients = len(self.manifest), self.manifest.patient_id.nunique()
        types = self.manifest.sample_type.value_counts()
        met, normal = int(types["Metastatic"]), int(types["Solid Tissue Normal"])
        f = self.run_claim(f"The release holds {n_samples:,} samples from {n_patients:,} patients.")
        self.assertEqual([p[1:] for p in parts(f)], [("supported", n_samples), ("supported", n_patients)])
        f = self.run_claim(f"There are {met} metastatic and {normal} normal-tissue samples.")
        self.assertEqual([p[1:] for p in parts(f)], [("supported", met), ("supported", normal)])
        f = self.run_claim(f"Only {met} samples are metastases, and {normal + 1} are normal tissue.")
        self.assertEqual((f["verdict"], [p[1] for p in parts(f)]), ("contradicted", ["supported", "contradicted"]))
        self.assertIn(f"{normal} normal tissue samples", cv_text(f))


# ---------- item 3: ranges ----------
class TestRangesSynthetic(SyntheticCase):
    # 30 of 40 primary tumors have mutation data (75%); 40 primary tumors; 12 diagnostic slides; 2 metastases

    def test_percent_ranges(self):
        for text, verdict in (("Between 70% and 80% of primary tumors have mutation data.", "supported"),
                              ("From 70 to 80 percent of primary tumors have mutation data.", "supported"),
                              ("70-80% of primary tumors have mutation data.", "supported"),
                              ("Between 75% and 80% of primary tumors have mutation data.", "supported"),   # ends included
                              ("Between 40% and 50% of primary tumors have mutation data.", "contradicted"),
                              ("80 to 90 percent of primary tumors have mutation data.", "contradicted")):
            f = check(self.ctx, text, self)
            self.assertEqual(f["verdict"], verdict, text)
            self.assertIn("both ends included", f["evidence"]["calculation"])
            if verdict == "contradicted":
                self.assertEqual(cv_text(f), "75.0% (30 of 40)")

    def test_count_ranges(self):
        self.assertEqual(self.verdict("From 25 to 35 primary tumors have mutation data."), "supported")
        f = check(self.ctx, "Between 31 and 35 primary tumors have mutation data.", self)
        self.assertEqual((f["verdict"], f["correct_value"]["value"]), ("contradicted", 30))
        self.assertEqual(self.verdict("There are between 35 and 45 primary tumors."), "supported")
        self.assertEqual(self.verdict("There are between 10 and 15 diagnostic slides."), "supported")
        self.assertEqual(self.verdict("Between 3 and 5 samples are metastases."), "contradicted")

    def test_a_range_is_never_read_as_one_number_or_a_negative(self):
        q = E.parse_quantifier("From 25 to 35 primary tumors have mutation data.")
        self.assertEqual((q["comparator"], q["threshold"], q["high"]), ("range", 25, 35))
        q = E.parse_quantifier("70 - 80% of primary tumors have mutation data.")
        self.assertEqual((q["kind"], q["comparator"]), ("fraction", "range"))
        self.assertEqual(E.parse_quantifier("Between 120% and 130% of tumors have RNA data.")["kind"], "invalid")

    def test_near_an_end_asks_for_review_but_not_at_100_percent(self):
        f = check(self.ctx, "Between 60% and 76% of primary tumors have mutation data.", self)
        self.assertTrue(f["needs_human_review"])
        self.assertIn("upper end of the range", f["review_reason"])
        f = check(self.ctx, "Between 90% and 100% of primary tumors have survival data.", self)  # 100%: at the 100% end only
        self.assertEqual(f["verdict"], "supported")
        self.assertFalse(f["needs_human_review"])


class TestRangesReal(RealCase):
    def test_ranges_match_pandas(self):
        m = self.manifest[self.manifest.sample_id.str[13:15] == "01"]
        layers = ["has_survival", "has_mutation", "has_copy_number", "has_rna", "has_protein"]
        n = int(m[layers].all(axis=1).sum())
        share = n / len(m)
        f = self.run_claim("Between 40% and 50% of primary tumors have all five data layers.")
        self.assertEqual((f["verdict"], f["evidence"]["n_samples"], f["evidence"]["denominator"]),
                         ("supported" if 0.40 <= share <= 0.50 else "contradicted", n, len(m)))
        f = self.run_claim("Between 50% and 60% of primary tumors have all five data layers.")
        self.assertEqual((f["verdict"], cv_text(f)), ("contradicted", f"{share * 100:.1f}% ({n} of {len(m)})"))
        f = self.run_claim("From 500 to 600 primary tumors have all five data layers.")
        self.assertEqual((f["verdict"], f["evidence"]["n_samples"]), ("supported" if 500 <= n <= 600 else "contradicted", n))
        f = self.run_claim("From 600 to 700 primary tumors have all five data layers.")
        self.assertEqual((f["verdict"], f["correct_value"]["value"]), ("contradicted", n))


if __name__ == "__main__":
    unittest.main()
