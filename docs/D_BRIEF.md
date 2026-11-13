# D's brief: guardrails, tests, edge cases, repo hygiene

## Why this job matters (plain English)
This event is about whether oncology data can be trusted. Judges reward a tool
that shows its limits and refuses what it should refuse, and they penalize
overclaiming. You are the person who makes sure the project never says or does
something it should not. Your work is also what makes the demo safe to run
without anyone narrating.

## What you own
1. The guardrail module: `src/guardrails/`
2. The tests: `tests/`
3. The edge-case bank: `tests/edge_cases.csv`
4. Repo hygiene: secrets, raw data, overclaiming language
5. The fresh-clone README check and the Friday repo swap with the paired team

You do not own the evidence engine (that is the data teammate) or the UI (A).
Agree on the interfaces below, then work in parallel.

## Setup
1. Clone the team repo, create a virtual environment, install requirements.
2. Copy this package's `tests/` folder into the repo root. Contract files live in `contract/`.
3. Run `python -m unittest discover -s tests -v`. pytest also works if you have it.
4. Today: contract and hygiene tests pass, and the guardrail tests skip because
   `check_claim` does not exist yet. Your first goal is to make them run and pass.

## Read first (in the challenge repo)
- `RULES.md` and `SUBMISSION_CHECKLIST.md`: turn them into a tick list for the team.
- The event rules in short: no PHI, no patient records, no clinical decisions
  (no diagnosis, treatment recommendation, or patient risk score), no
  re-identification or linking to outside sources, no restricted data, no
  overclaiming (clinical validity, regulatory compliance, production readiness).
- The project must show limitations, uncertainty, data sources, and when a
  person needs to review a result.
- The joining rule in `data/README.md`: only join records where a documented match exists.

## Deliverable 1: `check_claim(text)` (the pre-check)
Runs on each claim before it reaches the evidence engine.

```python
def check_claim(text: str) -> dict:
    # returns {"allowed": bool, "flags": [str], "reason": str}
```
- `allowed` is True only if the claim may go on to the engine.
- `flags` use the names in `contract/validate_findings.py` (`GUARDRAIL_FLAGS`):
  `clinical_claim_blocked`, `individual_level_request_blocked`,
  `reidentification_blocked`, `phi_like_input`, `prompt_injection_suspected`,
  `invalid_input`. (`data_cannot_answer` and `low_event_count` come from the
  engine, not from you.)
- `reason` is one plain sentence the UI can show.
- It must never crash, whatever the input: empty, huge, weird characters, other languages.

What to detect (start with simple rules, improve with the edge-case bank):
- Clinical: treatment effect, treatment recommendation, diagnosis, patient risk
  score, "which treatment is best".
- Individual: TCGA-style barcodes (pattern `TCGA-XX-XXXX`), "this patient",
  requests for one person's attributes.
- Re-identification: outside records, public data, "match to identities".
- PHI-like input: names with dates of birth, record numbers, emails, phone numbers.
- Prompt injection: text in the report that tries to give instructions to the
  system ("ignore previous instructions", "reveal your key").
- Invalid input: empty or whitespace only.

Start with regular expressions and keyword rules. Add an LLM-based check later
only if it stays predictable and testable. Rules you can explain beat clever
rules you cannot.

## Deliverable 2: `check_finding(finding)` (the post-check)
Runs on the engine's output before the UI sees it. Most of it already exists
as `check_finding` in `contract/validate_findings.py`. Extend it with:
- Blocked findings never carry a number or a "supported" verdict.
- Every finding has a non-empty limitation and calculation.
- The cohort trace never grows and is continuous.
- Verdicts that are not "supported" have at least one next action.
- Low event counts raise the review flag. Set the threshold in one config value.
- The data release name and checksum status are present on every output.

## Deliverable 3: the edge-case bank
`tests/edge_cases.csv` has 26 starter cases. Columns: id, category, claim_text,
expected_action, expected_flag, notes.
- `allow`: must pass the pre-check.
- `block` / `reject_input`: must be refused with the expected flag.
- `engine_refuses`: the evidence engine must answer "insufficient evidence"
  with the `data_cannot_answer` flag. The pre-check skips these. Share them
  with the engine owner as their test list.

Grow it to 50 or more. Ideas to add:
- Claims that mix a safe part and a clinical part (the clinical part must never get a verdict).
- Two claims in one report that contradict each other.
- The same claim repeated (duplicates).
- Percentages versus counts, impossible numbers, negative numbers.
- Claims about other cancer types or other datasets.
- Very long reports, tables pasted as text, markdown or HTML in the report.
- A report containing only injection text.
- Different phrasing of the same clinical request (synonyms, questions, polite wording).
- Near misses that should be allowed (for example "the cohort has a survival
  column" is a data question, not a clinical claim). False blocks also cost us.

## Deliverable 4: repo hygiene (`tests/test_repo_hygiene.py`)
Already checks: banned overclaiming phrases, secret patterns, raw data files
and huge files, and `.gitignore` coverage.
Your extra work:
- Add Gitleaks as a pre-commit hook, and run it over the full history before submitting.
- Confirm `.gitignore` covers data folders and `.env`. Provide `.env.example`
  with key names only.
- Make sure no private URLs, personal info, or restricted files are in the repo.
- Check that attribution and licenses follow `DATA_LICENSES.md`.
- Search the UI text and README for wording that implies clinical advice or
  readiness for real-world use.

## Deliverable 5: the fresh-clone test and Friday swap
- Every day: clone the repo into a clean folder, follow only the README, and
  confirm the app runs. Fix the README, not your memory.
- Friday (Checkpoint 2): clone the paired team's repo, follow their README
  alone, and post in Discord what worked and what broke. Be specific and kind.
- Before code freeze (Saturday 2:15 PM ET): walk through `SUBMISSION_CHECKLIST.md`
  line by line with the team.

## Coordination
- With the evidence engine owner: agree on the finding fields (they are in
  `contract/README.md`), then ask for a hook so you can run `check_finding`
  on every output automatically.
- With A (frontend): agree what the UI shows for each flag. All blocked flags
  (the ones ending in `_blocked`, plus `phi_like_input`,
  `prompt_injection_suspected`, `invalid_input`) should show the blocked state
  with no number. Ask A to add a test hook so you can check "blocked means no number".
- Folder ownership: `src/guardrails/`, `tests/`, `scripts/`, and the hygiene
  config are yours. Use small branches and pull requests, and ask for review.

## Priorities
- **P0:** `check_claim` passing the whole bank, `check_finding` invariants,
  hygiene tests green, Gitleaks clean, fresh-clone README works.
- **P1:** 50 or more edge cases, false-block tests, UI behavior checks for
  blocked states, the Friday swap report.
- **P2:** simple pre-commit setup for the whole team, a one-command
  `make check` or script that runs every test, and a short "limits and
  guardrails" paragraph for the pitch that the team can reuse.

## Definition of done
- `python -m unittest discover -s tests` passes on a clean clone.
- Every case in the bank behaves as expected, and new cases were added.
- Nothing blocked ever shows a number or a "supported" verdict.
- No secrets, no raw data, no overclaiming phrases anywhere in the repo.
- The README works from a fresh clone, and the Friday swap report is posted.
