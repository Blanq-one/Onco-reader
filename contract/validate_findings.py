"""Draft contract checker for findings JSON (plain Python, no dependencies).

Usage: python validate_findings.py mock_findings.json

NOTE: This is a draft. Align field names with the organizers' shared findings
format (format/ folder in the challenge repo) before the final merge.
"""
import json
import sys

VERDICTS = {"supported", "contradicted", "insufficient_evidence"}
GUARDRAIL_FLAGS = {
    "clinical_claim_blocked",
    "individual_level_request_blocked",
    "data_cannot_answer",
    "low_event_count",
    "reidentification_blocked",
    "phi_like_input",
    "prompt_injection_suspected",
    "invalid_input",
}
REQUIRED_FINDING_KEYS = {
    "id", "claim_text", "verdict", "evidence", "cohort_trace",
    "limitation", "needs_human_review", "review_reason", "guardrail_flags",
    "next_actions",
}
REQUIRED_EVIDENCE_KEYS = {
    "metric_name", "value", "n_samples", "denominator", "source_files", "calculation",
}


def check_finding(f):
    errors = []
    fid = f.get("id", "<no id>")
    missing = REQUIRED_FINDING_KEYS - set(f)
    if missing:
        errors.append(f"{fid}: missing keys {sorted(missing)}")
        return errors
    if f["verdict"] not in VERDICTS:
        errors.append(f"{fid}: bad verdict {f['verdict']!r}")
    if not str(f["limitation"]).strip():
        errors.append(f"{fid}: limitation must be non-empty")
    ev = f["evidence"]
    missing_ev = REQUIRED_EVIDENCE_KEYS - set(ev)
    if missing_ev:
        errors.append(f"{fid}: evidence missing {sorted(missing_ev)}")
    else:
        if not str(ev["calculation"]).strip():
            errors.append(f"{fid}: calculation must be non-empty")
        if ev["n_samples"] > ev["denominator"]:
            errors.append(f"{fid}: n_samples exceeds denominator")
        if f["verdict"] != "insufficient_evidence" and (ev["value"] is None or not ev["source_files"]):
            errors.append(f"{fid}: supported/contradicted needs a value and source files")
    for flag in f["guardrail_flags"]:
        if flag not in GUARDRAIL_FLAGS:
            errors.append(f"{fid}: unknown guardrail flag {flag!r}")
    if f["needs_human_review"] and not f["review_reason"]:
        errors.append(f"{fid}: needs_human_review requires a review_reason")
    if f["verdict"] == "insufficient_evidence" and not f["guardrail_flags"] \
            and not f["needs_human_review"] and f["evidence"].get("value") is not None:
        pass  # allowed: thin evidence with a value
    actions = f["next_actions"]
    if not isinstance(actions, list) or any(not str(a).strip() for a in actions):
        errors.append(f"{fid}: next_actions must be a list of non-empty strings")
    elif f["verdict"] != "supported" and not actions:
        errors.append(f"{fid}: non-supported findings need at least one next action")
    prev_after = None
    for step in f["cohort_trace"]:
        if step["n_after"] > step["n_before"]:
            errors.append(f"{fid}: cohort step {step['step']!r} grows the cohort")
        if prev_after is not None and step["n_before"] != prev_after:
            errors.append(f"{fid}: cohort trace is not continuous at {step['step']!r}")
        prev_after = step["n_after"]
    return errors


def main(path):
    with open(path) as fh:
        doc = json.load(fh)
    errors = []
    if doc.get("is_mock") and not doc.get("mock_warning"):
        errors.append("mock file needs a mock_warning")
    ids = [f.get("id") for f in doc.get("findings", [])]
    if len(ids) != len(set(ids)):
        errors.append("duplicate finding ids")
    for f in doc.get("findings", []):
        errors.extend(check_finding(f))
    if errors:
        print("FAILED")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print(f"ok: {len(doc['findings'])} findings valid")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "mock_findings.json")
