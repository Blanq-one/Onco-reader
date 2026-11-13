"""Pre-check logic: normalise the text, run the rules in rules.py, build the answer.

check_claim never raises. Any unexpected error fails CLOSED (the claim is
refused as invalid_input) so a bug here can never let a claim through unchecked.
"""
import re
import unicodedata

from .rules import FLAG_ORDER, MAX_CLAIM_CHARS, READINESS, RULES, SCAN_LIMIT

# Characters people use to hide words from filters: zero-width spaces and joiners,
# soft hyphens, bidi controls, word joiners, byte-order marks.
_INVISIBLE = re.compile("[­͏؜ᅟᅠ឴឵᠎​-‏‪-‮⁠-⁯﻿]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_PUNCT = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
                        "“": '"', "”": '"', "„": '"', "″": '"',
                        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
                        "―": "-", "−": "-"})

# One plain sentence per flag. {label} comes from the first rule that fired.
REASONS = {
    "invalid_input": "Rejected: {label}.",
    "prompt_injection_suspected": "Blocked: the text {label}, and instructions inside a report are never followed.",
    "phi_like_input": "Blocked: the text {label}, so remove personal details before checking it.",
    "reidentification_blocked": "Blocked: this is a {label}, which is not allowed with this data.",
    "individual_level_request_blocked": "Blocked: {label}, and only cohort-level questions can be checked.",
    "clinical_claim_blocked": "Blocked: this reads as a {label}, and this tool checks data readiness only.",
}
PLAIN = {
    "invalid_input": "invalid input",
    "prompt_injection_suspected": "instructions aimed at the system",
    "phi_like_input": "personal details",
    "reidentification_blocked": "re-identification",
    "individual_level_request_blocked": "a single person",
    "clinical_claim_blocked": "a clinical claim",
}
PHI_RULE_PREFIX = "phi_"


def normalise(text):
    """Make look-alike text match the plain patterns: fullwidth letters, curly
    quotes, accents and hidden characters all collapse to plain ASCII-ish text."""
    t = unicodedata.normalize("NFKC", text)
    t = _INVISIBLE.sub("", t)
    t = _CONTROL.sub(" ", t)
    t = t.translate(_PUNCT)
    t = "".join(ch for ch in unicodedata.normalize("NFKD", t) if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", t).strip()


def _invalid(detail):
    return _answer(["invalid_input"], {"invalid_input": detail}, ["invalid_input"])


def _answer(flags, first_label, rule_ids):
    if not flags:
        return {"allowed": True, "flags": [], "reason": "", "rules": []}
    main = flags[0]
    reason = REASONS[main].format(label=first_label[main])
    if len(flags) > 1:
        reason = reason[:-1] + " (also flagged: " + ", ".join(PLAIN[f] for f in flags[1:]) + ")."
    return {"allowed": False, "flags": list(flags), "reason": reason, "rules": list(rule_ids)}


def _scan(t):
    """Return the rules that fire on normalised text t, in RULES order."""
    low = t.lower()
    ready = bool(READINESS.search(low))
    hits = []
    for rule in RULES:
        if rule.readiness_exempt and ready:
            continue
        hay = t if rule.on_original else low
        if rule.requires is not None and not rule.requires.search(hay):
            continue
        if any(p.search(hay) for p in rule.patterns):
            hits.append(rule)
    return hits


def _check(text):
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if not isinstance(text, str):
        return _invalid("the claim is not text")
    t = normalise(text[: SCAN_LIMIT * 2])[:SCAN_LIMIT]
    if not t:
        return _invalid("the claim is empty")
    if not any(ch.isalpha() for ch in t):
        return _invalid("the claim has no words, only numbers or symbols")
    hits = _scan(t)
    first_label = {}
    for rule in hits:
        first_label.setdefault(rule.flag, rule.label)
    flags = [f for f in FLAG_ORDER if f in first_label]
    if len(text) > MAX_CLAIM_CHARS:
        if "invalid_input" not in flags:
            flags.insert(0, "invalid_input")
        first_label["invalid_input"] = (f"the claim is longer than {MAX_CLAIM_CHARS} characters, "
                                        "so split it into single sentences")
    return _answer(flags, first_label, [r.id for r in hits])


def check_claim(text):
    """Pre-check one claim before it reaches the evidence engine.

    Returns {"allowed": bool, "flags": [str], "reason": str, "rules": [str]}.
    flags use the names in contract/validate_findings.py, in FLAG_ORDER. reason
    is one plain sentence for the UI ("" when allowed). rules lists the rule ids
    that fired, so every refusal can be traced back to rules.py.
    """
    try:
        return _check(text)
    except Exception:  # fail closed: never crash, never let an unchecked claim through
        return _invalid("the claim could not be checked safely, so rewrite it as a plain sentence")


def explain(text):
    """For people debugging a rule: which rules fired and on what text.
    Matched text from PHI rules is masked so this never echoes personal details."""
    if not isinstance(text, str):
        return []
    t = normalise(text[: SCAN_LIMIT * 2])[:SCAN_LIMIT]
    out = []
    for rule in _scan(t):
        hay = t if rule.on_original else t.lower()
        m = next((p.search(hay) for p in rule.patterns if p.search(hay)), None)
        shown = "[masked]" if rule.id.startswith(PHI_RULE_PREFIX) else (m.group(0) if m else "")
        out.append({"rule": rule.id, "flag": rule.flag, "label": rule.label, "matched": shown})
    return out


# Full participant or sample barcode, with any sample, vial or aliquot suffix (TCGA-A7-A0DB-01A-11R).
_BARCODE_FULL = re.compile(r"\btcga-[a-z0-9]{2}-[a-z0-9]{4}(?:-[a-z0-9]+)*", re.I)
REDACT_RULE_IDS = ("individual_patient_id",)  # besides every phi_ rule


def redact(text):
    """Return text with identifying spans replaced by [REDACTED]: personal details
    (every phi_ rule), participant barcodes and patient numbers.

    Engine v1.1.2 stores this instead of the raw claim for findings blocked as
    individual-level or re-identification (phi_like_input claims are withheld whole).
    """
    if not isinstance(text, str):
        return ""
    t = _BARCODE_FULL.sub("[REDACTED]", normalise(text))
    for rule in RULES:
        if rule.id.startswith(PHI_RULE_PREFIX) or rule.id in REDACT_RULE_IDS:
            for p in rule.patterns:
                t = p.sub("[REDACTED]", t)
    return t
