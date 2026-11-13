# Project rules (read first)

Evidence Navigator for TCGA-BRCA (hackathon Track 2). It takes claims about the
data and returns checked findings: verdict, evidence, limitation, next actions.

## Hard rules
- No clinical claims. No diagnosis, no treatment recommendation, no patient risk
  scores. This tool checks data readiness only.
- Never commit raw TCGA files, API keys, .env files, or private URLs. Raw data
  lives in ../challenge-ref (read only).
- Never use overclaiming words in any user-facing text: production-ready,
  clinically validated, clinical-grade, or any HIPAA or FDA claim.
- Every number shown must trace to its calculation and source file. The
  findings JSON carries both.
- Show the limitation on every finding. Never hide it.

## Layout and ownership
- src/data and src/engine: data loader and evidence engine. Do not edit unless
  your task says so.
- contract/: the findings shape (README.md, validate_findings.py,
  mock_findings.json, demo_report.md). Source of truth. Do not rename fields.
- app/: frontend. src/guardrails/ and tests/: guardrails and tests.
  server/: local server. scripts/: helper scripts. docs/: briefs and prompts.
- Stay inside the folders your task names. If you need a change somewhere else,
  say so in your final report instead of making it.

## Commands
- Run the engine:
  python src/engine/engine.py --data-dir ../challenge-ref/data/tcga-brca --report contract/demo_report.md --out out/findings.json --notes
- Run tests: python -m unittest discover -s tests -v
- Validate a findings file: python contract/validate_findings.py out/findings.json

## Style
- Python standard library only. Do not add dependencies.
- Frontend: no build step, no CDN, works offline.
- Plain punctuation in user-facing text (avoid em dashes).
- Small commits on your own branch. Never push to main.
