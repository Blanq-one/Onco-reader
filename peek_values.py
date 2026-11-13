r"""Prints aggregate value counts for a few clinical and survival columns.
No patient rows and no IDs are printed, only how many samples have each value.

Run from the onco-evidence folder:
    python peek_values.py ..\challenge-ref\data\tcga-brca
"""
import csv
import os
import sys
from collections import Counter

root = sys.argv[1] if len(sys.argv) > 1 else os.path.join("..", "challenge-ref", "data", "tcga-brca")
raw = os.path.join(root, "raw")


def peek(filename, wanted, top=12):
    path = os.path.join(raw, filename)
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        cols = {c: Counter() for c in wanted if c in reader.fieldnames}
        missing = [c for c in wanted if c not in reader.fieldnames]
        n = 0
        for row in reader:
            n += 1
            for c in cols:
                cols[c][(row[c] or "").strip() or "<blank>"] += 1
    print("=" * 60)
    print(f"{filename}: {n} rows")
    for c, counter in cols.items():
        print(f"\n  {c}  ({len(counter)} distinct values)")
        for value, count in counter.most_common(top):
            print(f"    {value[:40]:<42}{count}")
    if missing:
        print("\n  columns not found:", missing)


peek("clinical.tsv", [
    "PAM50Call_RNAseqPAM50_mRNA_nature2012",
    "ER_Status_nature2012",
    "PR_Status_nature2012",
    "HER2_Final_Status_nature2012",
    "AJCC_Stage_nature2012",
    "pathologic_stage",
    "histological_type",
    "sample_type",
    "gender",
    "vital_status",
])
peek("survival.tsv", ["OS", "DSS", "DFI", "PFI"], top=5)
