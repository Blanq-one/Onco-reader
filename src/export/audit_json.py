r"""Export the engine's findings document as audit.json in the organizers' shared format (v0.2).

Plain English: src/engine/engine.py audit() writes findings in our own contract
shape (contract/README.md). The organizers' checker reads a different, shared
shape (challenge-ref/format/findings.schema.json). This module converts one into
the other: one finding per claim with kind "claim_check", the claim as written,
its verdict, the correct value for contradicted claims, evidence pointers that
carry the calculation, the limitation and the human review flag.

Field map (ours -> shared format):
  id                        -> id
  source_sentence           -> claim_text (the schema wants the claim exactly as
                               written in the report; falls back to claim_text)
  claim_text                -> note on the "claim" evidence pointer ("Checked as: ...")
  verdict                   -> claim_verdict, and severity (see SEVERITY)
  correct_value.text        -> correct_value (contradicted claims only)
  missing_evidence          -> summary ("Data needed: ...") and a "release" pointer note
  evidence.calculation      -> note on an "analysis" pointer, with metric, value, n and denominator
  evidence.sub_checks       -> one "claim" pointer per part of the sentence
  evidence.source_files     -> "file" pointers tagged with the release name
  cohort_trace, robustness  -> notes on "analysis" pointers
  guardrail_flags           -> note on an "analysis" pointer (guardrail_check)
  review_reason             -> note on an "analysis" pointer (human_review)
  limitation                -> limitation (plus a warning if checksums were not verified)
  needs_human_review        -> needs_human_review, and confidence (see confidence_for)
Not carried, because the schema has no place for them: next_actions,
data_notes, interpretation_config, skipped_sentences.

Reviews: the schema's decisions[] point at repairs (repair_id), not at
findings, so a reviewer accepting or overriding a claim verdict has no place in
audit.json. build_review() writes those to a separate review.json instead.
audit.json always holds the machine verdicts unchanged.

Standard library only.
"""
import csv
import json
import os
import re
from collections import OrderedDict

# One finding per sentence (False, the default), or one finding per part of a sentence (True).
# The engine checks a sentence with several claims in it ("Luminal A is the largest subtype, about 62% of
# tumors") part by part and gives the sentence the worst verdict, with the parts in evidence.sub_checks.
# If the organizers' answer key lists each part as its own claim, set this to True: every part becomes its
# own claim_check finding (id "claim-002.1", "claim-002.2", ...) with its own claim_text, verdict and
# correct_value, and the sentence-level finding is not emitted for that sentence. Sentences with one part
# are exported the same way either way. See "If the answer key splits sentences" in README.md.
SPLIT_SUBCLAIMS = False

FORMAT_VERSION = "0.2"
DATASET = "TCGA-BRCA"
DEFAULT_RELEASE = "raw"  # the organizers' reference output names the fetch.py release "raw"
DEFAULT_TEAM = "onco-evidence"
PRODUCT = "Research Claim Auditor"
TRACK = "evidence-navigator"
VERDICTS = ("supported", "contradicted", "insufficient_evidence")
VERDICT_LABEL = {"supported": "supported", "contradicted": "contradicted", "insufficient_evidence": "insufficient evidence"}
# A wrong number in a report is the most serious outcome; an unanswerable claim
# still needs attention; a supported claim has nothing wrong with it.
SEVERITY = {"contradicted": "high", "insufficient_evidence": "medium", "supported": "none"}
SHARE_PREFIXES = ("coverage_", "overlap_", "share_")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
FILE_WITH_NOTE = re.compile(r"^(\S+)\s*\((.+)\)\s*$")  # "sample_manifest.csv (slides_for_sample)"

# review.json: the app's approve / reject / ask-for-more buttons (app/js/state.js)
REVIEW_DECISIONS = ("approve", "reject", "more")
REVIEW_STATUSES = ("pending", "accepted", "overridden", "more_evidence_requested")
# A finding stopped by one of these guardrail flags was never computed, so there is no
# result a reviewer could override. Same set as src/guardrails BLOCKING_FLAGS (a test
# keeps them equal) and as BLOCKED in app/js/state.js.
BLOCKING_FLAGS = frozenset({
    "clinical_claim_blocked", "individual_level_request_blocked", "reidentification_blocked",
    "phi_like_input", "prompt_injection_suspected", "invalid_input",
})
# Fixed text: it never includes claim text or a reviewer's note. Same words as the app.
BLOCKED_OVERRIDE_ERROR = ("a blocked claim cannot be overridden; "
                          "accept it as insufficient evidence or ask for more evidence")
BLOCKED_ACCEPT_VERDICT = "insufficient_evidence"


def is_blocked(f):
    return bool(set(f.get("guardrail_flags") or []) & BLOCKING_FLAGS)


# ---------- release files ----------
def read_sources(data_dir):
    """File names and SHA-256 checksums from the release's sources.csv, in file order."""
    path = os.path.join(data_dir, "sources.csv")
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = {"file", "sha256"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"sources.csv has no {sorted(missing)} column")
        files = []
        for row in reader:
            name = (row.get("file") or "").strip()
            digest = (row.get("sha256") or "").strip().lower()
            if not name:
                continue
            if not HEX64.match(digest):
                raise ValueError(f"sources.csv: {name} has no valid SHA-256 checksum")
            files.append(OrderedDict([("file", name), ("sha256", digest)]))
    if not files:
        raise ValueError("sources.csv lists no files")
    return files


# ---------- small text helpers ----------
def _sentence(text):
    text = str(text).strip()
    return text if not text or text.endswith((".", "!", "?")) else text + "."


def _is_share(metric, value, n, den):
    if metric:
        return str(metric).startswith(SHARE_PREFIXES)
    return isinstance(value, float) and bool(den) and n is not None and abs(value - n / den) < 1e-4


def headline(value, n, den, metric=None):
    """The measured figure in words, e.g. '49.9% (421 of 844)' or '535 of 1101'. None when nothing was computed."""
    if value is None or isinstance(value, bool):
        return None
    if metric and str(metric).startswith("ratio_"):  # engine v1.3 ratio claims: value is the ratio, n is the first group
        return f"{value:.2f} to 1 ({n} of {den} in the two groups are in the first)"
    if _is_share(metric, value, n, den):
        return f"{value * 100:.1f}% ({n} of {den})"
    if isinstance(value, int) and n == den == value:
        return str(value)
    if n is None or den is None:
        return str(value)
    return f"{n} of {den}"


def correct_value_text(f):
    """Our correct_value.text, or the measured headline if an older engine left it out."""
    cv = f.get("correct_value")
    if isinstance(cv, dict) and str(cv.get("text") or "").strip():
        return str(cv["text"]).strip()
    if isinstance(cv, str) and cv.strip():
        return cv.strip()
    ev = f.get("evidence") or {}
    return headline(ev.get("value"), ev.get("n_samples"), ev.get("denominator"), ev.get("metric_name"))


def missing_evidence_text(f):
    """What data would be needed to check an insufficient_evidence claim."""
    for key in ("missing_evidence", "review_reason"):
        text = str(f.get(key) or "").strip()
        if text:
            return text
    return "A data field or a measurable threshold that lets this claim be checked against the release."


def confidence_for(f):
    """high unless a person must review the finding (medium) or another reasonable reading flips the verdict (low)."""
    if (f.get("robustness") or {}).get("verdict_changes"):
        return "low"
    if f.get("needs_human_review"):
        return "medium"
    return "high"


# ---------- one finding ----------
def _ref(kind, ref_id, release=None, file=None, note=None):
    r = OrderedDict([("kind", kind), ("id", str(ref_id))])
    if release:
        r["release"] = release
    if file:
        r["file"] = file
    if note:
        r["note"] = str(note)
    return r


def _summary(f, verdict, ev):
    if verdict == "supported":
        h = headline(ev.get("value"), ev.get("n_samples"), ev.get("denominator"), ev.get("metric_name"))
        text = f"Supported. The data shows {h}." if h else "Supported by the data."
    elif verdict == "contradicted":
        cv = correct_value_text(f)
        text = f"Contradicted. The data shows {cv}." if cv else "Contradicted by the data."
    else:
        needed = missing_evidence_text(f)
        parts = ["Insufficient evidence."]
        reason = str(f.get("review_reason") or "").strip()
        if reason and reason != needed:
            parts.append(_sentence(reason))
        parts.append("Data needed: " + _sentence(needed))
        text = " ".join(parts)
    subs = ev.get("sub_checks") or []
    if len(subs) > 1:
        ok = sum(1 for p in subs if p.get("verdict") == "supported")
        text += f" Parts of the sentence supported: {ok} of {len(subs)}."
    return text


def _calculation_note(ev):
    calc = str(ev.get("calculation") or "").strip() or "No calculation was recorded."
    value = ev.get("value")
    if value is None:
        return calc
    metric = ev.get("metric_name") or "value"
    return f"{metric} = {value} ({ev.get('n_samples')} of {ev.get('denominator')} samples). {calc}"


def _trace_note(trace):
    steps = []
    for i, s in enumerate(trace):
        if i == 0 and s.get("n_before") == s.get("n_after"):
            steps.append(f"{s.get('step')}: {s.get('n_after')}")
        else:
            steps.append(f"{s.get('step')}: {s.get('n_before')} -> {s.get('n_after')}")
    return "Cohort, step by step: " + "; ".join(steps) + "."


def _evidence(f, ev, verdict, release, listed_files):
    fid = f["id"]
    checked = str(f.get("claim_text") or "").strip()
    written = str(f.get("source_sentence") or "").strip() or checked
    refs = [_ref("claim", fid, note="The claim as written in the report." if checked == written else f"Checked as: {checked}")]
    for i, part in enumerate(ev.get("sub_checks") or [], 1):
        h = headline(part.get("value"), part.get("n_samples"), part.get("denominator"))
        label = VERDICT_LABEL.get(part.get("verdict"), str(part.get("verdict")))
        refs.append(_ref("claim", f"{fid}.{i}", note=f"Part {i}: {part.get('claim')} Verdict: {label}" + (f"; measured {h}." if h else ".")))
    computed = ev.get("value") is not None
    refs.append(_ref("analysis", ev.get("metric_name") or "calculation", release=release if computed else None,
                     note=_calculation_note(ev)))
    trace = f.get("cohort_trace") or []
    if trace:
        refs.append(_ref("analysis", "cohort_trace", release=release, note=_trace_note(trace)))
    rob = f.get("robustness")
    if rob:
        refs.append(_ref("analysis", "robustness", release=release,
                         note=f"Alternative reading ({rob.get('alt_rule')}): value {rob.get('alt_value')}; "
                              f"verdict {'changes' if rob.get('verdict_changes') else 'does not change'}."))
    for entry in ev.get("source_files") or []:
        m = FILE_WITH_NOTE.match(str(entry))
        name, detail = (m.group(1), m.group(2)) if m else (str(entry), None)
        notes = [f"field used: {detail}"] if detail else []
        if name not in listed_files:
            notes.append("not listed in sources.csv")
        refs.append(_ref("file", name, release=release, file=name, note="; ".join(notes) or None))
    if verdict == "insufficient_evidence":
        refs.append(_ref("release", release, note="Data needed, not found in this release: " + _sentence(missing_evidence_text(f))))
    flags = f.get("guardrail_flags") or []
    if flags:
        refs.append(_ref("analysis", "guardrail_check", note="Guardrail flags: " + ", ".join(map(str, flags)) + "."))
    reason = str(f.get("review_reason") or "").strip()
    if f.get("needs_human_review") and reason:
        refs.append(_ref("analysis", "human_review", note="A person must check this before it is used: " + _sentence(reason)))
    return refs


def claim_check(f, release=DEFAULT_RELEASE, listed_files=(), checksum_note=None):
    """One engine finding -> one shared-format finding with kind 'claim_check'."""
    if not isinstance(f, dict) or not f.get("id"):
        raise ValueError("a finding has no id")
    verdict = f.get("verdict")
    if verdict not in VERDICTS:
        raise ValueError(f"{f['id']}: verdict {verdict!r} is not one of {list(VERDICTS)}")
    ev = f.get("evidence") or {}
    written = str(f.get("source_sentence") or "").strip() or str(f.get("claim_text") or "").strip()
    out = OrderedDict([("id", str(f["id"])), ("kind", "claim_check"), ("claim_text", written), ("claim_verdict", verdict)])
    if verdict == "contradicted":
        cv = correct_value_text(f)
        if cv:
            out["correct_value"] = cv
    out["summary"] = _summary(f, verdict, ev)
    out["severity"] = SEVERITY[verdict]
    out["confidence"] = confidence_for(f)
    out["needs_human_review"] = bool(f.get("needs_human_review"))
    limitation = str(f.get("limitation") or "").strip() or "No limitation was recorded for this finding; treat it with care."
    out["limitation"] = limitation + (" " + checksum_note if checksum_note else "")
    out["evidence"] = _evidence(f, ev, verdict, release, set(listed_files))
    return out


def part_checks(f, release=DEFAULT_RELEASE, listed_files=(), checksum_note=None):
    """SPLIT_SUBCLAIMS: one claim_check finding per part of a multi-part sentence, each with its own verdict.

    Each part is turned back into an engine-shaped finding and exported with claim_check(), so it gets the same
    summary, severity, confidence and evidence rules as a whole sentence. The part keeps the sentence's
    limitation; its claim_text is the part as the engine checked it, and an evidence pointer quotes the
    sentence as written in the report.
    """
    ev = f.get("evidence") or {}
    parts = ev.get("sub_checks") or []
    written = str(f.get("source_sentence") or f.get("claim_text") or "").strip()
    out = []
    for i, part in enumerate(parts, 1):
        verdict = part.get("verdict")
        has_own_review = "needs_human_review" in part
        pf = {
            "id": f"{f['id']}.{i}",
            "claim_text": str(part.get("claim") or "").strip(),
            "source_sentence": str(part.get("claim") or "").strip(),
            "verdict": verdict,
            "correct_value": {"text": part["correct_value"]} if part.get("correct_value") else None,
            "evidence": {"metric_name": part.get("metric_name") or ev.get("metric_name"), "value": part.get("value"),
                         "n_samples": part.get("n_samples"), "denominator": part.get("denominator"),
                         "calculation": part.get("calculation") or ev.get("calculation"),
                         "source_files": part.get("source_files") or ev.get("source_files") or []},
            "cohort_trace": [],
            "limitation": f.get("limitation"),
            "needs_human_review": bool(part.get("needs_human_review")) if has_own_review else bool(f.get("needs_human_review")),
            "review_reason": part.get("review_reason") if has_own_review else f.get("review_reason"),
            "guardrail_flags": part.get("guardrail_flags", f.get("guardrail_flags") or []),
            "robustness": None,
            "missing_evidence": f.get("missing_evidence") if verdict == "insufficient_evidence" else None,
        }
        cc = claim_check(pf, release, listed_files, checksum_note)
        cc["evidence"][0]["note"] = f"Part {i} of {len(parts)} of one sentence, as checked."
        cc["evidence"].insert(1, _ref("claim", f["id"], note="The whole sentence as written in the report: " + written))
        out.append(cc)
    return out


# ---------- whole document ----------
def checksum_warning(doc):
    """A sentence for every limitation when the engine could not confirm the frozen checksums, else None."""
    status = (doc.get("data_release") or {}).get("checksum_status") or "unknown"
    if status == "verified":
        return None
    return (f"The local data files were not confirmed against the frozen checksums in sources.csv "
            f"(checksum status: {status}), so these results may not describe the frozen release.")


def build_audit(doc, files, release=DEFAULT_RELEASE, team=DEFAULT_TEAM, question=None, allow_mock=False, split_subclaims=None):
    """The engine's findings document -> audit.json (shared format v0.2) as an ordered dict.

    split_subclaims: None follows the module switch SPLIT_SUBCLAIMS; True or False overrides it for this call.
    """
    split = SPLIT_SUBCLAIMS if split_subclaims is None else bool(split_subclaims)
    if not isinstance(doc, dict) or not isinstance(doc.get("findings"), list):
        raise ValueError("not a findings document (no findings list)")
    if doc.get("is_mock") and not allow_mock:
        raise ValueError("refusing to export mock findings: their numbers are invented")
    if not files:
        raise ValueError("no release files: pass the checksums from sources.csv")
    ids = [f.get("id") if isinstance(f, dict) else None for f in doc["findings"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate finding ids")
    warn = checksum_warning(doc)
    listed = [x["file"] for x in files]
    title = doc.get("report_title") or "the report"
    q = question or (f"Which claims in {title} does the TCGA-BRCA release '{release}' support, contradict, "
                     f"or leave without enough evidence?")
    out_findings = []
    for f in doc["findings"]:
        if split and len((f.get("evidence") or {}).get("sub_checks") or []) > 1:
            out_findings.extend(part_checks(f, release, listed, warn))
        else:
            out_findings.append(claim_check(f, release, listed, warn))
    out_ids = [x["id"] for x in out_findings]
    if len(out_ids) != len(set(out_ids)):
        raise ValueError("duplicate finding ids after splitting sentences into parts")
    return OrderedDict([
        ("format_version", FORMAT_VERSION),
        ("producer", OrderedDict([("team", team), ("product", PRODUCT), ("track", TRACK)])),
        ("data", OrderedDict([("dataset", DATASET),
                              ("releases", [OrderedDict([("name", release), ("files", [OrderedDict(x) for x in files])])])])),
        ("question", q),
        ("findings", out_findings),
    ])


# ---------- human review (kept outside audit.json) ----------
def build_review(doc, decisions=None, audit_file="audit.json"):
    """review.json: one item per claim, keeping the machine verdict and any human decision side by side.

    decisions is the app's saved review state (localStorage 'en.decisions'):
      {"claim-002": {"decision": "approve" | "reject" | "more", "note": "...", "at": "ISO time",
                     "verdict": optional replacement verdict, "reviewer_role": optional}}
    Decisions for ids that are not in this audit are ignored and listed under ignored_decision_ids.

    Blocked findings (any flag in BLOCKING_FLAGS) may only be accepted, which records them as
    insufficient evidence, or sent back with "more". A "reject" or any other human verdict on
    a blocked finding raises ValueError("<id>: " + BLOCKED_OVERRIDE_ERROR).
    """
    decisions = decisions or {}
    if not isinstance(decisions, dict):
        raise ValueError("decisions must be an object keyed by finding id")
    items, seen = [], set()
    for f in doc.get("findings") or []:
        fid, verdict = f.get("id"), f.get("verdict")
        d = decisions.get(fid) or {}
        if not isinstance(d, dict):
            raise ValueError(f"{fid}: a decision must be an object")
        choice, human = d.get("decision"), d.get("verdict")
        if choice is not None and choice not in REVIEW_DECISIONS:
            raise ValueError(f"{fid}: decision {choice!r} is not one of {list(REVIEW_DECISIONS)}")
        if human is not None and human not in VERDICTS:
            raise ValueError(f"{fid}: verdict {human!r} is not one of {list(VERDICTS)}")
        blocked = is_blocked(f)
        if blocked and (choice == "reject" or human not in (None, BLOCKED_ACCEPT_VERDICT)):
            raise ValueError(f"{fid}: {BLOCKED_OVERRIDE_ERROR}")
        if choice == "approve" and human is None:
            human = BLOCKED_ACCEPT_VERDICT if blocked else verdict
        if choice == "more":
            status = "more_evidence_requested"
        elif choice == "approve" and blocked:
            status = "accepted"  # accepted as insufficient evidence
        elif choice == "reject" or (human is not None and human != verdict):
            status = "overridden"
        elif choice == "approve":
            status = "accepted"
        else:
            status = "pending"
        seen.add(fid)
        items.append(OrderedDict([
            ("finding_id", fid),
            ("claim_text", str(f.get("source_sentence") or f.get("claim_text") or "")),
            ("machine_verdict", verdict),
            ("needs_human_review", bool(f.get("needs_human_review"))),
            ("review_reason", f.get("review_reason")),
            ("status", status),
            ("human_decision", choice),
            ("human_verdict", human),
            ("note", d.get("note") or None),
            ("reviewer_role", d.get("reviewer_role") or None),
            ("decided_at", d.get("at") or None),
        ]))
    counts = OrderedDict((s, sum(1 for i in items if i["status"] == s)) for s in REVIEW_STATUSES)
    review = OrderedDict([
        ("review_version", "1"),
        ("about", "Human review of the claim verdicts in " + audit_file + ". The shared findings format (v0.2) has no "
                  "place for a reviewer to accept or override a claim verdict, so reviews are kept here. "
                  "The machine verdicts in " + audit_file + " are never changed."),
        ("audit_file", audit_file),
        ("report_title", doc.get("report_title")),
        ("counts", counts),
        ("items", items),
    ])
    ignored = sorted(str(k) for k in decisions if k not in seen)
    if ignored:
        review["ignored_decision_ids"] = ignored
    return review


def write_json(obj, path):
    """Write JSON as ASCII (non-ASCII escaped) so any reader decodes it, whatever its default encoding."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=True)
        fh.write("\n")
