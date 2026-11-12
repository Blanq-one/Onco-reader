# Contract and mock data (draft-0)

Purpose: let everyone build in parallel while the real data pipeline is still
being written. Everything here is MOCK. The numbers are invented.

## Files
- `mock_findings.json`: 8 fake findings that cover every case the app must handle.
- `mock_report.md`: the fake report the Claim Auditor would "upload".
- `validate_findings.py`: checks any findings file against the draft contract.
  Run `python validate_findings.py mock_findings.json`.

## What one finding carries
claim_text, verdict (supported / contradicted / insufficient_evidence),
evidence (metric, value, n_samples, denominator, source files, calculation),
cohort_trace (the join-by-join shrink), limitation (always present),
needs_human_review + review_reason, guardrail_flags, next_actions (concrete,
non-clinical steps), and an optional
robustness block (same claim under an alternative inclusion rule).

## For A (frontend): screens and states to design for
1. Report view: claims listed, each with a verdict badge.
2. Verdict card: headline number with its denominator (e.g. 440 of 1080).
3. Cohort funnel: chart from cohort_trace showing how each join shrinks the cohort.
4. "Show me the calculation" panel: calculation text and source files.
5. Limitation banner: always visible on every card, never hidden.
6. Needs-review flag: shows review_reason, with approve / reject / ask-for-more buttons.
7. Blocked and cannot-answer states: clear message, no number shown (mock-004, 007, 008).
8. Robustness toggle: swap to the alternative rule and show if the verdict changes (mock-003).
9. Mock banner: when is_mock is true, show a loud "SAMPLE DATA" label.
10. Accessibility: keyboard navigation, and labels that work without color.

## For D (guardrails and tests): behavior spec
- Every finding has a non-empty limitation and calculation.
- supported/contradicted must have a value and source files.
- Clinical or treatment claims never get a number or a supported verdict (mock-004).
- Requests about one individual patient are blocked (mock-007).
- If the needed column does not exist, verdict is insufficient_evidence with
  the data_cannot_answer flag (mock-008).
- Cohort traces never grow and must be continuous.
- needs_human_review requires a review_reason.
- Nothing secret or raw in the repo: no keys, no raw TCGA files.
Add new edge-case claims to the mock file and extend validate_findings.py.

## For the evidence engine owner
Produce JSON in this same shape from real data. When it is ready, point the
frontend at the real file instead of the mock. Before the final merge, compare
these field names to the organizers' shared format (format/ in the challenge
repo) and add a small converter if they differ.
