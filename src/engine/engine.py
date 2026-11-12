r"""Evidence engine v1: turn report claims into checked findings (standard library only).

Plain English: for each claim in a report it (1) runs the guardrail pre-check,
(2) reads the claim as a small template, (3) computes the real numbers from the
TCGA-BRCA files through tcga_loader, and (4) writes a finding in the contract
shape, with the evidence, a limitation, next actions, and a robustness check.

Templates it understands (v1):
  coverage   "RNA data is available for most samples"          -> share with that layer
  overlap    "Copy number and RNA can be joined for most ..."   -> share with ALL layers named
  count      "Fewer than 100 samples have both survival and mutation records"
  condition  "RNA data is available for nearly all samples that have clinical records"
Layers: clinical, survival, mutation, copy number, RNA, protein, slides.
Anything else is answered honestly as "insufficient evidence".

Run (from the repo root):
    python src/engine/engine.py --data-dir ..\challenge-ref\data\tcga-brca --report contract\mock_report.md --out out\findings.json
"""
import argparse
import json
import os
import re
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "contract"))

from src.data import tcga_loader as L  # noqa: E402

try:  # D's module, once it exists
    from src.guardrails import check_claim as _check_claim  # type: ignore
    GUARDRAILS_SOURCE = "src/guardrails"
except Exception:  # pragma: no cover
    _check_claim = None
    GUARDRAILS_SOURCE = "built-in fallback (temporary, replace with D's module)"

try:
    import validate_findings as VF  # contract/validate_findings.py
except Exception:  # pragma: no cover
    VF = None

# Every interpretation choice lives here so it can be shown and changed in one place.
CFG = {
    "most_threshold": 0.5,       # "most" / "majority" means more than 50 percent
    "nearly_all": 0.95,          # "nearly all" / "almost all" means at least 95 percent
    "about_tolerance": 0.05,     # "about N percent" means within 5 points of N
    "borderline_margin": 0.02,   # within 2 points of the threshold -> ask a person to review
    "min_population": 30,        # fewer samples than this is too thin to judge
}

LAYER_WORDS = OrderedDict([
    ("copy_number", [r"copy[- ]?number", r"\bcnv\b", r"gistic"]),
    ("mutation", [r"mutation", r"mutated", r"\bvariants?\b"]),
    ("protein", [r"protein", r"rppa"]),
    ("survival", [r"survival"]),
    ("rna", [r"\brna\b", r"rna-?seq", r"gene expression", r"expression data", r"transcript"]),
    ("clinical", [r"clinical"]),
    ("slides", [r"\bslides?\b", r"pathology", r"histolog"]),
])
LAYER_LABEL = {"copy_number": "copy number", "mutation": "mutation", "protein": "protein", "survival": "survival",
               "rna": "RNA", "clinical": "clinical", "slides": "pathology slides"}
LAYER_SOURCE = {name: spec["file"] for name, spec in L.LAYERS.items()}
LAYER_SOURCE["slides"] = "sample_manifest.csv (slides_for_sample)"

OTHER_DATASET_WORDS = r"\b(lung|colon|colorectal|kidney|prostate|ovarian|liver|brain|glioma|melanoma)\b"
POPULATION_WORDS = [("normal", "11", "normal tissue samples"), ("metasta", "06", "metastasis samples")]

BLOCK_ACTIONS = {
    "clinical_claim_blocked": ["Rewrite the claim as a data-availability question, such as how many samples have treatment records.",
                               "Send treatment-effect questions to qualified clinical researchers."],
    "individual_level_request_blocked": ["Rewrite the claim as a cohort-level question."],
    "reidentification_blocked": ["Remove any attempt to identify people or link to outside records."],
    "phi_like_input": ["Remove names, dates of birth, record numbers and contact details from the report."],
    "prompt_injection_suspected": ["Remove instructions aimed at the system from the report text."],
    "invalid_input": ["Provide a non-empty claim written as a sentence."],
}


# ---------- context ----------
class Context:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.layers, self.missing = L.load_layers(data_dir)
        self.manifest = L.load_manifest(data_dir)
        if self.manifest:
            ids = [r["sample_id"] for r in self.manifest]
            slide_ids = []
            for r in self.manifest:
                try:
                    if float(r.get("slides_for_sample", 0) or 0) > 0:
                        slide_ids.append(r["sample_id"])
                except ValueError:
                    pass
            self.layers["slides"] = L.LayerIds(slide_ids, "sample")
        else:
            ids = sorted(set().union(*[l.ids for l in self.layers.values() if l.level == "sample"]))
        self.all_samples = sorted(ids)
        self.by_code = {}
        for s in self.all_samples:
            self.by_code.setdefault(L.sample_code(s), []).append(s)
        self.checksums = L.verify_checksums(data_dir)

    def population(self, code="01"):
        return self.by_code.get(code, [])


# ---------- reading claims ----------
def split_claims(text):
    items = []
    for line in text.splitlines():
        m = re.match(r"^\s*(?:\d+[.)]|[-*\u2022])\s+(.*\S)\s*$", line)
        if m:
            items.append(m.group(1))
    if items:
        return items
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if s.strip() and not s.lstrip().startswith("#")]


def find_layers(text):
    low = text.lower()
    found = []
    for name, pats in LAYER_WORDS.items():
        pos = [m.start() for p in pats for m in re.finditer(p, low)]
        if pos:
            found.append((min(pos), name))
    return [n for _, n in sorted(found)]


NUM = r"(\d[\d,]*(?:\.\d+)?)"


def parse_quantifier(text):
    """Return dict(kind, comparator, threshold, reading) or None. Also returns an 'invalid' marker."""
    low = text.lower().replace("\u2019", "'")
    m = re.search(r"\b(fewer than|less than|under|below|more than|over|above|at least|at most|up to|exactly)\s+" + NUM +
                  r"\s+(samples?|patients?|tumou?rs?|cases?)\b", low)
    if m:
        word, n = m.group(1), float(m.group(2).replace(",", ""))
        comp = {"fewer than": "<", "less than": "<", "under": "<", "below": "<", "more than": ">", "over": ">",
                "above": ">", "at least": ">=", "at most": "<=", "up to": "<=", "exactly": "=="}[word]
        return {"kind": "count", "comparator": comp, "threshold": n, "reading": f"'{word} {int(n)}' samples"}
    m = re.search(r"\b(fewer than|less than|under|below|more than|over|above|at least|at most|about|around|approximately|"
                  r"roughly|nearly|almost)?\s*" + NUM + r"\s*(?:%|percent|per cent)", low)
    if m:
        word, pct = (m.group(1) or "about"), float(m.group(2).replace(",", ""))
        if pct > 100 or pct < 0:
            return {"kind": "invalid", "reading": f"{pct:g} percent is outside 0 to 100"}
        comp = {"fewer than": "<", "less than": "<", "under": "<", "below": "<", "more than": ">", "over": ">",
                "above": ">", "at least": ">=", "at most": "<=", "about": "~", "around": "~", "approximately": "~",
                "roughly": "~", "nearly": "~", "almost": "~"}[word]
        return {"kind": "fraction", "comparator": comp, "threshold": pct / 100.0,
                "reading": f"'{word} {pct:g} percent'" + (f" (within {int(CFG['about_tolerance'] * 100)} points)" if comp == "~" else "")}
    for pat, comp, thr, reading in [
        (r"\b(nearly|almost) all\b", ">=", CFG["nearly_all"], f"'nearly all' means at least {int(CFG['nearly_all'] * 100)} percent"),
        (r"\b(less|fewer) than half\b", "<", 0.5, "'less than half' means under 50 percent"),
        (r"\b(more than|over) half\b", ">", 0.5, "'more than half' means over 50 percent"),
        (r"\b(every|each|all|entire)\b", "==", 1.0, "'all/every' means 100 percent"),
        (r"\b(most|majority)\b", ">", CFG["most_threshold"], f"'most' means more than {int(CFG['most_threshold'] * 100)} percent"),
    ]:
        if re.search(pat, low):
            return {"kind": "fraction", "comparator": comp, "threshold": thr, "reading": reading}
    return None


def parse_claim(text):
    low = text.lower()
    q = parse_quantifier(text)
    if q and q["kind"] == "invalid":
        return {"type": "invalid", "reading": q["reading"]}
    target_text, cond_text = text, ""
    m = re.search(r"\b(?:samples|tumou?rs|patients|cases)\s+(?:that\s+|which\s+)?(?:have|with|having)\s+(.+)$", text, re.I)
    if m:
        left = text[:m.start()]
        if find_layers(left):  # a layer before the clause means the clause is a condition
            target_text, cond_text = left, m.group(1)
    targets = find_layers(target_text)
    conds = [c for c in find_layers(cond_text) if c not in targets]
    code, pop_label = "01", "primary tumor samples"
    for word, c, label in POPULATION_WORDS:
        if word in low:
            code, pop_label = c, label
    if not targets:
        outside = re.search(OTHER_DATASET_WORDS, low)
        return {"type": "unanswerable", "outside": bool(outside),
                "reason": ("it refers to a different cancer type or dataset than the loaded TCGA-BRCA release" if outside
                           else "it needs a field that is not among the loaded layers")}
    return {"type": "measure", "targets": targets, "conditions": conds, "quantifier": q, "pop_code": code, "pop_label": pop_label}


# ---------- computing ----------
def compute(ctx, parsed, population_ids, pop_label):
    steps, current = [], list(population_ids)
    steps.append({"step": pop_label, "n_before": len(current), "n_after": len(current)})
    for layer in parsed["conditions"] + parsed["targets"]:
        before = len(current)
        current = [s for s in current if ctx.layers[layer].contains(s)]
        tag = "has" if layer in parsed["targets"] else "has (condition)"
        steps.append({"step": f"{tag} {LAYER_LABEL[layer]}", "n_before": before, "n_after": len(current)})
    cond_n = steps[len(parsed["conditions"])]["n_after"]  # denominator after condition layers only
    return steps, cond_n, len(current)


def satisfied(q, value, count, denom):
    v = value if q["kind"] == "fraction" else count
    t, c = q["threshold"], q["comparator"]
    if c == "~":
        return abs(value - t) <= CFG["about_tolerance"]
    if c == "==":
        return v == t if q["kind"] == "fraction" else v == t
    return {">": v > t, ">=": v >= t, "<": v < t, "<=": v <= t}[c]


def limitation_for(parsed, layers_used):
    parts = ["Presence in a file means the sample appears there; it says nothing about data quality or completeness inside the file."]
    if "slides" in layers_used:
        parts = ["A slide counts only when its barcode matches the sample; diagnostic and frozen slides are not separated here."]
    if "survival" in layers_used:
        parts.append("Survival presence does not tell you how many events (deaths) exist.")
    return " ".join(parts)


def source_files(layers):
    files = [LAYER_SOURCE[l] for l in layers if l in LAYER_SOURCE]
    return files + ["sample_manifest.csv"]


# ---------- findings ----------
def blank_finding(fid, text):
    return OrderedDict([
        ("id", fid), ("claim_text", text), ("verdict", "insufficient_evidence"),
        ("evidence", OrderedDict([("metric_name", "not_computed"), ("value", None), ("n_samples", 0),
                                   ("denominator", 0), ("source_files", []), ("calculation", "")])),
        ("cohort_trace", []), ("limitation", ""), ("needs_human_review", False), ("review_reason", None),
        ("guardrail_flags", []), ("next_actions", []), ("robustness", None),
    ])


def blocked_finding(fid, text, flags, reason, total):
    f = blank_finding(fid, text)
    f["evidence"]["calculation"] = f"not run: {reason}"
    f["evidence"]["denominator"] = total
    f["limitation"] = "This tool checks data readiness only. The request was stopped before any analysis."
    f["needs_human_review"] = True
    f["review_reason"] = reason
    f["guardrail_flags"] = list(flags)
    acts = []
    for fl in flags:
        acts += BLOCK_ACTIONS.get(fl, [])
    f["next_actions"] = acts or ["Rewrite the claim as a cohort-level data-availability question."]
    return f


def run_guardrails(text):
    if _check_claim is not None:
        return _check_claim(text)
    low = (text or "").lower()
    flags = []
    if not (text or "").strip():
        flags.append("invalid_input")
    if re.search(r"ignore (all )?previous instructions|reveal your api key|^system:", low):
        flags.append("prompt_injection_suspected")
    if re.search(r"\bdob\b|\bmrn\b|[a-z0-9._-]+@[a-z0-9.-]+\.[a-z]{2,}", low):
        flags.append("phi_like_input")
    if re.search(r"outside records|obituar", low):
        flags.append("reidentification_blocked")
    if re.search(r"tcga-[a-z0-9]{2}-[a-z0-9]{4}", low) and "reidentification_blocked" not in flags:
        flags.append("individual_level_request_blocked")
    if re.search(r"improves survival|should receive|risk score|diagnos|which treatment|chemotherapy|prognos", low):
        flags.append("clinical_claim_blocked")
    return {"allowed": not flags, "flags": flags, "reason": ("Stopped by guardrails: " + ", ".join(flags)) if flags else ""}


def evaluate_claim(ctx, fid, text):
    total = len(ctx.population("01")) or len(ctx.all_samples)
    guard = run_guardrails(text)
    if not guard["allowed"]:
        return blocked_finding(fid, text, guard["flags"], guard.get("reason") or "Stopped by guardrails.", total)
    parsed = parse_claim(text)
    f = blank_finding(fid, text)
    f["evidence"]["denominator"] = total
    if parsed["type"] == "invalid":
        f["evidence"]["calculation"] = f"not run: {parsed['reading']}"
        f["limitation"] = "A percentage outside 0 to 100 is impossible, so the claim cannot be checked as written."
        f["guardrail_flags"] = ["invalid_input"]
        f["needs_human_review"], f["review_reason"] = True, "The claim contains an impossible percentage."
        f["next_actions"] = BLOCK_ACTIONS["invalid_input"] + ["Rewrite the claim with a percentage between 0 and 100."]
        return f
    if parsed["type"] == "unanswerable":
        f["evidence"]["calculation"] = f"not run: {parsed['reason']}"
        f["limitation"] = f"The data cannot answer this: {parsed['reason']}."
        f["guardrail_flags"] = ["data_cannot_answer"]
        f["next_actions"] = ["Rephrase the claim around the available layers (clinical, survival, mutation, copy number, RNA, protein, slides).",
                             "Check whether the needed field exists in another data file."]
        return f
    missing = [l for l in parsed["conditions"] + parsed["targets"] if l not in ctx.layers]
    if missing:
        f["evidence"]["calculation"] = f"not run: layer file(s) not loaded for {missing}"
        f["limitation"] = f"The data cannot answer this: {missing} not loaded."
        f["guardrail_flags"] = ["data_cannot_answer"]
        f["next_actions"] = ["Re-run the data download and check that every layer file loads."]
        return f
    pop_ids = ctx.population(parsed["pop_code"])
    steps, cond_n, hit_n = compute(ctx, parsed, pop_ids, parsed["pop_label"])
    layers_used = parsed["conditions"] + parsed["targets"]
    value = hit_n / cond_n if cond_n else None
    q = parsed["quantifier"]
    is_count = bool(q and q["kind"] == "count")
    metric = ("count_" if is_count else "overlap_" if len(parsed["targets"]) > 1 else "coverage_") + "_".join(parsed["targets"])
    tlabel = " and ".join(LAYER_LABEL[t] for t in parsed["targets"])
    denom_text = parsed["pop_label"] + (" that have " + " and ".join(LAYER_LABEL[c] for c in parsed["conditions"]) if parsed["conditions"] else "")
    calc = f"samples with {tlabel} among {denom_text}: {hit_n} / {cond_n}" + (f" = {value * 100:.1f}%" if value is not None else "")
    ev = f["evidence"]
    shown = hit_n if is_count else (round(value, 4) if value is not None else None)
    ev.update({"metric_name": metric, "value": shown, "n_samples": hit_n,
               "denominator": cond_n, "source_files": source_files(layers_used)})
    f["cohort_trace"] = steps
    f["limitation"] = limitation_for(parsed, layers_used)
    if cond_n < CFG["min_population"]:
        ev["calculation"] = calc + f". Only {cond_n} samples are in the denominator, which is too few to judge."
        f["needs_human_review"], f["review_reason"] = True, "The denominator is too small to judge the claim."
        f["next_actions"] = ["Widen the population or drop a condition so more samples remain."]
        return f
    if q is None:
        ev["calculation"] = calc + ". The claim has no measurable threshold, so no verdict is given."
        f["needs_human_review"], f["review_reason"] = True, "The claim has no measurable threshold; a person must decide what counts as enough."
        f["next_actions"] = ["State a number the claim should meet (for example, at least 75 percent), then re-run.",
                             "Ask a reviewer what counts as enough for the intended question."]
        return f
    ok = satisfied(q, value, hit_n, cond_n)
    f["verdict"] = "supported" if ok else "contradicted"
    ev["calculation"] = calc + f". Claim read as: {q['reading']}."
    lead = value if q["kind"] == "fraction" else hit_n
    if q["comparator"] != "~" and abs(lead - q["threshold"]) <= (CFG["borderline_margin"] if q["kind"] == "fraction" else 0):
        f["needs_human_review"], f["review_reason"] = True, "The result sits within 2 points of the claim's threshold."
    # robustness: same claim, but over every sample type instead of the chosen population
    alt_ids = ctx.all_samples
    if parsed["pop_code"] == "01" and len(alt_ids) != len(pop_ids):
        a_steps, a_cond, a_hit = compute(ctx, parsed, alt_ids, "all samples")
        a_val = a_hit / a_cond if a_cond else None
        if a_val is not None:
            alt_ok = satisfied(q, a_val, a_hit, a_cond)
            alt_value = round(a_val, 4) if q["kind"] == "fraction" else a_hit
            f["robustness"] = {"alt_rule": "count every sample type (tumor, normal, metastasis) instead of primary tumors only",
                               "alt_value": alt_value, "verdict_changes": alt_ok != ok}
            if alt_ok != ok:
                f["needs_human_review"] = True
                f["review_reason"] = "The verdict flips if normal and metastasis samples are counted too."
    if f["verdict"] == "contradicted":
        f["next_actions"] = [f"Restrict the question to the {hit_n} samples that have {tlabel}, or choose a layer with better coverage.",
                             f"Restate the claim with the measured figure ({hit_n} of {cond_n})."]
    else:
        f["next_actions"] = ["Check data quality inside the file, not just presence, before relying on it."]
        if f["robustness"] and f["robustness"]["verdict_changes"]:
            f["next_actions"].append("Decide which sample types the question is really about.")
    return f


def audit(ctx, claims, title):
    findings = [evaluate_claim(ctx, f"claim-{i:03d}", c) for i, c in enumerate(claims, 1)]
    return OrderedDict([
        ("is_mock", False), ("schema_version", "draft-0"),
        ("data_release", {"name": "TCGA-BRCA (frozen event release)",
                          "checksum_verified": ctx.checksums["status"] == "verified",
                          "checksum_status": ctx.checksums["status"]}),
        ("report_title", title), ("interpretation_config", CFG),
        ("guardrails_source", GUARDRAILS_SOURCE), ("findings", findings),
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Evidence engine v1")
    ap.add_argument("--data-dir", default=L.DEFAULT_DIR)
    ap.add_argument("--report", help="text or markdown file with numbered or bulleted claims")
    ap.add_argument("--claim", action="append", default=[], help="a single claim (can repeat)")
    ap.add_argument("--out", default=os.path.join("out", "findings.json"))
    args = ap.parse_args(argv)
    claims, title = list(args.claim), "Ad hoc claims"
    if args.report:
        with open(args.report, encoding="utf-8") as fh:
            claims += split_claims(fh.read())
        title = os.path.basename(args.report)
    if not claims:
        sys.exit("give --report FILE or at least one --claim TEXT")
    if not os.path.isdir(args.data_dir):
        sys.exit(f"data folder not found: {os.path.abspath(args.data_dir)}")
    ctx = Context(args.data_dir)
    doc = audit(ctx, claims, title)
    print(f"\nGuardrails: {GUARDRAILS_SOURCE}   Checksums: {ctx.checksums['status']}\n")
    problems = 0
    for f in doc["findings"]:
        ev = f["evidence"]
        val = "-" if ev["value"] is None else (f"{ev['value']:.3f}" if isinstance(ev["value"], float) else ev["value"])
        errs = VF.check_finding(f) if VF else []
        problems += len(errs)
        print(f"{f['id']}  {f['verdict']:<22} value={val:<7} n={ev['n_samples']}/{ev['denominator']}  "
              f"flags={f['guardrail_flags']} review={f['needs_human_review']}")
        print(f"          {f['claim_text'][:90]}")
        for e in errs:
            print("          CONTRACT PROBLEM:", e)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    print(f"\nSaved {args.out}  ({len(doc['findings'])} findings, {problems} contract problems)")


if __name__ == "__main__":
    main()
