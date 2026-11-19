# OncoReader (Evidence Navigator)

Check every claim in a report against the real data.

Paste a report that makes claims about the TCGA-BRCA breast cancer data. The app finds every checkable claim and checks it against the frozen data release. Each claim gets a verdict (supported, contradicted, or insufficient evidence), the numbers behind it with their calculation and source files, a limitation, and next steps.

A local app: HTML, CSS and vanilla JavaScript in the browser, and a Python server and engine that use only the standard library. No build step, no libraries, no external requests, works offline.

**Track:** Evidence Navigator
**Demo video:** _link to be added_
**Required product output:** [`out/audit.json`](out/audit.json), made from the practice report by `scripts/make_audit.py`. It passes the organizers' `format/validate.py`. The unseen-report run is in [docs/SETUP.md](docs/SETUP.md#judges-run-on-the-sealed-envelope).

## Who it is for

A reviewer has been handed a report and asks: "can we trust this?" They don't want to redo the analysis. They want to know which claims the data backs, which it contradicts, and which it can't settle, with enough evidence to defend each call.

## What it does

1. **Load the report.** Paste it, upload a PDF, or use the practice report.
2. **Confirm the claims.** Check the sentences that will be tested and the ones skipped, each with a reason.
3. **Run the audit.** Each claim gets a verdict, the numbers with their calculation, source files and cohort trace, its limitation, and next actions. Clinical, individual-patient and personal-data requests are blocked before any analysis.
4. **Decide.** On each claim marked for review, accept the verdict, override it, or ask for more evidence.
5. **Download the results.** `audit.json` is the organizers' shared findings format v0.2. `review.json` holds the reviewer's decisions.

## What it does not do

- **No clinical claims.** No diagnosis, no treatment recommendation, no patient risk score. Such requests are blocked.
- **Nothing about one person.** Requests about individual patients, re-identification and personal details are blocked.
- **No guessing.** A claim it can't read gets "insufficient evidence" and a note on what data would be needed.
- **No hidden limits.** Every finding shows its limitation, and every number comes with its calculation and source file.

## Run

You need Git and Python 3.11. The server and engine use the standard library only. Two packages are optional: `pypdf` for PDF upload and `jsonschema` for the organizers' validator.

```bash
# 1. Get both repos side by side
mkdir hackathon && cd hackathon
git clone https://github.com/disleveK/oncosys-hackathon-challenge.git challenge-ref
git clone https://github.com/Blanq-one/Onco-reader.git onco-evidence

# 2. Download the TCGA-BRCA data (checked against frozen checksums)
cd challenge-ref && python3 data/tcga-brca/fetch.py && cd ../onco-evidence

# 3. Start the app, then open http://127.0.0.1:8000/app/
python3 server/serve.py
```

On Windows use `python` (or `py`) and backslashes. Every other step is in [docs/SETUP.md](docs/SETUP.md): making `audit.json`, the sealed-envelope run, the API, the fresh-clone check and the limits.

## Structure

| Path | What it is |
|---|---|
| `site/` | the intro project page (a copy of the OncoReader io page): hero, how it works, live sample audit, sound, motion and characters, with an "Open the app" button into `app/` |
| `app/` | the front end: `index.html`, `css/app.css` (all colours and fonts are tokens at the top), `js/` (state, pages, review rules) and `samples/` |
| `server/serve.py` | local server: the app at `/app/` and the JSON API at `/api/` |
| `src/engine/` | evidence engine: claims in, checked findings out |
| `src/data/` | TCGA-BRCA loader and checksum checks |
| `src/guardrails/` | pre-check on every claim, post-check on every findings document |
| `src/export/` | `audit.json` exporter and `review.json` |
| `contract/` | the findings shape, its validator, demo and mock reports |
| `scripts/` | `make_audit.py`, `fresh_clone_check.py`, `run_checks.py` and other checks |
| `tests/` | unit tests and the guardrail edge-case bank |
| `out/` | generated findings and the files the example report loads |
| `docs/` | `SETUP.md`, briefs and task prompts |

Raw TCGA files are never committed. They stay in `../challenge-ref`, which this project only reads.

## Options

`python3 server/serve.py` serves the app at `/app/`, the intro page at `/site/` and the API at `/api/`. It takes:
- `--data-dir PATH`: the data folder (default `$TCGA_DATA_DIR`, else `../challenge-ref/data/tcga-brca`);
- `--port 8001`: use this if port 8000 is busy;
- `--host`: default `127.0.0.1`, this computer only;
- `--split-subclaims`: one finding per part of a multi-part sentence in the `audit.json` download.

At start-up it prints whether the data passed its checksums, whether the guardrails loaded and whether PDF upload is on. If the guardrails are missing, it refuses to start.

## Look

The app uses the same paper look as the OncoReader page: a warm sheet, an ink serif (Bookerly if installed, then Charter, then Georgia), mono labels and stamp-style verdict tags. No font files are bundled.
- The first visit follows the system setting (light if the browser does not say). The toggle in the top bar overrides it, and the choice is kept in this browser.
- Every colour comes from the tokens at the top of `app/css/app.css`. Verdict colours (supported, contradicted, insufficient evidence, blocked) stay distinct in both themes, and every text pair is at least 4.5:1.
- The app itself has no sound and no background effects. Motion is a short page fade and stops when the system asks for reduced motion. The intro page in `site/` keeps the full io experience: sound, motion and effects, each with a button to turn it off.

To view the intro page, start the server (`python3 server/serve.py`) and open http://127.0.0.1:8000/site/. The "Open the app" button goes to `/app/` on the same server, so audits are live. Without the server (for example on a static host) the app opens only the saved example report.

## Checks

```bash
python3 -m unittest discover -s tests -v     # 209 tests
python3 scripts/run_checks.py                # tests, contract, guardrail bank, repo hygiene
python3 scripts/fresh_clone_check.py . --data-dir ../challenge-ref/data/tcga-brca
```

The tests that need pandas or Node.js skip without them.

## Limits

- **Local only.** The server listens on 127.0.0.1, has no login and is not meant for a shared network. It never logs claim text or request bodies.
- **One data release.** Results describe the frozen TCGA-BRCA release from `challenge-ref`. If a file does not match its checksum, every limitation says so.
- **Claims it reads:** coverage and overlap of data layers, counts and group sizes, sample and slide counts, ranges, fractions and ratios, how often a named gene is mutated, survival events, and "large enough for" questions. Anything else is "insufficient evidence". The full list is at the top of `src/engine/engine.py`.
- **Reports and PDFs:** up to 50 claims and 2000 characters per claim per request. PDFs up to 5 MB with real text, no OCR for scans.
- **`audit.json` holds the machine verdicts only.** Reviewer decisions go to `review.json`.

More in [docs/SETUP.md](docs/SETUP.md#limits).

## Team

- _Name_: _role_
- _Name_: _role_
- _Name_: _role_

## Licenses

Our code uses the Python standard library only, and the front end uses no third-party libraries. Optional: `pypdf` (BSD-3-Clause), `jsonschema` (MIT), `pandas` and Node.js for tests only. Data is TCGA-BRCA from the UCSC Xena hub and the TCGA Pan-Cancer Clinical Data Resource, fetched by the organizers' script and never committed. Terms are in `challenge-ref/DATA_LICENSES.md`.
