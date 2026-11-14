"""evidence.examples: the samples behind a measured number (engine), and audit.json staying unchanged.

Synthetic tests use the tiny release from test_engine_claims (expected numbers known exactly) and always run.
The pandas cross-checks use the real release and skip when pandas or the data is missing."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_engine_claims import (DATA_DIR, METASTASIS, NO_REAL, PRIMARY, SyntheticCase, check, pd)  # noqa: E402
from src.engine import engine as E  # noqa: E402
from src.export import audit_json as A  # noqa: E402


def groups(f):
    return {g["kind"]: g for g in f["evidence"].get("examples", [])}


class TestExamplesSynthetic(SyntheticCase):
    def test_share_claim_lists_counted_and_fall_short(self):
        # 30 of the 40 primary tumors are in the mutation file
        f = check(self.ctx, "Mutation data is available for about 75 percent of primary tumors.", self)
        self.assertEqual(f["verdict"], "supported")
        g = groups(f)
        self.assertEqual((g["included"]["total"], g["fall_short"]["total"]), (30, 10))
        self.assertEqual(g["included"]["ids"], sorted(PRIMARY[:30]))
        self.assertEqual(g["fall_short"]["ids"], sorted(PRIMARY[30:]))
        self.assertEqual(g["included"]["total"], f["evidence"]["n_samples"])
        self.assertEqual(g["included"]["total"] + g["fall_short"]["total"], f["evidence"]["denominator"])

    def test_ids_come_only_from_the_loaded_files_and_are_sorted(self):
        f = check(self.ctx, "Mutation data is available for about 75 percent of primary tumors.", self)
        known = set(self.ctx.all_samples)
        for g in f["evidence"]["examples"]:
            self.assertEqual(g["ids"], sorted(g["ids"]))
            self.assertTrue(set(g["ids"]) <= known)

    def test_count_claim_lists_only_the_counted_samples(self):
        f = check(self.ctx, "There are 2 metastatic samples.", self)
        g = groups(f)
        self.assertEqual(list(g), ["included"])
        self.assertEqual((g["included"]["total"], g["included"]["ids"]), (2, sorted(METASTASIS)))

    def test_slide_count_lists_slide_barcodes(self):
        f = check(self.ctx, "There are 12 diagnostic slides.", self)
        g = groups(f)["included"]
        self.assertEqual((g["total"], len(g["ids"])), (12, 12))
        self.assertTrue(all("-X" in i for i in g["ids"]))

    def test_gene_share_lists_mutated_and_unmutated_profiled_tumors(self):
        f = check(self.ctx, "TP53 is mutated in about a third of tumors.", self)
        g = groups(f)
        self.assertEqual((g["included"]["total"], g["fall_short"]["total"]), (10, 20))
        self.assertEqual(g["included"]["ids"], sorted(PRIMARY[:10]))

    def test_total_stays_exact_when_ids_are_capped(self):
        old = E.EXAMPLES_MAX
        E.EXAMPLES_MAX = 5
        try:
            f = check(self.ctx, "Mutation data is available for about 75 percent of primary tumors.", self)
        finally:
            E.EXAMPLES_MAX = old
        g = groups(f)
        self.assertEqual((g["included"]["total"], len(g["included"]["ids"])), (30, 5))
        self.assertEqual((g["fall_short"]["total"], len(g["fall_short"]["ids"])), (10, 5))
        self.assertEqual(g["included"]["ids"], sorted(PRIMARY[:30])[:5])

    def test_blocked_and_insufficient_findings_get_none(self):
        blocked = check(self.ctx, "Drug X cures breast cancer.", self)
        self.assertEqual(blocked["verdict"], "insufficient_evidence")
        self.assertNotIn("examples", blocked["evidence"])
        vague = check(self.ctx, "The cohort is large enough for a subtype comparison.", self)
        self.assertEqual(vague["verdict"], "insufficient_evidence")
        self.assertNotIn("examples", vague["evidence"])

    def test_sentence_with_several_numbers_keeps_examples_on_each_part(self):
        f = check(self.ctx, "Of the 40 primary tumors, 30 have mutation data.", self)
        self.assertNotIn("examples", f["evidence"])
        parts = f["evidence"]["sub_checks"]
        self.assertEqual(len(parts), 2)
        self.assertTrue(all(p.get("examples") for p in parts))

    def test_audit_json_does_not_change(self):
        text = "Mutation data is available for about 75 percent of primary tumors."
        with_ex = {"is_mock": False, "schema_version": "draft-0",
                   "data_release": {"name": "TCGA-BRCA (frozen event release)", "checksum_verified": False, "checksum_status": "unknown"},
                   "report_title": "t.md", "findings": [check(self.ctx, text, self)]}
        self.assertIn("examples", with_ex["findings"][0]["evidence"])
        without = copy.deepcopy(with_ex)
        del without["findings"][0]["evidence"]["examples"]
        files = [{"file": "clinical.tsv", "sha256": "1" * 64}, {"file": "sample_manifest.csv", "sha256": "2" * 64}]
        self.assertEqual(A.build_audit(with_ex, files), A.build_audit(without, files))


@unittest.skipIf(DATA_DIR is None or pd is None, NO_REAL)
class TestExamplesRealData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = E.Context(DATA_DIR)
        cls.manifest = pd.read_csv(os.path.join(DATA_DIR, "sample_manifest.csv"))

    def test_primary_tumors_with_no_slide(self):
        f = check(self.ctx, "Every primary tumor has a pathology slide.", self)
        g = groups(f)
        prim = self.manifest[self.manifest.sample_type == "Primary Tumor"]
        no_slide = prim[prim.slides_for_sample == 0]
        self.assertEqual(g["fall_short"]["total"], len(no_slide))
        self.assertEqual(g["included"]["total"], len(prim) - len(no_slide))
        self.assertEqual(g["fall_short"]["ids"], sorted(no_slide.sample_id)[:E.EXAMPLES_MAX])

    def test_844_primary_tumors_have_a_subtype_call(self):
        f = check(self.ctx, "Luminal A accounts for about 49 percent of primary tumors with a PAM50 subtype.", self)
        g = groups(f)
        col = self.ctx.attrs["subtype"]["column"]
        clin = pd.read_csv(os.path.join(DATA_DIR, "raw", "clinical.tsv"), sep="\t", low_memory=False)
        primary = clin[clin.sampleID.str.endswith("-01")]
        self.assertEqual(int(primary[col].notna().sum()), 844)
        self.assertEqual(g["included"]["total"] + g["fall_short"]["total"], 844)
        self.assertEqual(f["evidence"]["denominator"], 844)


if __name__ == "__main__":
    unittest.main()
