r"""Make audit.json (shared findings format v0.2) from a report: the Research Claim Auditor export.

Run from the repo root:
    python scripts/make_audit.py ..\challenge-ref\products\research-claim-auditor\practice_brief.md
    python scripts/make_audit.py REPORT --data-dir ..\challenge-ref\data\tcga-brca --out out\audit.json

What it does:
  1. Extracts the checkable claims from the report (engine extract_claims).
  2. Runs the evidence engine on them (engine Context + audit), with the
     guardrails pre-check on every claim and the post-check on the result.
  3. Writes out/audit.json: one claim_check finding per claim, with the release
     name and the file checksums from the data folder's sources.csv.
  4. Writes out/review.json: the human review queue. The shared format has no
     place for a reviewer to accept or override a claim verdict, so reviews
     live there. Pass --decisions with the app's saved decisions to fill it.
Check the result with: python ..\challenge-ref\format\validate.py out\audit.json

Exit codes: 0 written; 2 bad input or setup; 3 the guardrails post-check refused
the output (nothing is written, and no claim text is printed).
Standard library only.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.engine import engine as E  # noqa: E402
from src.export import audit_json as AJ  # noqa: E402

DEFAULT_DATA = os.environ.get("TCGA_DATA_DIR") or os.path.join(ROOT, "..", "challenge-ref", "data", "tcga-brca")
DEFAULT_OUT = os.path.join(ROOT, "out", "audit.json")
# Post-check problems are fixed text, but quoted values in them (step names, flags)
# can echo words from a claim, so every quoted part is withheld before printing.
QUOTED = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")


def safe_problem(problem):
    return QUOTED.sub("[withheld]", str(problem))[:300]


def fail(msg, code=2):
    print(msg, file=sys.stderr)
    return code


def main(argv=None):
    ap = argparse.ArgumentParser(description="Make audit.json (shared findings format v0.2) from a report")
    ap.add_argument("report", help="the report to audit (Markdown or text)")
    ap.add_argument("--data-dir", default=DEFAULT_DATA, help="folder with raw/, sample_manifest.csv and sources.csv")
    ap.add_argument("--out", default=DEFAULT_OUT, help="where to write audit.json (default: out/audit.json)")
    ap.add_argument("--review-out", help="where to write review.json (default: next to --out)")
    ap.add_argument("--decisions", help="JSON of reviewer decisions keyed by finding id (the app's saved decisions)")
    ap.add_argument("--release-name", default=AJ.DEFAULT_RELEASE, help="release name in audit.json (default: raw)")
    ap.add_argument("--team", default=AJ.DEFAULT_TEAM, help="producer.team in audit.json")
    ap.add_argument("--question", help="the question asked (default: built from the report name)")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # never crash on characters the console cannot show
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    if E._check_claim is None:
        return fail("src/guardrails is missing or failed to import; audit.json is never made without it.")
    if not hasattr(E, "extract_claims"):
        return fail("This engine has no extract_claims; make_audit.py needs engine v1.2.0 or later.")
    if not os.path.isfile(args.report):
        return fail(f"report not found: {os.path.abspath(args.report)}")
    data_dir = os.path.abspath(args.data_dir)
    if not os.path.isdir(data_dir):
        return fail(f"data folder not found: {data_dir}")
    try:
        files = AJ.read_sources(data_dir)
    except (OSError, ValueError) as err:
        return fail(f"cannot read the release checksums: {err}")
    decisions = None
    if args.decisions:
        try:
            with open(args.decisions, encoding="utf-8") as fh:
                decisions = json.load(fh)
        except (OSError, ValueError) as err:
            return fail(f"cannot read --decisions: {err.__class__.__name__}")

    with open(args.report, encoding="utf-8") as fh:
        claims, skipped = E.extract_claims(fh.read())
    title = os.path.basename(args.report)
    if not claims:
        print("WARNING: no checkable claims were found in the report; audit.json will have no findings.", file=sys.stderr)
    ctx = E.Context(data_dir)
    try:
        doc = E.audit(ctx, claims, title, skipped)
    except E.PostCheckError as err:
        print("Refusing to write audit.json: the guardrails post-check found "
              f"{len(err.problems)} problem(s) (quoted values withheld).", file=sys.stderr)
        for problem in err.problems:
            print("  -", safe_problem(problem), file=sys.stderr)
        return 3

    out = os.path.abspath(args.out)
    review_out = os.path.abspath(args.review_out) if args.review_out else os.path.join(os.path.dirname(out), "review.json")
    try:
        audit = AJ.build_audit(doc, files, release=args.release_name, team=args.team, question=args.question)
        review = AJ.build_review(doc, decisions, audit_file=os.path.basename(out))
    except ValueError as err:
        return fail(f"cannot export: {err}")
    AJ.write_json(audit, out)
    AJ.write_json(review, review_out)

    status = ctx.checksums["status"]
    print(f"\nGuardrails: {E.GUARDRAILS_SOURCE}   Checksums: {status}   Release: {args.release_name}\n")
    if status != "verified":
        print("WARNING: the data files did not all match sources.csv; every limitation in audit.json says so.", file=sys.stderr)
    for f in audit["findings"]:
        extra = f"  correct value: {f['correct_value']}" if "correct_value" in f else ""
        review_flag = "yes" if f["needs_human_review"] else "no"
        print(f"{f['id']}  {f['claim_verdict']:<22} review={review_flag:<4}{extra}")
    counts = ", ".join(f"{k} {v}" for k, v in review["counts"].items() if v)
    print(f"\nSaved {out}  ({len(audit['findings'])} claim_check findings)")
    print(f"Saved {review_out}  (review queue: {counts or 'empty'})")
    try:
        shown = os.path.relpath(out).replace(os.sep, "/")
    except ValueError:  # Windows: output on another drive
        shown = out
    print("Check it with: python ../challenge-ref/format/validate.py " + shown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
