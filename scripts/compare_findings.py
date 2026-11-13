r"""Compare two findings files claim by claim: verdict, value and flags.

    python scripts/compare_findings.py before.json after.json

Claims are matched by claim_text. Prints every claim whose verdict, value or
guardrail flags changed, then a one-line summary. Exit code 0 either way;
this is a report, not a test. Standard library only.
"""
import json
import sys


def load(path):
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return doc, {f["claim_text"]: f for f in doc.get("findings", [])}


def brief(f):
    if f is None:
        return "(missing)"
    v = f["evidence"].get("value")
    return f"{f['verdict']} value={v} flags={f['guardrail_flags']} review={f['needs_human_review']}"


def compare(before_path, after_path):
    bdoc, before = load(before_path)
    adoc, after = load(after_path)
    print(f"before: {before_path}  (guardrails: {bdoc.get('guardrails_source', '?')})")
    print(f"after:  {after_path}  (guardrails: {adoc.get('guardrails_source', '?')})\n")
    changed = 0
    for text in list(before) + [t for t in after if t not in before]:
        b, a = before.get(text), after.get(text)
        same = b and a and all((b[k] == a[k]) for k in ("verdict", "guardrail_flags", "needs_human_review")) \
            and b["evidence"].get("value") == a["evidence"].get("value")
        if same:
            continue
        changed += 1
        print(f"CHANGED  {text[:100]}")
        print(f"   before {brief(b)}")
        print(f"   after  {brief(a)}")
    print(f"\n{changed} of {len(set(before) | set(after))} claims changed")
    return changed


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    compare(sys.argv[1], sys.argv[2])
