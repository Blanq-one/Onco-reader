# Task: guardrails and tests (folders: src/guardrails/, tests/, scripts/)

Read first: CLAUDE.md, docs/D_BRIEF.md, tests/edge_cases.csv, the three test
files in tests/, contract/validate_findings.py, contract/README.md.

## Build
1. src/guardrails/__init__.py exporting check_claim(text) -> dict with
   {"allowed": bool, "flags": [str], "reason": str}. Flag names must be the ones
   in contract/validate_findings.py (GUARDRAIL_FLAGS). Rules must be explainable
   (regular expressions and keyword lists in one clear config block). Never
   crash on any input (empty, huge, odd characters, other languages).
   Detect: clinical claims (treatment effect, treatment recommendation, diagnosis,
   patient risk score), individual-level requests (TCGA-style barcodes, "this
   patient"), re-identification (outside records, matching to identities),
   PHI-like text (names with dates of birth, record numbers, emails, phone
   numbers), prompt injection, empty or whitespace input.
2. Make the whole bank in tests/edge_cases.csv pass:
   python -m unittest discover -s tests -v
3. Grow the bank to 60+ rows. Include near misses that must be ALLOWED, for
   example "Survival data is available for most ER-positive tumors" and "At
   least 100 deaths among ER-positive tumors" (data questions, not clinical
   claims), plus mixed claims, synonyms and polite wording of clinical
   requests, other languages, very long text, and injection text. False blocks
   count as bugs.
4. Extend tests/test_contract.py with invariants on real findings: run
   python src/engine/engine.py (see CLAUDE.md) on contract/demo_report.md into a
   temp file and check every finding with contract/validate_findings.py. Skip
   that test cleanly if ../challenge-ref data is missing.
5. scripts/scan_repo.py: a single command that runs the secrets, raw-data and
   overclaiming-language checks from tests/test_repo_hygiene.py and prints
   PASS or the list of problems. Run it and fix problems in files you own;
   report problems elsewhere.
6. Confirm the engine now picks up your module (its header line should say
   "Guardrails: src/guardrails") and that its results on contract/demo_report.md
   and contract/sample_claims_v11.md are unchanged except where your rules
   are stricter or looser on purpose. List any verdict that changed.

## Rules
- Edit only src/guardrails/, tests/, scripts/. Do not edit the engine.
- Standard library only.

## Final report (short)
Rules implemented, test counts, any claim whose behavior changed, anything the
engine owner must change.
