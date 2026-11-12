# Onco Evidence (Evidence Navigator, Track 2)

Turns claims about TCGA-BRCA into checked findings: verdict, evidence, limitation, next actions.

## Quickstart (from a fresh clone)
1. Clone the organizers' repo next to this one and download the data:
   git clone https://github.com/disleveK/oncosys-hackathon-challenge.git challenge-ref
   cd challenge-ref && pip install -r requirements.txt && python data/tcga-brca/fetch.py && cd ..
2. Run the engine from this folder:
   python src/engine/engine.py --data-dir ../challenge-ref/data/tcga-brca --report contract/mock_report.md --out out/findings.json
3. Output: out/findings.json (shape described in contract/README.md).

Raw TCGA data is never committed. No clinical claims: this tool checks data readiness only.
