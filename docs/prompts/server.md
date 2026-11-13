# Task: local server, README, fresh-clone check (folders: server/, scripts/, README.md)

Read first: CLAUDE.md, README.md, src/engine/engine.py (public pieces: Context,
audit, split_claims), contract/README.md.

## Build
1. server/serve.py, Python standard library only.
   - Serves the repo root as static files, so the frontend at /app/ works, but
     never serves .git, .env, data, raw files or anything outside the repo
     (block path traversal and hidden files).
   - POST /api/audit. Body: {"claims": ["..."]} or {"report": "text"}. It
     builds the claim list (split_claims for a report), runs the engine's audit
     with a Context created once at startup, and returns the same JSON shape as
     out/findings.json. GET /api/health returns {"ok": true, "release": ...}.
   - Limits: request body 100 KB, at most 50 claims, 2000 characters each;
     return {"error": "..."} with 400 or 413 when exceeded. Wrap audit calls in
     a lock. Never crash on bad JSON.
   - Binds 127.0.0.1 only by default. Flags: --data-dir (default from env
     TCGA_DATA_DIR, else ../challenge-ref/data/tcga-brca), --port (default 8000),
     --host.
   - Prints clear startup messages, including the app URL and whether the data
     checks passed (checksum status).
2. README.md quickstart for a stranger on a fresh clone, copy-paste commands
   for Windows PowerShell and for Mac/Linux: clone the organizers' repo next to
   this one and fetch the data, run the engine, start the server, open the app.
   Add a short "What this tool does and does not do" section (data readiness
   only, no clinical claims) and a project layout section.
3. scripts/fresh_clone_check.py: clones this repo (path or URL as an argument)
   into a temp folder, runs the unit tests, runs the engine on
   contract/demo_report.md against --data-dir, validates the output with
   contract/validate_findings.py, starts server/serve.py on a free port, checks
   /api/health, /app/ (when it exists) and one POST /api/audit, then prints
   PASS or FAIL per step and exits nonzero on failure.
4. Keep the README commands true: run each one yourself once.

## Rules
- Edit only server/, scripts/, README.md. Do not edit the engine, contract,
  tests or app.
- Standard library only.

## Final report (short)
What works, the exact commands to run it, any problem you found in the engine.
