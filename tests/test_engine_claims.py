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


def write_release(folder, mutation_rows=None, er=None, flat=False, manifests=True):
    """Write sample_manifest.csv, slide_manifest.csv and the data files; returns the folder.
    flat=True puts the data files directly in the folder (an envelope release) instead of raw/."""
    raw = folder if flat else os.path.join(folder, "raw")
    os.makedirs(raw, exist_ok=True)
    samples = PRIMARY + NORMAL + METASTASIS
    types = {"01": "Primary Tumor", "11": "Solid Tissue Normal", "06": "Metastatic"}
    if manifests:
        _write_manifests(folder, samples, types)
    _write_data(raw, samples, mutation_rows, er)
    return folder


def _write_manifests(folder, samples, types):
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


def _write_data(raw, samples, mutation_rows, er):
    er = er or {s: ("Negative" if i % 4 == 0 else "Positive") for i, s in enumerate(PRIMARY)}  # 10 negative, 30 positive
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


# ---------- item 4: gene-level mutation claims ----------
class TestGeneClaimsSynthetic(SyntheticCase):
    # 30 of 40 primary tumors are in the mutation file: PIK3CA 12, TP53 10, GATA3 4, CDH1 2, TTN 0

    def test_share_uses_profiled_primary_tumors_as_denominator(self):
        f = check(self.ctx, "TP53 is mutated in about a third of tumors.", self)
        ev = f["evidence"]
        self.assertEqual((f["verdict"], ev["n_samples"], ev["denominator"], ev["metric_name"]), ("supported", 10, 30, "share_tp53_mutated"))
        self.assertIn("Denominator: primary tumors with mutation data (30 of 40 primary tumors)", ev["calculation"])
        self.assertEqual(ev["source_files"][0], "mutation_gene_level.tsv.gz")
        self.assertEqual(f["cohort_trace"][-1], {"step": "TP53 mutated", "n_before": 30, "n_after": 10})

    def test_threshold_claims(self):
        self.assertEqual(self.verdict("GATA3 mutations occur in more than 10% of tumors."), "supported")  # 13.3%
        f = check(self.ctx, "GATA3 mutations occur in more than 20% of tumors.", self)
        self.assertEqual(f["verdict"], "contradicted")
        self.assertTrue(cv_text(f).startswith("13.3% (4 of 30 "))
        self.assertEqual(self.verdict("TTN mutations occur in fewer than 1 in 10 tumors."), "supported")  # in the file, never mutated
        self.assertEqual(self.verdict("At least 12 tumors carry PIK3CA mutations."), "supported")
        self.assertEqual(self.verdict("TP53 is mutated in between 30% and 40% of tumors."), "supported")

    def test_most_frequently_mutated_gene(self):
        self.assertEqual(self.verdict("PIK3CA is the most frequently mutated gene."), "supported")
        f = check(self.ctx, "TP53 is the most frequently mutated gene.", self)
        self.assertEqual(f["verdict"], "contradicted")
        self.assertIn("PIK3CA (12 of 30)", cv_text(f))
        self.assertIn("TP53 has 10 of 30 (rank 2)", cv_text(f))
        self.assertEqual(self.verdict("TP53 is the second most frequently mutated gene."), "supported")
        self.assertEqual(self.verdict("PIK3CA and TP53 are the two most frequently mutated genes."), "supported")
        self.assertEqual(self.verdict("PIK3CA and GATA3 are the two most frequently mutated genes."), "contradicted")
        self.assertIn("compared across all 5 genes", check(self.ctx, "PIK3CA is the most frequently mutated gene.", self)["evidence"]["calculation"])

    def test_gene_not_in_the_file_cannot_be_answered(self):
        for text in ("FAKEGENE1 is mutated in about 5% of tumors.", "XYZW mutations occur in 5% of tumors.",
                     "BRCA2 is the most frequently mutated gene."):
            f = check(self.ctx, text, self)
            self.assertEqual((f["verdict"], f["guardrail_flags"]), ("insufficient_evidence", ["data_cannot_answer"]), text)
            self.assertIn("not among the 5 genes", f["evidence"]["calculation"])

    def test_never_supported_from_mutation_coverage(self):
        for text in ("tp53 is mutated in about a third of tumors.", "The gene is mutated in most tumors.",
                     "Most tumors carry a driver mutation."):
            f = check(self.ctx, text, self)
            self.assertEqual(f["verdict"], "insufficient_evidence", text)
            self.assertFalse(f["evidence"]["metric_name"].startswith(("coverage_", "overlap_")), text)
        # a real coverage claim still works
        self.assertEqual(self.verdict("Mutation data is available for most primary tumors."), "supported")

    def test_not_a_gene(self):
        f = check(self.ctx, "Mutation calls can be matched to external databases such as COSMIC.", self)
        self.assertNotIn("gene", f["evidence"]["metric_name"])
        self.assertEqual(E.gene_mentions("Mutation data covers most HER2-positive tumors."), [])
        self.assertEqual(E.gene_mentions("TP53 and PIK3CA are mutated in about a third of tumors."), ["TP53", "PIK3CA"])

    def test_gene_list_gives_one_check_per_gene(self):
        f = check(self.ctx, "TP53 and GATA3 are mutated in about a third of tumors.", self)
        self.assertEqual(parts(f), [("TP53 is mutated in about a third of tumors.", "supported", 10),
                                    ("GATA3 is mutated in about a third of tumors.", "contradicted", 4)])
        self.assertEqual(f["verdict"], "contradicted")

    def test_subgroup_and_thin_denominator(self):
        f = check(self.ctx, "TP53 mutations occur in about a third of ER-negative tumors.", self)
        self.assertEqual((f["verdict"], f["evidence"]["denominator"]), ("insufficient_evidence", 8))  # 8 profiled ER-negative
        self.assertIn("too small", f["review_reason"])
        self.assertIn("clinical.tsv", f["evidence"]["source_files"])

    def test_missing_or_unreadable_mutation_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_release(tmp)  # no mutation file
            f = check(E.Context(tmp), "TP53 is mutated in about a third of tumors.", self)
            self.assertEqual((f["verdict"], f["guardrail_flags"]), ("insufficient_evidence", ["data_cannot_answer"]))
        with tempfile.TemporaryDirectory() as tmp:
            write_release(tmp, mutation_rows={"TP53": PRIMARY[:10]})
            path = os.path.join(tmp, "raw", "mutation_gene_level.tsv.gz")
            with gzip.open(path, "wt", encoding="utf-8") as fh:
                fh.write("sample\t" + "\t".join(PRIMARY[:3]) + "\nTP53\t0.5\t1\tMissense\n")
            f = check(E.Context(tmp), "TP53 is mutated in about a third of tumors.", self)
            self.assertEqual(f["guardrail_flags"], ["data_cannot_answer"])
            self.assertIn("values other than 0 and 1", f["evidence"]["calculation"])


class TestGeneClaimsReal(RealCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mut = pd.read_csv(os.path.join(DATA_DIR, "raw", "mutation_gene_level.tsv.gz"), sep="\t", index_col=0)
        primary = set(cls.manifest.sample_id[cls.manifest.sample_id.str[13:15] == "01"])
        cls.cols = [c for c in mut.columns if c[:15] in primary]
        cls.calls = mut[cls.cols]
        cls.per_gene = (cls.calls == 1).sum(axis=1).sort_values(ascending=False)

    def test_encoding_is_zero_or_one(self):
        self.assertTrue(set(pd.unique(self.calls.values.ravel())) <= {0, 1})

    def test_share_and_denominator_match_pandas(self):
        den = len(self.cols)
        for gene, text, test in (("TP53", "TP53 is mutated in about a third of tumors.", lambda v: abs(v - 1 / 3) <= 0.03),
                                 ("GATA3", "GATA3 mutations occur in more than 10% of tumors.", lambda v: v > 0.10)):
            n = int(self.per_gene[gene])
            f = self.run_claim(text)
            self.assertEqual((f["evidence"]["n_samples"], f["evidence"]["denominator"]), (n, den), gene)
            self.assertAlmostEqual(f["evidence"]["value"], round(n / den, 4))
            self.assertEqual(f["verdict"], "supported" if test(n / den) else "contradicted", gene)

    def test_most_frequently_mutated_matches_pandas(self):
        top, second = self.per_gene.index[0], self.per_gene.index[1]
        self.assertEqual(self.run_claim(f"{top} is the most frequently mutated gene.")["verdict"], "supported")
        f = self.run_claim(f"{second} is the most frequently mutated gene.")
        self.assertEqual(f["verdict"], "contradicted")
        self.assertIn(f"{top} ({int(self.per_gene[top])} of {len(self.cols)})", cv_text(f))
        self.assertEqual(self.run_claim("PIK3CA is the most frequently mutated gene.")["verdict"],
                         "supported" if top == "PIK3CA" else "contradicted")

    def test_subgroup_matches_pandas(self):
        col = next(n["column_used"] for n in self.ctx.attr_notes if n["attribute"] == "ER status")
        clin = pd.read_csv(os.path.join(DATA_DIR, "raw", "clinical.tsv"), sep="\t", low_memory=False).set_index("sampleID")
        neg = [c for c in self.cols if str(clin[col].get(c, "")).strip().lower().startswith("neg")]
        n = int((self.calls.loc["TP53", neg] == 1).sum())
        f = self.run_claim("TP53 mutations occur in about half of ER-negative tumors.")
        self.assertEqual((f["evidence"]["n_samples"], f["evidence"]["denominator"]), (n, len(neg)))
        self.assertEqual(f["verdict"], "supported" if abs(n / len(neg) - 0.5) <= 0.03 else "contradicted")

    def test_unknown_gene(self):
        self.assertNotIn("FAKEGENE1", self.calls.index)
        f = self.run_claim("FAKEGENE1 is mutated in about 5% of tumors.")
        self.assertEqual((f["verdict"], f["guardrail_flags"]), ("insufficient_evidence", ["data_cannot_answer"]))


# ---------- item 5: survival comparisons and treatment wording ----------
SURVIVAL_SENTENCES = ["ER-positive patients live longer than ER-negative patients.",
                      "ER-negative patients die sooner.",
                      "ER-positive tumors have better survival than ER-negative tumors.",
                      "ER-negative tumors have worse outcomes than ER-positive tumors.",
                      "Patients outlive expectations."]


class TestSurvivalComparisonsSynthetic(SyntheticCase):
    # primary tumors: ER-negative are rows 0, 4, 8, ... (10 samples) and every one of them died; ER-positive (30) none died

    def test_never_skipped(self):
        claims, skipped = E.extract_claims(" ".join(SURVIVAL_SENTENCES))
        self.assertEqual([c["text"] for c in claims], SURVIVAL_SENTENCES)
        self.assertEqual(skipped, [])

    def test_answered_insufficient_with_deaths_per_group(self):
        f = check(self.ctx, SURVIVAL_SENTENCES[0], self)
        self.assertEqual(f["verdict"], "insufficient_evidence")
        self.assertEqual(f["evidence"]["breakdown"], [{"group": "ER-positive", "n": 30, "events": 0},
                                                      {"group": "ER-negative", "n": 10, "events": 10}])
        self.assertIn(E.SURVIVAL_NOT_TESTED, f["evidence"]["calculation"])
        self.assertIn("30 with survival data, 0 OS deaths", f["evidence"]["calculation"])
        self.assertTrue(f["needs_human_review"])
        self.assertIn("not survival differences", f["review_reason"])
        self.assertEqual(f["guardrail_flags"], ["low_event_count"])  # both groups under 20 deaths
        self.assertEqual(f["missing_evidence"], E.SURVIVAL_MISSING)
        self.assertIn("survival.tsv", f["evidence"]["source_files"])

    def test_one_named_group_is_compared_with_the_rest(self):
        f = check(self.ctx, SURVIVAL_SENTENCES[1], self)
        self.assertEqual([b["group"] for b in f["evidence"]["breakdown"]], ["ER-negative", "other ER status"])
        self.assertEqual(f["verdict"], "insufficient_evidence")

    def test_no_groups_still_shows_the_deaths(self):
        f = check(self.ctx, SURVIVAL_SENTENCES[4], self)
        self.assertEqual((f["verdict"], f["evidence"]["n_samples"]), ("insufficient_evidence", 40))
        self.assertIn("10 OS deaths", f["evidence"]["calculation"])

    def test_blocked_wording_stays_blocked_and_says_what_it_needs(self):
        for text in SURVIVAL_SENTENCES[2:4]:
            f = check(self.ctx, text, self)
            self.assertEqual((f["verdict"], f["evidence"]["value"], f["evidence"]["n_samples"]), ("insufficient_evidence", None, 0), text)
            self.assertIn("clinical_claim_blocked", f["guardrail_flags"])
            self.assertEqual(f["missing_evidence"], E.SURVIVAL_MISSING_BLOCKED)
            self.assertNotIn("Treatment-response", f["missing_evidence"])

    def test_treatment_claim_names_the_real_columns(self):
        f = check(self.ctx, "Patients whose tumors had the highest ER-alpha protein responded best to hormone therapy.", self)
        self.assertEqual(f["verdict"], "insufficient_evidence")
        me = f["missing_evidence"]
        self.assertIn("yes/no treatment flags (radiation_therapy, targeted_molecular_therapy, additional_pharmaceutical_therapy)", me)
        self.assertIn("no hormone-therapy records and no treatment response", me)

    def test_treatment_wording_follows_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_release(tmp)
            path = os.path.join(tmp, "raw", "clinical.tsv")
            with open(path, "w", newline="", encoding="utf-8") as fh:
                fh.write("sampleID\tbreast_carcinoma_estrogen_receptor_status\thormone_therapy_type\n")
                for s in PRIMARY:
                    fh.write(f"{s}\tPositive\tTamoxifen\n")
            f = check(E.Context(tmp), "Patients who got hormone therapy responded best to treatment.", self)
            self.assertIn("clinical.tsv has no treatment columns", f["missing_evidence"])
            self.assertIn("hormone-therapy columns (hormone_therapy_type)", f["missing_evidence"])


class TestSurvivalComparisonsReal(RealCase):
    def test_groups_and_deaths_match_pandas(self):
        col = next(n["column_used"] for n in self.ctx.attr_notes if n["attribute"] == "ER status")
        clin = pd.read_csv(os.path.join(DATA_DIR, "raw", "clinical.tsv"), sep="\t", low_memory=False)
        clin = clin[clin.sampleID.str[13:15] == "01"].set_index("sampleID")
        surv = pd.read_csv(os.path.join(DATA_DIR, "raw", "survival.tsv"), sep="\t", index_col=0)
        status = clin[col].astype(str).str.strip().str.lower()
        expected = []
        for label, prefix in (("ER-positive", "pos"), ("ER-negative", "neg")):
            ids = status.index[status.str.startswith(prefix)]
            deaths = int((surv.reindex(ids)["OS"] == 1).sum())
            expected.append({"group": label, "n": len(ids), "events": deaths})
        f = self.run_claim("ER-positive patients live longer than ER-negative patients.")
        self.assertEqual(f["verdict"], "insufficient_evidence")
        self.assertEqual(f["evidence"]["breakdown"], expected)

    def test_treatment_columns_exist_and_no_hormone_column(self):
        header = pd.read_csv(os.path.join(DATA_DIR, "raw", "clinical.tsv"), sep="\t", nrows=0).columns
        for c in E.TREATMENT_FLAG_COLUMNS:
            self.assertIn(c, header)
        self.assertEqual([c for c in header if E.HORMONE_WORDS.search(c)], [])
        f = self.run_claim("Patients whose tumors had the highest ER-alpha protein responded best to hormone therapy.")
        self.assertIn("no hormone-therapy records and no treatment response", f["missing_evidence"])


# ---------- item 6: ratio claims ----------
class TestRatiosSynthetic(SyntheticCase):
    # primary tumors: 30 ER-positive, 10 ER-negative -> exactly 3 to 1

    def test_ratio_readings(self):
        for text, verdict in (("ER-positive tumors outnumber ER-negative tumors 3:1.", "supported"),
                              ("ER-positive tumors outnumber ER-negative tumors by about three to one.", "supported"),
                              ("There are three times as many ER-positive as ER-negative tumors.", "supported"),
                              ("There are twice as many ER-positive as ER-negative tumors.", "contradicted"),
                              ("ER-positive tumors outnumber ER-negative tumors by more than 3 to 1.", "contradicted"),  # 3.0 is not more
                              ("ER-positive tumors outnumber ER-negative tumors by at least 3 to 1.", "supported"),
                              ("There are half as many ER-negative as ER-positive tumors.", "contradicted")):          # 0.33, not 0.5
            f = check(self.ctx, text, self)
            self.assertEqual(f["verdict"], verdict, text)
            self.assertTrue(f["evidence"]["metric_name"].startswith("ratio_"), text)

    def test_numbers_and_correct_value(self):
        f = check(self.ctx, "There are twice as many ER-positive as ER-negative tumors.", self)
        ev = f["evidence"]
        self.assertEqual((ev["value"], ev["n_samples"], ev["denominator"]), (3.0, 30, 40))
        self.assertEqual(ev["groups"], [{"group": "ER-positive", "n": 30}, {"group": "ER-negative", "n": 10}])
        self.assertEqual(cv_text(f), "3.0 to 1 (ER-positive 30, ER-negative 10)")
        self.assertIn("fewer than 30 samples", f["review_reason"])  # ER-negative has 10

    def test_extracted_not_skipped(self):
        claims, skipped = E.extract_claims("There are twice as many ER-positive as ER-negative tumors.")
        self.assertEqual((len(claims), skipped), (1, []))

    def test_unreadable_groups_and_ranges(self):
        f = check(self.ctx, "Smokers outnumber nonsmokers two to one.", self)
        self.assertEqual(f["verdict"], "insufficient_evidence")
        self.assertIn("could not both be read", f["review_reason"])
        self.assertIsNone(E.parse_ratio("From 25 to 35 primary tumors have mutation data."))  # a range, not a ratio


class TestRatiosReal(RealCase):
    def test_ratios_match_pandas(self):
        clin = pd.read_csv(os.path.join(DATA_DIR, "raw", "clinical.tsv"), sep="\t", low_memory=False)
        clin = clin[clin.sampleID.str[13:15] == "01"]
        pam = clin.PAM50Call_RNAseq.value_counts()
        basal, her2 = int(pam["Basal"]), int(pam["Her2"])
        f = self.run_claim("Basal-like tumors outnumber HER2-enriched tumors by about two to one.")
        self.assertEqual((f["evidence"]["groups"][0]["n"], f["evidence"]["groups"][1]["n"]), (basal, her2))
        self.assertAlmostEqual(f["evidence"]["value"], round(basal / her2, 3))
        self.assertEqual(f["verdict"], "supported" if abs(basal / her2 - 2) <= 0.15 * 2 else "contradicted")
        col = next(n["column_used"] for n in self.ctx.attr_notes if n["attribute"] == "ER status")
        st = clin[col].astype(str).str.lower()
        pos, neg = int(st.str.startswith("pos").sum()), int(st.str.startswith("neg").sum())
        f = self.run_claim("There are twice as many ER-positive as ER-negative tumors.")
        self.assertEqual((f["verdict"], cv_text(f)), ("contradicted", f"{pos / neg:.1f} to 1 (ER-positive {pos}, ER-negative {neg})"))
        f = self.run_claim("ER-positive tumors outnumber ER-negative tumors roughly 3:1.")
        self.assertEqual(f["verdict"], "supported" if abs(pos / neg - 3) <= 0.45 else "contradicted")


# ---------- item 7: a release folder with the data files directly inside, no sources.csv ----------
MIXED = ("Of the 40 primary tumors in the release, 30 have mutation data. There are 2 metastatic samples. "
         "TP53 is mutated in about a third of tumors. There are 12 diagnostic slides. "
         "ER-positive tumors outnumber ER-negative tumors 3:1. Of the 50 primary tumors in the release, 30 have RNA data.")


class TestReleaseFolders(unittest.TestCase):
    def audit(self, folder):
        ctx = E.Context(folder)
        claims, skipped = E.extract_claims(MIXED)
        return ctx, E.audit(ctx, claims, "mixed", skipped)  # the guardrails post-check runs inside audit()

    def test_flat_folder_without_sources_or_manifests(self):
        from src.data import tcga_loader as L
        with tempfile.TemporaryDirectory() as tmp:
            write_release(tmp, mutation_rows=MUTATIONS, flat=True, manifests=False)
            self.assertEqual(os.path.abspath(L.raw_dir(tmp)), os.path.abspath(tmp))
            ctx, doc = self.audit(tmp)
            self.assertEqual(doc["data_release"]["checksum_status"], "unknown")
            self.assertEqual(len(ctx.all_samples), 47)  # read from the data files, since there is no manifest
            self.assertEqual([f["verdict"] for f in doc["findings"]][:3], ["supported", "supported", "supported"])
            self.assertEqual(doc["findings"][3]["guardrail_flags"], ["data_cannot_answer"])  # no slide list
            last = doc["findings"][5]  # 50 primary tumors is wrong, and RNA is not in this release
            self.assertEqual(last["verdict"], "contradicted")
            self.assertNotIn("data_cannot_answer", last["guardrail_flags"])
            self.assertIn("data_cannot_answer", last["evidence"]["sub_checks"][1]["guardrail_flags"])

    def test_raw_layout_still_preferred(self):
        from src.data import tcga_loader as L
        with tempfile.TemporaryDirectory() as tmp:
            write_release(tmp, mutation_rows=MUTATIONS)
            self.assertTrue(L.raw_dir(tmp).endswith("raw"))
            self.assertEqual(self.audit(tmp)[1]["findings"][3]["verdict"], "supported")  # slides from slide_manifest.csv

    def test_empty_and_broken_folders_never_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx, doc = self.audit(tmp)
            self.assertEqual((len(ctx.all_samples), doc["data_release"]["checksum_status"]), (0, "unknown"))
            self.assertEqual({f["verdict"] for f in doc["findings"]}, {"insufficient_evidence"})  # nothing is contradicted by nothing
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "clinical.tsv"), "w").close()
            with open(os.path.join(tmp, "survival.tsv"), "w") as fh:
                fh.write("garbage\n")
            with open(os.path.join(tmp, "protein_rppa.tsv.gz"), "wb") as fh:
                fh.write(b"not gzip")
            with gzip.open(os.path.join(tmp, "mutation_gene_level.tsv.gz"), "wt") as fh:
                fh.write("")
            with open(os.path.join(tmp, "sample_manifest.csv"), "w") as fh:
                fh.write("foo,bar\n1,2\n")
            ctx, doc = self.audit(tmp)
            self.assertIn("protein_rppa.tsv.gz", ctx.missing)
            self.assertEqual(len(doc["findings"]), 6)


ENVELOPE = os.path.join(ROOT, "..", "challenge-ref", "envelopes", "opened", "practice", "release")


@unittest.skipIf(not os.path.isdir(ENVELOPE), "practice envelope not opened (python envelopes/unseal.py practice ...)")
class TestPracticeEnvelopeRelease(unittest.TestCase):
    def test_envelope_release_loads(self):
        ctx = E.Context(ENVELOPE)
        self.assertEqual(ctx.checksums["status"], "unknown")
        self.assertEqual(ctx.missing, ["rna_hiseq.tsv.gz"])  # envelope releases carry no RNA
        self.assertGreater(len(ctx.population("01")), 1000)
        claims, skipped = E.extract_claims("TP53 is mutated in about a third of tumors. RNA data is available for most samples.")
        doc = E.audit(ctx, claims, "envelope", skipped)
        self.assertEqual([f["verdict"] for f in doc["findings"]], ["supported", "insufficient_evidence"])


# ---------- item 8: results close to the edge of the 'about' tolerance go to a person ----------
class TestReviewBandSynthetic(SyntheticCase):
    # 30 of 40 primary tumors (75%) have mutation data; tolerance 3 points, band 2 to 4.5 points

    def test_band_on_both_sides(self):
        for claimed, verdict, review in ((75, "supported", False), (74, "supported", False), (73, "supported", True),
                                         (72, "supported", True), (71, "contradicted", True), (70, "contradicted", False)):
            f = check(self.ctx, f"About {claimed}% of primary tumors have mutation data.", self)
            self.assertEqual((f["verdict"], f["needs_human_review"]), (verdict, review), claimed)
            if review:
                self.assertIn("near the 3-point tolerance", f["review_reason"])

    def test_band_for_ratios_and_counts(self):
        f = check(self.ctx, "ER-positive tumors outnumber ER-negative tumors by about 3.5 to 1.", self)  # 3.0 is 14% off
        self.assertEqual(f["verdict"], "supported")
        self.assertIn("near the 15 percent tolerance", f["review_reason"])
        f = check(self.ctx, "There are about 21 diagnostic slides.", self)  # 12: far outside, no band
        self.assertEqual((f["verdict"], f["needs_human_review"]), ("contradicted", False))


class TestReviewBandReal(RealCase):
    def test_her2_inside_the_band_goes_to_review(self):
        f = self.run_claim("About 15 percent of tumors are HER2-positive.")
        share = f["evidence"]["n_samples"] / f["evidence"]["denominator"]
        self.assertTrue(0.02 <= abs(share - 0.15) <= 0.045)
        self.assertEqual((f["verdict"], f["needs_human_review"]), ("supported" if abs(share - 0.15) <= 0.03 else "contradicted", True))

    def test_practice_brief_unchanged(self):
        brief = os.path.join(DATA_DIR, "..", "..", "products", "research-claim-auditor", "practice_brief.md")
        claims, skipped = E.extract_claims(open(brief, encoding="utf-8").read())
        doc = E.audit(self.ctx, claims, "practice_brief.md", skipped)
        self.assertEqual([(f["verdict"], f["needs_human_review"]) for f in doc["findings"]],
                         [("supported", False), ("contradicted", False), ("insufficient_evidence", True)])


if __name__ == "__main__":
    unittest.main()
