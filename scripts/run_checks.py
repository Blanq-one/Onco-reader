r"""Run every check in one command (the team's "make check").

    python scripts/run_checks.py
    python scripts/run_checks.py --data-dir ..\challenge-ref\data\tcga-brca

1. All unit tests:            python -m unittest discover -s tests
2. Repo hygiene:              python scripts/scan_repo.py
3. Guardrail bank:            python scripts/check_claims.py --bank
4. Engine on the demo report: findings into a temp file, then the contract
   validator and the guardrails post-check on every finding. Skipped if the
   data folder is missing.

Prints PASS/FAIL per step and exits non-zero if any step failed. Never writes
into out/. Standard library only.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA = os.environ.get("TCGA_DATA_DIR") or os.path.join("..", "challenge-ref", "data", "tcga-brca")


def step(name, cmd, **kw):
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"), **kw)
    ok = proc.returncode == 0
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print("      " + "\n      ".join((proc.stdout + proc.stderr).strip().splitlines()[-25:]))
    return ok, proc


def engine_demo(data_dir):
    if not os.path.isfile(os.path.join(data_dir, "raw", "clinical.tsv")):
        print(f"SKIP  engine on contract/demo_report.md (no data at {data_dir})")
        return True
    sys.path.insert(0, os.path.join(ROOT, "src"))
    import guardrails as G
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "findings.json")
        ok, proc = step("engine runs on contract/demo_report.md",
                        [sys.executable, os.path.join("src", "engine", "engine.py"), "--data-dir", data_dir,
                         "--report", os.path.join("contract", "demo_report.md"), "--out", out, "--notes"], timeout=900)
        if not ok:
            return False
        header_ok = "Guardrails: src/guardrails" in proc.stdout
        print(f"{'PASS' if header_ok else 'FAIL'}  engine header says 'Guardrails: src/guardrails'")
        with open(out, encoding="utf-8") as fh:
            problems = G.check_document(json.load(fh))
    print(f"{'PASS' if not problems else 'FAIL'}  contract validator and post-check on every demo finding")
    for p in problems:
        print("      " + p)
    return header_ok and not problems


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run every check")
    ap.add_argument("--data-dir", default=DEFAULT_DATA)
    args = ap.parse_args(argv)
    data_dir = args.data_dir if os.path.isabs(args.data_dir) else os.path.join(ROOT, args.data_dir)
    results = [
        step("unit tests (python -m unittest discover -s tests)",
             [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
             timeout=1800)[0],
        step("repo hygiene (scripts/scan_repo.py)", [sys.executable, os.path.join("scripts", "scan_repo.py")])[0],
        step("guardrail bank (scripts/check_claims.py --bank)",
             [sys.executable, os.path.join("scripts", "check_claims.py"), "--bank"])[0],
        engine_demo(os.path.abspath(data_dir)),
    ]
    print("\nALL CHECKS PASSED" if all(results) else "\nSOME CHECKS FAILED")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
