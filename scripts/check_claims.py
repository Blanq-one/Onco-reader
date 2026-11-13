r"""Show what the guardrail pre-check decides for claims, and why.

    python scripts/check_claims.py "Drug X improves survival." "RNA data is available for most samples."
    python scripts/check_claims.py --report contract/demo_report.md
    python scripts/check_claims.py --bank            # tests/edge_cases.csv: print only rows that misbehave
    python scripts/check_claims.py --explain "..."   # also show which rule fired on which words

Matched text from PHI rules is always masked. Standard library only.
"""
import argparse
import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from guardrails import check_claim, explain  # noqa: E402

BANK = os.path.join(ROOT, "tests", "edge_cases.csv")


def split_claims(text):
    """Same splitting as the engine: numbered or bulleted lines, else sentences."""
    items = [m.group(1) for m in (re.match(r"^\s*(?:\d+[.)]|[-*•])\s+(.*\S)\s*$", l) for l in text.splitlines()) if m]
    if items:
        return items
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip() and not s.lstrip().startswith("#")]


def show(claim, with_explain):
    r = check_claim(claim)
    tag = "ALLOW" if r["allowed"] else "BLOCK"
    print(f"{tag}  {claim[:100]}")
    if not r["allowed"]:
        print(f"       flags: {', '.join(r['flags'])}")
        print(f"       reason: {r['reason']}")
    if with_explain:
        for hit in explain(claim):
            print(f"       rule {hit['rule']} ({hit['flag']}) matched: {hit['matched']!r}")
    return r


def run_bank():
    bad = 0
    with open(BANK, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        if row["expected_action"] == "engine_refuses":
            continue
        r = check_claim(row["claim_text"])
        ok = r["allowed"] if row["expected_action"] == "allow" else (not r["allowed"] and row["expected_flag"] in r["flags"])
        if not ok:
            bad += 1
            print(f"MISMATCH {row['id']} expected {row['expected_action']} {row['expected_flag']}: got {r['flags'] or 'allowed'}")
            print(f"         {row['claim_text'][:100]}")
            for hit in explain(row["claim_text"]):
                print(f"         rule {hit['rule']} matched: {hit['matched']!r}")
    checked = sum(r["expected_action"] != "engine_refuses" for r in rows)
    print(f"{checked - bad} of {checked} bank rows behave as expected")
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("claims", nargs="*")
    ap.add_argument("--report", help="a text or markdown report; claims are split like the engine does")
    ap.add_argument("--bank", action="store_true", help="check tests/edge_cases.csv and list mismatches")
    ap.add_argument("--explain", action="store_true", help="show which rule fired and on which words")
    args = ap.parse_args(argv)
    if args.bank:
        return run_bank()
    claims = list(args.claims)
    if args.report:
        with open(args.report, encoding="utf-8") as fh:
            claims += split_claims(fh.read())
    if not claims:
        ap.error("give claims, --report FILE or --bank")
    results = [show(c, args.explain) for c in claims]
    print(f"\n{sum(not r['allowed'] for r in results)} of {len(results)} blocked")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # never crash printing a claim on a cp1252 console
    sys.exit(main())
