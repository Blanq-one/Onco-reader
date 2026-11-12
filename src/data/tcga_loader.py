r"""TCGA-BRCA loader and cohort attrition (standard library only).

What it does, in plain English:
  1. Reads which samples appear in each data file (straight from the raw files).
  2. Starts from the primary tumor samples and applies one layer at a time,
     counting how many samples survive each step (the cohort attrition).
  3. Cross-checks those counts against the organizers' sample_manifest.csv,
     so any disagreement is surfaced instead of hidden.
  4. Checks the raw files against the frozen checksums in sources.csv.

Run it (from the folder that holds challenge-ref):
    python tcga_loader.py --data-dir challenge-ref\data\tcga-brca --plot
Or set TCGA_DATA_DIR once and drop --data-dir.

Outputs: a printed table, cohort_attrition.json, and (with --plot) a PNG.
Raw data is only ever READ. Nothing here copies or commits it.
"""
import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import sys
from collections import OrderedDict

DEFAULT_DIR = os.environ.get("TCGA_DATA_DIR", os.path.join("challenge-ref", "data", "tcga-brca"))

# layer name -> raw file, how sample IDs are stored, and the manifest flag column
LAYERS = OrderedDict([
    ("clinical", {"file": "clinical.tsv", "kind": "rows", "flag": "in_clinical"}),
    ("survival", {"file": "survival.tsv", "kind": "rows", "flag": "has_survival"}),
    ("mutation", {"file": "mutation_gene_level.tsv.gz", "kind": "columns", "flag": "has_mutation"}),
    ("copy_number", {"file": "copy_number_gistic.tsv.gz", "kind": "columns", "flag": "has_copy_number"}),
    ("rna", {"file": "rna_hiseq.tsv.gz", "kind": "columns", "flag": "has_rna"}),
    ("protein", {"file": "protein_rppa.tsv.gz", "kind": "columns", "flag": "has_protein"}),
])
FIVE_LAYERS = ["survival", "mutation", "copy_number", "rna", "protein"]
DEFAULT_ORDER = ["clinical"] + FIVE_LAYERS

# Numbers quoted in the data README ("Coverage, checked Nov 10, 2026"), used only as a sanity check.
README_REFERENCE = {"samples": 1247, "patients": 1101, "primary_tumors": 1101, "primary_with_all_five_layers": 535}

TRUE_WORDS = {"1", "true", "t", "yes", "y"}
HEX64 = re.compile(r"\b[0-9a-fA-F]{64}\b")


# ---------- small helpers ----------
def _open(path):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="")
    return open(path, "r", encoding="utf-8", errors="replace", newline="")


def sample_code(sample_id):
    return sample_id[13:15] if len(sample_id) >= 15 else ""


def patient_of(sample_id):
    return sample_id[:12]


def is_primary(sample_id):
    return sample_code(sample_id) == "01"


def truthy(value):
    return str(value).strip().lower() in TRUE_WORDS


class LayerIds:
    """The IDs a data file contains, and at what level (sample or patient)."""

    def __init__(self, ids, level):
        self.ids = set(ids)
        self.level = level  # "sample" (15 chars) or "patient" (12 chars)

    def contains(self, sample_id):
        if self.level == "sample":
            return sample_id in self.ids
        return patient_of(sample_id) in self.ids

    def __len__(self):
        return len(self.ids)


# ---------- reading raw files ----------
def ids_from_columns(path):
    with _open(path) as fh:
        header = next(csv.reader(fh, delimiter="\t"))
    ids = [h.strip()[:15] for h in header[1:] if h.strip().startswith("TCGA-")]
    return LayerIds(ids, "sample")


def ids_from_rows(path):
    """Find the column that holds TCGA barcodes and read it (no assumptions about its name)."""
    with _open(path) as fh:
        reader = csv.reader(fh, delimiter="\t")
        header = next(reader)
        rows = []
        for i, row in enumerate(reader):
            rows.append(row)
            if i >= 199:
                break
        best, best_score = None, 0
        for idx in range(len(header)):
            vals = [r[idx] for r in rows if idx < len(r)]
            tcga = [v for v in vals if v.startswith("TCGA-")]
            long_ones = [v for v in tcga if len(v) >= 15]
            score = len(long_ones) * 2 + len(tcga)  # prefer sample-level barcodes
            if score > best_score:
                best, best_score = idx, score
        if best is None:
            raise ValueError(f"no barcode column found in {path}")
        fh.seek(0)
        reader = csv.reader(fh, delimiter="\t")
        next(reader)
        values = [r[best].strip() for r in reader if best < len(r) and r[best].startswith("TCGA-")]
    sample_level = sum(1 for v in values if len(v) >= 15) >= len(values) / 2
    if sample_level:
        return LayerIds([v[:15] for v in values], "sample")
    return LayerIds([v[:12] for v in values], "patient")


def load_layers(data_dir):
    raw = os.path.join(data_dir, "raw")
    found, missing = OrderedDict(), []
    for name, spec in LAYERS.items():
        path = os.path.join(raw, spec["file"])
        if not os.path.exists(path):
            missing.append(spec["file"])
            continue
        reader = ids_from_columns if spec["kind"] == "columns" else ids_from_rows
        found[name] = reader(path)
    return found, missing


def load_manifest(data_dir):
    path = os.path.join(data_dir, "sample_manifest.csv")
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------- attrition ----------
def starting_population(manifest, layers):
    """Primary tumor samples. Uses the manifest if present, else the union of sample-level files."""
    if manifest:
        ids = [r["sample_id"] for r in manifest]
        source = "sample_manifest.csv"
    else:
        ids = sorted(set().union(*[l.ids for l in layers.values() if l.level == "sample"]))
        source = "union of raw files"
    return sorted(i for i in ids if is_primary(i)), source


def attrition_from_layers(population, layers, order):
    trace, current = [], list(population)
    trace.append({"step": "primary tumor samples", "n_before": len(current), "n_after": len(current)})
    for name in order:
        if name not in layers:
            trace.append({"step": f"{name} (file missing, skipped)", "n_before": len(current), "n_after": len(current)})
            continue
        before = len(current)
        current = [s for s in current if layers[name].contains(s)]
        trace.append({"step": f"has {name}", "n_before": before, "n_after": len(current)})
    return trace, current


def attrition_from_manifest(population, manifest, order):
    by_id = {r["sample_id"]: r for r in manifest}
    current = list(population)
    counts = [len(current)]
    for name in order:
        flag = LAYERS[name]["flag"]
        current = [s for s in current if flag in by_id[s] and truthy(by_id[s][flag])]
        counts.append(len(current))
    return counts


def crosscheck(manifest, layers):
    """Compare each layer's raw-file IDs with the manifest flags, across ALL manifest samples."""
    report = OrderedDict()
    manifest_ids = {r["sample_id"] for r in manifest}
    for name, spec in LAYERS.items():
        if name not in layers:
            continue
        flagged = {r["sample_id"] for r in manifest if spec["flag"] in r and truthy(r[spec["flag"]])}
        raw = {s for s in manifest_ids if layers[name].contains(s)}
        raw_outside = 0
        if layers[name].level == "sample":
            raw_outside = len(layers[name].ids - manifest_ids)
        report[name] = {
            "manifest_flagged": len(flagged),
            "raw_file_matches": len(raw),
            "only_in_raw": len(raw - flagged),
            "only_in_manifest": len(flagged - raw),
            "raw_ids_not_in_manifest": raw_outside,
            "agrees": raw == flagged and raw_outside == 0,
        }
    return report


# ---------- checksums ----------
def _sha256_file(path, decompress=False):
    h = hashlib.sha256()
    opener = gzip.open if decompress else open
    with opener(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_checksums(data_dir):
    """Match each raw file's SHA-256 against any hash listed in sources.csv.

    Returns status 'verified' (all files matched), 'mismatch' (a file matched nothing)
    or 'unknown' (sources.csv not found). We try both the file bytes and, for .gz files,
    the decompressed bytes, since sources.csv does not say which one it hashes.
    """
    src = os.path.join(data_dir, "sources.csv")
    if not os.path.exists(src):
        return {"status": "unknown", "detail": "sources.csv not found", "files": {}}
    with open(src, encoding="utf-8") as fh:
        known = {h.lower() for h in HEX64.findall(fh.read())}
    files, bad = OrderedDict(), []
    for spec in LAYERS.values():
        path = os.path.join(data_dir, "raw", spec["file"])
        if not os.path.exists(path):
            continue
        digests = [_sha256_file(path)]
        if path.endswith(".gz") and digests[0] not in known:
            digests.append(_sha256_file(path, decompress=True))
        ok = any(d in known for d in digests)
        files[spec["file"]] = "match" if ok else "NO MATCH"
        if not ok:
            bad.append(spec["file"])
    status = "verified" if files and not bad else "mismatch"
    return {"status": status, "detail": "all files matched" if not bad else f"no match for: {bad}", "files": files}


# ---------- report ----------
def build_report(data_dir, order, skip_hash=False):
    layers, missing = load_layers(data_dir)
    manifest = load_manifest(data_dir)
    population, pop_source = starting_population(manifest, layers)
    trace, final = attrition_from_layers(population, layers, order)
    five_trace, five_final = attrition_from_layers(population, layers, [l for l in FIVE_LAYERS])
    report = OrderedDict()
    report["is_mock"] = False
    report["data_release"] = {"name": "TCGA-BRCA (frozen event release)"}
    report["population"] = {"definition": "primary tumor samples (barcode type 01), sample level",
                            "source": pop_source, "n": len(population)}
    report["cohort_trace"] = trace
    report["final"] = {"samples": len(final), "patients": len({patient_of(s) for s in final})}
    report["missing_files"] = missing
    report["layer_id_levels"] = {k: v.level for k, v in layers.items()}
    if manifest:
        report["manifest_check"] = {
            "manifest_counts_by_step": attrition_from_manifest(population, manifest, [o for o in order]),
            "raw_counts_by_step": [t["n_after"] for t in trace],
            "per_layer": crosscheck(manifest, layers),
        }
        report["manifest_check"]["steps_agree"] = (
            report["manifest_check"]["manifest_counts_by_step"] == report["manifest_check"]["raw_counts_by_step"]
        ) if not missing else None
    ref = README_REFERENCE
    report["readme_reference"] = {
        "readme_primary_tumors": ref["primary_tumors"], "ours": len(population),
        "readme_with_all_five_layers": ref["primary_with_all_five_layers"], "ours_five_layers": len(five_final),
        "matches": len(population) == ref["primary_tumors"] and len(five_final) == ref["primary_with_all_five_layers"],
    }
    if not skip_hash:
        report["checksums"] = verify_checksums(data_dir)
        report["data_release"]["checksum_status"] = report["checksums"]["status"]
    return report


def print_report(rep):
    print()
    print(f"Population: {rep['population']['definition']} (from {rep['population']['source']})")
    print()
    print(f"{'Step':<34}{'before':>8}{'after':>8}{'dropped':>9}")
    print("-" * 59)
    for t in rep["cohort_trace"]:
        print(f"{t['step']:<34}{t['n_before']:>8}{t['n_after']:>8}{t['n_before'] - t['n_after']:>9}")
    print("-" * 59)
    print(f"Final cohort: {rep['final']['samples']} samples, {rep['final']['patients']} patients")
    if rep["missing_files"]:
        print("MISSING FILES:", rep["missing_files"])
    mc = rep.get("manifest_check")
    if mc:
        print()
        print("Manifest cross-check (raw files vs sample_manifest.csv):")
        for name, row in mc["per_layer"].items():
            flag = "agrees" if row["agrees"] else "DIFFERS"
            print(f"  {name:<12} {flag:<8} manifest={row['manifest_flagged']} raw={row['raw_file_matches']} "
                  f"only_raw={row['only_in_raw']} only_manifest={row['only_in_manifest']} "
                  f"raw_not_in_manifest={row['raw_ids_not_in_manifest']}")
        print(f"  step-by-step counts agree: {mc['steps_agree']}")
    r = rep["readme_reference"]
    print()
    print(f"README sanity check: primary tumors {r['ours']} vs {r['readme_primary_tumors']}, "
          f"all five layers {r['ours_five_layers']} vs {r['readme_with_all_five_layers']} -> "
          f"{'matches' if r['matches'] else 'DOES NOT MATCH'}")
    if "checksums" in rep:
        c = rep["checksums"]
        print(f"Checksums: {c['status']} ({c['detail']})")
    print()


def plot_funnel(rep, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    steps = rep["cohort_trace"]
    labels = [s["step"] for s in steps][::-1]
    values = [s["n_after"] for s in steps][::-1]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.barh(labels, values, color="#3b6fb6")
    for bar, v in zip(bars, values):
        ax.text(v + max(values) * 0.01, bar.get_y() + bar.get_height() / 2, str(v), va="center")
    ax.set_xlabel("samples remaining")
    ax.set_title("TCGA-BRCA: primary tumors surviving each join")
    ax.set_xlim(0, max(values) * 1.12)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description="TCGA-BRCA cohort attrition")
    ap.add_argument("--data-dir", default=DEFAULT_DIR, help="folder with raw/, sample_manifest.csv, sources.csv")
    ap.add_argument("--order", default=",".join(DEFAULT_ORDER), help="comma-separated layer order")
    ap.add_argument("--out", default="cohort_attrition.json")
    ap.add_argument("--plot", action="store_true", help="also write cohort_attrition.png")
    ap.add_argument("--skip-hash", action="store_true", help="skip the checksum check")
    args = ap.parse_args(argv)
    order = [o.strip() for o in args.order.split(",") if o.strip()]
    bad = [o for o in order if o not in LAYERS]
    if bad:
        sys.exit(f"unknown layer(s): {bad}. choose from {list(LAYERS)}")
    if not os.path.isdir(args.data_dir):
        sys.exit(f"data folder not found: {os.path.abspath(args.data_dir)}")
    rep = build_report(args.data_dir, order, skip_hash=args.skip_hash)
    print_report(rep)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=2)
    print(f"Saved {args.out}")
    if args.plot:
        png = os.path.splitext(args.out)[0] + ".png"
        plot_funnel(rep, png)
        print(f"Saved {png}")


if __name__ == "__main__":
    main()
