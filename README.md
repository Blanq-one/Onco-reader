# Evidence Navigator (Research Claim Auditor)

**Track:** Evidence Navigator

Paste a report that makes claims about the TCGA-BRCA breast cancer data. Evidence Navigator finds every checkable claim and checks it against the frozen data release. Each claim gets a verdict (supported, contradicted, or insufficient evidence), the numbers behind it with their calculation and source files, a limitation, and next steps.

**Demo video:** _link to be added_

**Required product output:** [`out/audit.json`](out/audit.json), produced from the practice report (`app/samples/practice_brief.md`, the organizers' `products/research-claim-auditor/practice_brief.md`) by step 5 of [Setup and run](#setup-and-run). It passes the organizers' `format/validate.py`. To run on the unseen report, see [Judge's run on the sealed envelope](#judges-run-on-the-sealed-envelope).

## Who it is for

A reviewer has been handed a report and asks: "can we trust this?" They don't want to redo the analysis. They want to know which claims the data backs, which it contradicts, and which it can't settle, with enough evidence to defend each call.

## The workflow they finish

1. **Load the report.** Paste it, upload a PDF, or use the practice report.
2. **Confirm the claims.** Check the sentences that will be tested and the ones skipped, each with a reason.
3. **Run the audit.** Each claim gets:
   - a verdict;
   - the numbers, calculation, source files and cohort trace behind it;
   - its limitation;
   - next actions.

   Clinical, individual-patient and personal-data requests are blocked before any analysis.
4. **Decide.** On each claim marked for review, accept the verdict, override it, or ask for more evidence.
5. **Download the results.**
   - `audit.json`: the organizers' shared findings format v0.2.
   - `review.json`: the reviewer's decisions.

## Team

- _Name_: _role_
- _Name_: _role_
- _Name_: _role_

## What this tool does and does not do

- **It does** check data readiness. It shows whether the TCGA-BRCA files contain enough samples, records, overlap and events to support what a report says.
- **It does not** make clinical claims. There is no diagnosis, no treatment recommendation and no patient risk score. Such requests are blocked.
- **It never** answers questions about one person. Requests about individual patients, re-identification and personal details are blocked.
- **Every number is traceable.** Each one comes with its calculation and source file.
- **Every finding shows its limitation.** The limitation can't be hidden.
- **Claims it can't read are not guessed.** They get "insufficient evidence" and a note on what data would be needed.

## Setup and run

You need:
- Git;
- Python 3.11 (the version we tested with);
- about 100 MB of disk for the data.

The code uses the Python standard library only. Two packages are optional (see the comments in the steps below).

Both repos sit side by side in one folder: the organizers' `challenge-ref` (it holds the data) and this one.

### Windows PowerShell

```powershell
# 1. Get both repos, side by side
mkdir hackathon; cd hackathon
git clone https://github.com/disleveK/oncosys-hackathon-challenge.git challenge-ref
git clone https://github.com/Blanq-one/Onco-reader.git onco-evidence

# 2. Download the TCGA-BRCA data (fetch.py checks every file against the frozen checksums)
cd challenge-ref
python data\tcga-brca\fetch.py
cd ..\onco-evidence

# 3. Optional packages
python -m pip install jsonschema   # only for the organizers' validator (step 5)
python -m pip install pypdf        # only for PDF upload in the app

# 4. Run the tests and the engine on the demo report
python -m unittest discover -s tests
python src\engine\engine.py --data-dir ..\challenge-ref\data\tcga-brca --report contract\demo_report.md --out out\findings.json
python contract\validate_findings.py out\findings.json

# 5. Make audit.json for the practice report and check it with the organizers' validator
python scripts\make_audit.py app\samples\practice_brief.md --data-dir ..\challenge-ref\data\tcga-brca
python ..\challenge-ref\format\validate.py out\audit.json

# 6. Start the app (Ctrl+C stops it), then open http://127.0.0.1:8000/app/
python server\serve.py
```

If Windows says `python` is not found, use `py` instead.

### Mac or Linux

```bash
# 1. Get both repos, side by side
mkdir hackathon && cd hackathon
git clone https://github.com/disleveK/oncosys-hackathon-challenge.git challenge-ref
git clone https://github.com/Blanq-one/Onco-reader.git onco-evidence

# 2. Download the TCGA-BRCA data (fetch.py checks every file against the frozen checksums)
cd challenge-ref
python3 data/tcga-brca/fetch.py
cd ../onco-evidence

# 3. Optional packages
python3 -m pip install jsonschema   # only for the organizers' validator (step 5)
python3 -m pip install pypdf        # only for PDF upload in the app

# 4. Run the tests and the engine on the demo report
python3 -m unittest discover -s tests
python3 src/engine/engine.py --data-dir ../challenge-ref/data/tcga-brca --report contract/demo_report.md --out out/findings.json
python3 contract/validate_findings.py out/findings.json

# 5. Make audit.json for the practice report and check it with the organizers' validator
python3 scripts/make_audit.py app/samples/practice_brief.md --data-dir ../challenge-ref/data/tcga-brca
python3 ../challenge-ref/format/validate.py out/audit.json

# 6. Start the app (Ctrl+C stops it), then open http://127.0.0.1:8000/app/
python3 server/serve.py
```

### Judge's run on the sealed envelope

After steps 1 to 3 above, from the `hackathon` folder. Use the envelope number and four words from your card; the practice envelope is `practice orange meadow pilot lantern`.

```powershell
# 1. Open the envelope. On Windows, set UTF-8 first: unseal.py prints check marks, and without this it can stop
#    with a UnicodeEncodeError (always when its output is piped or redirected).
cd challenge-ref
$env:PYTHONUTF8=1
python envelopes\unseal.py 07 word1 word2 word3 word4   # your envelope number and its four words
cd ..\onco-evidence

# 2. Command line: audit.json for the envelope's report, then the organizers' validator
python scripts\make_audit.py ..\challenge-ref\envelopes\opened\E07\claim_auditor_report.md --data-dir ..\challenge-ref\data\tcga-brca
python ..\challenge-ref\format\validate.py out\audit.json

# 3. Or in the app: start the server, open http://127.0.0.1:8000/app/, upload claim_auditor_report.md,
#    press Extract claims, then Run the audit, then Download audit.json (on Results or Summary)
python server\serve.py
```

On Mac or Linux, use `python3`, forward slashes, and `PYTHONUTF8=1 python3 envelopes/unseal.py ...`.

- Claims are checked against the frozen release from `fetch.py` (release A). The envelope's `release/` folder is the input for Cohort Control Tower. The engine can read that folder too (`--data-dir ..\challenge-ref\envelopes\opened\E07\release`), but it has no `sources.csv`, so its checksum status is "unknown", and `make_audit.py` needs a `sources.csv` to write the file checksums into audit.json.
- If the answer key lists each part of a sentence as its own claim, add `--split-subclaims` to `make_audit.py` or `serve.py` (see [below](#if-the-answer-key-splits-sentences)).
- On our machine the whole run, from unsealing to a saved and validated audit.json, takes under 15 seconds.

### Server options

- `--data-dir PATH`: the data folder. The default is `$TCGA_DATA_DIR`; otherwise `../challenge-ref/data/tcga-brca`.
- `--port 8001`: use this if port 8000 is busy.
- `--host`: the default is `127.0.0.1`, this computer only.
- `--split-subclaims`: the app's audit.json download gets one finding per part of a multi-part sentence (see "If the answer key splits sentences" below).

At startup the server prints:
- whether the data passed its checksum checks;
- whether the guardrails loaded;
- whether PDF upload is on;
- whether audit.json has one finding per sentence or per part.

If the guardrails module is missing, the server refuses to start.

### Check a fresh clone

This command clones the committed state of the repo into a temp folder. It then:
1. runs the tests;
2. runs the engine on `contract/demo_report.md` and validates the result;
3. makes `audit.json` from the same report and checks it with the organizers' `format/validate.py`;
4. starts the server and checks every endpoint, including that unsafe requests are refused.

It prints PASS or FAIL for each step.

```powershell
python scripts\fresh_clone_check.py . --data-dir ..\challenge-ref\data\tcga-brca
```

On Mac or Linux, use `python3` and forward slashes. `python scripts/run_checks.py` runs the repo's other checks: tests, contract, guardrail bank and repo hygiene.

## Local API

The app uses these endpoints, and you can call them yourself. POST bodies are JSON sent with `Content-Type: application/json`. Errors come back as `{"error": "..."}`.

| Endpoint | Body | Returns |
|---|---|---|
| `GET /api/health` | | `{"ok": true, "checksum_status": "...", "pdf_text": true}` |
| `POST /api/extract` | `{"report": "text"}` | `{"claims": [{"id", "text", "source"}], "skipped": [{"text", "reason"}]}` |
| `POST /api/audit` | `{"report": "text"}` or `{"claims": ["...", "..."]}` | the findings document described in `contract/README.md`, plus `skipped_sentences` for a report |
| `POST /api/audit-json` | `{"report": "text"}` | `audit.json` in the organizers' shared format v0.2 |
| `POST /api/pdf-text` | the PDF file, sent with `Content-Type: application/pdf` | `{"text", "pages", "truncated"}`, or status 501 `{"error": "paste the text instead"}` without pypdf |

Notes on the bodies:
- Any body may also carry `"title"`, a short report name.
- `claims` may be plain strings or the `{"text", "source"}` objects that `/api/extract` returns.
- If the post-check refuses a document, the answer is status 500 with `{"error": "post-check failed"}`.

PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
$body = @{ claims = @("ER status is recorded for most samples.") } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/audit -ContentType "application/json" -Body $body
```

curl (Mac, Linux, or Git Bash):

```bash
curl -s http://127.0.0.1:8000/api/health
curl -s -X POST http://127.0.0.1:8000/api/audit -H 'Content-Type: application/json' \
  -d '{"claims": ["ER status is recorded for most samples."]}'
```

To save `audit.json` from PowerShell, use `Invoke-WebRequest ... -OutFile audit.json`, not `Out-File`. Windows PowerShell 5.1 adds a byte-order mark that the organizers' validator can't read. `scripts/make_audit.py` writes the file correctly.

## If the answer key splits sentences

Some sentences hold more than one claim, for example "Luminal A is the largest RNA subtype, accounting for about 62% of tumors". The engine checks each part and gives the sentence its worst verdict. By default `audit.json` has **one finding per sentence**, with the parts listed in its evidence.

If the organizers' answer key lists each part as its own claim, add `--split-subclaims` to the command, with no file to edit:

```
python scripts/make_audit.py REPORT --split-subclaims
python server/serve.py --split-subclaims
```

The flag sets `SPLIT_SUBCLAIMS` (top of `src/export/audit_json.py`) for that run only. `/api/health` reports `split_subclaims`. Each part then becomes its own `claim_check` finding with its own `claim_text`, verdict and `correct_value`, with ids such as `claim-002.1` and `claim-002.2`. The sentence-level finding is left out for those sentences. Sentences with one claim come out the same either way. A part's `claim_text` is the part as the engine checked it. The full sentence, as written in the report, is quoted in that finding's evidence.

Both settings pass the organizers' validator.

## Limits

- **Request size:**
  - JSON bodies up to 100 KB;
  - at most 50 claims per request;
  - at most 2000 characters per claim. The guardrails also reject any claim over 1000 characters as invalid input, so keep claims to one sentence each.
  - Longer reports must be split.
- **PDF upload:**
  - up to 5 MB, and only the first 100 pages are read;
  - at most 90,000 characters of text come back;
  - PDFs with real text only: there is no OCR for scanned pages;
  - it needs pypdf.
- **One audit at a time.** Other requests wait their turn.
- **This computer only.** The server listens on 127.0.0.1. It refuses requests addressed to another host name and requests sent by other web pages. It has no login, so it is not meant for a shared network.
- **Privacy:**
  - Logs hold only the method, route and status, never claim text or request bodies.
  - Text the guardrails flag as personal details is withheld in every answer.
  - Patient barcodes and patient numbers are redacted.
- **Data scope:**
  - Results describe the frozen TCGA-BRCA release fetched by `challenge-ref`, and nothing else.
  - If the files don't match the frozen checksums, every limitation says so.
- **Claims it understands:** the engine (v1.3.0) reads claims as small templates:
  - coverage of a data layer, and overlap between layers;
  - counts and group sizes, sample types (metastatic, normal tissue) and slide counts (diagnostic, frozen);
  - ranges ("between 40% and 50%"), word fractions ("about a third") and ratios ("about two to one");
  - how often a named gene is mutated, and which gene is mutated most often;
  - survival events, and survival comparisons (shown with each group's deaths, never judged);
  - "large enough for" readiness questions.

  The full list is at the top of `src/engine/engine.py`.

  Anything else gets "insufficient evidence" with a note on what data would be needed.
- **Guardrail coverage:**
  - The guardrails match English wording, plus common Spanish, Portuguese, French, German and Italian phrasings of clinical claims.
  - Clinical claims in non-Latin scripts are not detected.
  - A few legitimate questions can be blocked. They are listed in the comments of `src/guardrails/rules.py`.
- **What audit.json leaves out.** It holds the machine verdicts only. Reviewer decisions go to `review.json`, because the shared format has no place for them. Next actions, data notes and skipped sentences are not carried either.

## Project layout

```
app/             frontend: plain HTML, CSS and JavaScript, no build step, works offline
server/serve.py  local server: the app at /app/ and the JSON API at /api/
src/engine/      evidence engine: claims in, checked findings out
src/data/        TCGA-BRCA loader and checksum checks
src/guardrails/  pre-check on every claim, post-check on every findings document
src/export/      audit.json exporter (organizers' shared format v0.2) and review.json
contract/        the findings shape (README.md), its validator, demo and mock reports
scripts/         make_audit.py, fresh_clone_check.py, run_checks.py and other checks
tests/           unit tests and the guardrail edge-case bank (tests/edge_cases.csv)
out/             generated findings, plus the files the app's example report loads
docs/            briefs and task prompts
```

Raw TCGA files are never committed. They stay in `../challenge-ref`, which is read-only for this project.

## Third-party licenses

- **Our code:** the Python standard library only (Python Software Foundation License). The frontend uses no third-party libraries.
- **pypdf** (BSD-3-Clause, optional): used only by `POST /api/pdf-text` when installed. Without it, that endpoint answers 501 and you paste the text instead.
- **jsonschema** (MIT, optional): used only by the organizers' validator, `challenge-ref/format/validate.py`. That includes the steps of `scripts/fresh_clone_check.py` that run the validator. Our code does not import it.
- **pandas** (BSD-3-Clause, optional, tests only): `tests/test_engine_claims.py` recomputes the engine's numbers with pandas on the real data, as an independent check. Those tests skip without it.
- **Node.js** (MIT, optional, tests only): `tests/test_app_review_guard.py` runs the app's review rule (`app/js/state.js`) with Node. It skips without it.
- **Data:** TCGA-BRCA from the UCSC Xena hub, and curated survival from the TCGA Pan-Cancer Clinical Data Resource. Both are fetched by the organizers' script and never committed here. Terms and required citations are in `challenge-ref/DATA_LICENSES.md`.
