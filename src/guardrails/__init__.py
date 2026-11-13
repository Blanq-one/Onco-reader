"""Guardrails for the Evidence Navigator.

Pre-check (runs on each claim before the engine):
    check_claim(text) -> {"allowed": bool, "flags": [str], "reason": str, "rules": [str]}

Post-check (runs on the engine's output before the UI):
    check_finding(finding) -> [problem strings]
    check_document(doc)    -> [problem strings]

All rules live in rules.py (one config block, each with a WHY and known false
positives). Uses relative imports so it works both as `src.guardrails` (the
engine) and as `guardrails` (tests put src/ on sys.path).
"""
from .check import check_claim, explain, normalise, redact
from .postcheck import BLOCKING_FLAGS, POSTCHECK_CONFIG, check_document, check_finding
from .rules import FLAG_ORDER, MAX_CLAIM_CHARS, RULE_IDS, RULES

__all__ = ["check_claim", "explain", "normalise", "redact", "check_finding", "check_document",
           "BLOCKING_FLAGS", "POSTCHECK_CONFIG", "FLAG_ORDER", "MAX_CLAIM_CHARS", "RULES", "RULE_IDS"]
