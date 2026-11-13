"""Post-check: invariants on the engine's findings before the UI sees them.

check_finding runs the contract validator (contract/validate_findings.py) and
then the stricter rules below. Each returns a list of problem strings; an empty
list means the finding is fine.

The contract validator is loaded lazily on first use. Importing this module must
never fail: the engine imports src.guardrails inside a try/except and silently
falls back to its own rules if anything here raises.
"""
import importlib.util
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VALIDATOR_PATH = os.path.join(ROOT, "contract", "validate_findings.py")

# One place for the thresholds the post-check enforces.
POSTCHECK_CONFIG = {
    "min_events": 20,            # a breakdown group with fewer OS deaths than this must carry low_event_count
    "value_tolerance": 0.0001,   # coverage/share values must equal n_samples / denominator within this
    "expected_guardrails": "src/guardrails",
}

# WHY: a finding stopped by any of these was never computed, so it must not show
# a number or a "supported" verdict, and a person must see it.
BLOCKING_FLAGS = frozenset({
    "clinical_claim_blocked", "individual_level_request_blocked", "reidentification_blocked",
    "phi_like_input", "prompt_injection_suspected", "invalid_input",
})

# WHY: CLAUDE.md bans overclaiming words in user-facing text. Built from regexes
# so this file does not itself contain the banned phrases.
OVERCLAIM = re.compile(r"production[- ](?:ready|level)|clinically\s+validated|clinical[- ]grade|hipaa[- ]compliant|"
                       r"fda[- ]approved|regulatory\s+compliant", re.I)
USER_TEXT_FIELDS = ("limitation", "review_reason")

_validator = None


def _contract_validator():
    global _validator
    if _validator is None:
        spec = importlib.util.spec_from_file_location("_contract_validate_findings", VALIDATOR_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _validator = mod
    return _validator


def check_finding(f):
    """Contract checks plus the stricter guardrail invariants. Returns a list of problems."""
    try:
        problems = list(_contract_validator().check_finding(f))
    except Exception as exc:  # validator missing or broken: report it, keep checking
        problems = [f"contract validator could not run: {exc.__class__.__name__}"]
    fid = f.get("id", "<no id>") if isinstance(f, dict) else "<not a dict>"
    if not isinstance(f, dict) or problems and "missing keys" in problems[0]:
        return problems
    ev = f.get("evidence") or {}
    flags = set(f.get("guardrail_flags") or [])
    verdict = f.get("verdict")

    # Blocked findings never carry a number or a supported verdict, and always go to a person.
    if flags & BLOCKING_FLAGS:
        if verdict != "insufficient_evidence":
            problems.append(f"{fid}: blocked finding has verdict {verdict!r}")
        if ev.get("value") is not None:
            problems.append(f"{fid}: blocked finding shows a value")
        if ev.get("n_samples"):
            problems.append(f"{fid}: blocked finding shows n_samples {ev.get('n_samples')}")
        if not f.get("needs_human_review"):
            problems.append(f"{fid}: blocked finding is not sent for human review")

    # The data cannot answer it, so it cannot be supported or contradicted.
    if "data_cannot_answer" in flags and verdict != "insufficient_evidence":
        problems.append(f"{fid}: data_cannot_answer with verdict {verdict!r}")

    # Low event counts raise the review flag.
    if "low_event_count" in flags and not f.get("needs_human_review"):
        problems.append(f"{fid}: low_event_count without needs_human_review")
    thin = [b for b in ev.get("breakdown") or [] if isinstance(b, dict) and b.get("events", 0) < POSTCHECK_CONFIG["min_events"]]
    if thin and "low_event_count" not in flags:
        problems.append(f"{fid}: {len(thin)} group(s) under {POSTCHECK_CONFIG['min_events']} deaths but no low_event_count flag")

    # Every number traces to its calculation: the trace ends at n_samples, and
    # coverage/share values equal n_samples / denominator.
    trace = f.get("cohort_trace") or []
    if trace and not (flags & BLOCKING_FLAGS) and trace[-1].get("n_after") != ev.get("n_samples"):
        problems.append(f"{fid}: cohort trace ends at {trace[-1].get('n_after')} but n_samples is {ev.get('n_samples')}")
    metric = str(ev.get("metric_name", ""))
    value = ev.get("value")
    if value is not None and metric.startswith(("coverage_", "overlap_", "share_")):
        den = ev.get("denominator") or 0
        if not 0 <= value <= 1:
            problems.append(f"{fid}: {metric} value {value} is outside 0 to 1")
        elif den and abs(value - ev.get("n_samples", 0) / den) > POSTCHECK_CONFIG["value_tolerance"]:
            problems.append(f"{fid}: value {value} does not equal {ev.get('n_samples')} / {den}")
    if value is not None and metric.startswith("count_") and value != ev.get("n_samples"):
        problems.append(f"{fid}: count value {value} differs from n_samples {ev.get('n_samples')}")

    # No overclaiming words in text a user reads.
    texts = [str(f.get(k) or "") for k in USER_TEXT_FIELDS] + [str(a) for a in f.get("next_actions") or []]
    if any(OVERCLAIM.search(t) for t in texts):
        problems.append(f"{fid}: user-facing text contains an overclaiming phrase")
    return problems


def check_document(doc):
    """Whole-file checks plus check_finding on every finding. Returns a list of problems."""
    if not isinstance(doc, dict) or not isinstance(doc.get("findings"), list):
        return ["document has no findings list"]
    problems = []
    if doc.get("is_mock"):
        if not str(doc.get("mock_warning") or "").strip():
            problems.append("mock file needs a mock_warning")
    else:
        rel = doc.get("data_release") or {}
        if not isinstance(rel, dict) or not rel.get("name"):
            problems.append("data_release.name is missing")
        if not isinstance(rel, dict) or not rel.get("checksum_status"):
            problems.append("data_release.checksum_status is missing")
        # WHY: the engine silently falls back to its own rules if src.guardrails fails to import.
        src = doc.get("guardrails_source")
        if src is not None and src != POSTCHECK_CONFIG["expected_guardrails"]:
            problems.append(f"guardrails_source is {src!r}, expected {POSTCHECK_CONFIG['expected_guardrails']!r}")
    ids = [f.get("id") for f in doc["findings"] if isinstance(f, dict)]
    if len(ids) != len(set(ids)):
        problems.append("duplicate finding ids")
    for f in doc["findings"]:
        problems.extend(check_finding(f))
    return problems
