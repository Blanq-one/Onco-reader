r"""Evidence engine v1.2.1: turn report claims into checked findings (standard library only).

Plain English: for each claim in a report it (1) runs the guardrail pre-check,
(2) reads the claim as a small template, (3) computes the real numbers from the
TCGA-BRCA files, and (4) writes a finding in the contract shape with the
evidence, a limitation, next actions, and a robustness check.

Templates it understands:
  layer coverage    "RNA data is available for most samples"
  overlap           "Copy number and RNA can be joined for most samples"
  condition         "RNA is available for nearly all samples that have clinical records"
  count             "Fewer than 100 samples have both survival and mutation records"
  recorded          "ER status is recorded for most samples"
  group size/share  "At least 100 HER2-positive tumors" / "About 15 percent of tumors are HER2-positive"
  subgroup coverage "Protein data covers most triple-negative tumors"
  events            "At least 30 deaths among ER-negative tumors"
  readiness         "The cohort is large enough for a subtype comparison" (shows group sizes)
Layers: clinical, survival, mutation, copy number, RNA, protein, slides.
Clinical attributes: ER, PR, HER2, stage, histology, PAM50 subtype, gender.
Anything else is answered honestly as "insufficient evidence".

Run (from the repo root):
    python src/engine/engine.py --data-dir ..\challenge-ref\data\tcga-brca --report contract\mock_report.md --out out\findings.json
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "contract"))

from src.data import tcga_loader as L  # noqa: E402

_GUARD_ERROR = None
try:  # the real guardrails module
    from src.guardrails import check_claim as _check_claim  # type: ignore
    GUARDRAILS_SOURCE = "src/guardrails"
except Exception as _exc:  # pragma: no cover
    _check_claim = None
    _GUARD_ERROR = _exc
    GUARDRAILS_SOURCE = "MISSING"
try:
    from src.guardrails import redact as _redact  # type: ignore
except Exception:  # pragma: no cover
    _redact = None
try:  # the post-check that every finished document must pass before it is written or returned
    from src.guardrails.postcheck import check_document as _check_document  # type: ignore
except Exception:  # pragma: no cover
    try:
        from src.guardrails import check_document as _check_document  # type: ignore
    except Exception:
        _check_document = None


class PostCheckError(RuntimeError):
    """The finished findings document failed the guardrails post-check. .problems holds fixed-text strings, never claim text."""

    def __init__(self, problems):
        super().__init__("post-check found %d problem(s)" % len(problems))
        self.problems = list(problems)


ALLOW_FALLBACK = False  # set True only by --unsafe-no-guardrails (quick local tests, never for submission)

try:
    import validate_findings as VF  # contract/validate_findings.py
except Exception:  # pragma: no cover
    VF = None

# Every interpretation choice lives here so it can be shown and changed in one place.
CFG = {
    "most_threshold": 0.5,       # "most" / "majority" means more than 50 percent
    "nearly_all": 0.95,          # "nearly all" / "almost all" means at least 95 percent
    "about_tolerance": 0.03,     # "about N percent" means within 3 points of N
    "about_count_rel": 0.02,     # "about N samples" means within 2 percent of N (at least 1)
    "borderline_margin": 0.02,   # within 2 points of the threshold -> ask a person to review
    "min_population": 30,        # fewer samples than this is too thin to judge
    "min_events": 20,            # fewer OS events than this is too thin for survival comparisons
    "min_group_size": 30,        # smaller groups are flagged as thin
}

LAYER_WORDS = OrderedDict([
    ("copy_number", [r"copy[- ]?number", r"\bcnv\b", r"gistic"]),
    ("mutation", [r"mutation", r"mutated", r"\bvariants?\b"]),
    ("protein", [r"protein", r"rppa"]),
    ("survival", [r"survival"]),
    ("rna", [r"\brna\b", r"rna-?seq", r"gene expression", r"expression data", r"transcript"]),
    ("clinical", [r"clinical"]),
    ("slides", [r"\bslides?\b", r"pathology", r"histolog(?:y|ical) slides?"]),
])
LAYER_LABEL = {"copy_number": "copy number", "mutation": "mutation", "protein": "protein", "survival": "survival",
               "rna": "RNA", "clinical": "clinical", "slides": "pathology slides"}
LAYER_SOURCE = {name: spec["file"] for name, spec in L.LAYERS.items()}
LAYER_SOURCE["slides"] = "sample_manifest.csv (slides_for_sample)"

OTHER_DATASET_WORDS = r"\b(lung|colon|colorectal|kidney|prostate|ovarian|liver|brain|glioma|melanoma)\b"
POPULATION_WORDS = [("normal tissue", "11", "normal tissue samples"), ("metasta", "06", "metastasis samples")]

# ---- clinical attributes (candidate columns are tried and the best-populated one is used) ----
ATTR_SPECS = OrderedDict([
    ("er", {"label": "ER status", "kind": "status",
            "candidates": ["ER_Status_nature2012", "breast_carcinoma_estrogen_receptor_status"]}),
    ("pr", {"label": "PR status", "kind": "status",
            "candidates": ["PR_Status_nature2012", "breast_carcinoma_progesterone_receptor_status"]}),
    ("her2", {"label": "HER2 status", "kind": "status",
              "candidates": ["HER2_Final_Status_nature2012", "lab_proc_her2_neu_immunohistochemistry_receptor_status"]}),
    ("stage", {"label": "pathologic stage", "kind": "stage",
               "candidates": ["pathologic_stage", "AJCC_Stage_nature2012"]}),
    ("histology", {"label": "histological type", "kind": "text", "candidates": ["histological_type"]}),
    ("subtype", {"label": "PAM50 subtype", "kind": "text", "pattern": "pam50", "candidates": []}),
    ("gender", {"label": "gender", "kind": "text", "candidates": ["gender"]}),
])

BLOCK_ACTIONS = {
    "clinical_claim_blocked": ["Rewrite the claim as a data-availability question, such as how many samples have treatment records.",
                               "Send treatment-effect questions to qualified clinical researchers."],
    "individual_level_request_blocked": ["Rewrite the claim as a cohort-level question."],
    "reidentification_blocked": ["Remove any attempt to identify people or link to outside records."],
    "phi_like_input": ["Remove names, dates of birth, record numbers and contact details from the report."],
    "prompt_injection_suspected": ["Remove instructions aimed at the system from the report text."],
    "invalid_input": ["Provide a non-empty claim written as a sentence."],
}


# ---------- value normalisers ----------
def norm_status(v):
    v = (v or "").strip().lower()
    if not v or v.startswith("["):
        return None
    if v.startswith("pos"):
        return "positive"
    if v.startswith("neg"):
        return "negative"
    if v.startswith(("indeterminate", "equivocal", "borderline")):
        return "indeterminate"
    return None


def norm_stage(v):
    m = re.match(r"^\s*stage\s+(iv|iii|ii|i)[abc]?\s*$", (v or "").strip().lower())
    return m.group(1) if m else None


def norm_text(v):
    v = (v or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "", v) if v and not v.startswith("[") else None


NORMALISERS = {"status": norm_status, "stage": norm_stage, "text": norm_text}


# ---------- context ----------
SUBTYPE_NAMES = {"luma": "Luminal A", "lumb": "Luminal B", "basal": "Basal-like", "her2": "HER2-enriched", "normal": "Normal-like"}


class Context:
    def __init__(self, data_dir, overrides=None):
        self.data_dir = data_dir
        self.overrides = overrides or {}
        self.layers, self.missing = L.load_layers(data_dir)
        self.manifest = L.load_manifest(data_dir)
        if self.manifest:
            ids = [r["sample_id"] for r in self.manifest]
            slide_ids = []
            for r in self.manifest:
                try:
                    if float(r.get("slides_for_sample", 0) or 0) > 0:
                        slide_ids.append(r["sample_id"])
                except ValueError:
                    pass
            self.layers["slides"] = L.LayerIds(slide_ids, "sample")
        else:
            ids = sorted(set().union(*[l.ids for l in self.layers.values() if l.level == "sample"]))
        self.all_samples = sorted(ids)
        self.by_code = {}
        for s in self.all_samples:
            self.by_code.setdefault(L.sample_code(s), []).append(s)
        self.checksums = L.verify_checksums(data_dir)
        self.os = self._load_os()
        self.attrs, self.attr_notes = self._load_attributes()

    def population(self, code="01"):
        return self.by_code.get(code, [])

    # survival events (OS) keyed by sample id
    def _load_os(self):
        path = os.path.join(self.data_dir, "raw", "survival.tsv")
        out = {}
        if not os.path.exists(path):
            return out
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            if not reader.fieldnames or "OS" not in reader.fieldnames:
                return out
            idcol = "sample" if "sample" in reader.fieldnames else reader.fieldnames[0]
            for row in reader:
                v = (row.get("OS") or "").strip()
                if v in ("0", "1"):
                    out[row[idcol].strip()[:15]] = int(v)
        return out

    def os_event(self, sample_id):
        return self.os.get(sample_id)

    # clinical attributes: pick the best-populated candidate column for each
    def _load_attributes(self):
        path = os.path.join(self.data_dir, "raw", "clinical.tsv")
        attrs, notes = {}, []
        if not os.path.exists(path):
            return attrs, notes
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            header = reader.fieldnames or []
            idcol = "sampleID" if "sampleID" in header else header[0]
            rows = {r[idcol].strip()[:15]: r for r in reader}
        primary = [s for s in rows if L.is_primary(s)]
        for key, spec in ATTR_SPECS.items():
            cands = [c for c in spec["candidates"] if c in header]
            if spec.get("pattern"):
                cands += [h for h in header if spec["pattern"] in h.lower() and h not in cands]
            ov = self.overrides.get(key)
            if ov:
                if ov not in header:
                    sys.exit(f"--column {key}={ov}: no such column in clinical.tsv")
                if ov not in cands:
                    cands.append(ov)
            if not cands:
                continue
            norm = NORMALISERS[spec["kind"]]
            scored = []
            for c in cands:
                n = sum(1 for s in primary if norm(rows[s].get(c)) is not None)
                scored.append((n, -cands.index(c), c))
            scored.sort(reverse=True)
            if ov:
                best = ov
                best_n = next(n for n, _, c in scored if c == ov)
                others = [(n, i, c) for n, i, c in scored if c != ov]
            else:
                best_n, _, best = scored[0]
                others = scored[1:]
            display = {}
            for s, r in rows.items():
                v = norm(r.get(best))
                if v is not None and v not in display:
                    display[v] = (r.get(best) or "").strip()
            attrs[key] = {"column": best, "norm": norm, "display": display,
                          "values": {s: norm(r.get(best)) for s, r in rows.items()}}
            notes.append(OrderedDict([
                ("attribute", spec["label"]), ("column_used", best),
                ("chosen_by", "override" if ov else "most recorded values"),
                ("primary_tumors_with_recorded_value", best_n), ("primary_tumors", len(primary)),
                ("alternatives", [{"column": c, "primary_tumors_with_recorded_value": n} for n, _, c in others]),
            ]))
        return attrs, notes

    def display_name(self, key, value):
        if key == "subtype":
            return SUBTYPE_NAMES.get(value, self.attrs[key]["display"].get(value, value))
        if key == "stage":
            return "Stage " + value.upper()
        if key in ("er", "pr", "her2"):
            return value.capitalize()
        return self.attrs[key]["display"].get(value, value)

    def attr(self, key, sample_id):
        a = self.attrs.get(key)
        return a["values"].get(sample_id) if a else None


# ---------- reading claims ----------
def split_claims(text):
    items = []
    for line in text.splitlines():
        m = re.match(r"^\s*(?:\d+[.)]|[-*\u2022])\s+(.*\S)\s*$", line)
        if m:
            items.append(m.group(1))
    if items:
        return items
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if s.strip() and not s.lstrip().startswith("#")]


ABBREV = ["e.g.", "i.e.", "vs.", "etc.", "approx.", "fig.", "al.", "no.", "dr.", "mr.", "ms.", "st."]
RECOMMEND = re.compile(r"^(?:we|i|the authors?|authors?)\s+(?:recommend|suggest|propose|urge|advise|hope|believe|plan)\b|"
                       r"\bfuture (?:work|studies|research)\b|^(?:it would be|it may be|it might be)\b", re.I)
HEDGE_TAIL = re.compile(r",?\s*(?:which|that)\s+(?:suggests?|implies|indicates?|means|shows)\b.*$", re.I)
CLINICAL_WORDS = re.compile(r"\b(respond\w*|response|benefit\w*|efficacy|effective\w*|therapy|treatment\w*|drug\w*|"
                            r"chemotherap\w*|prognos\w*|surviv\w*|mortality|outcome\w*|improv\w*)\b", re.I)
QUANT_WORDS = re.compile(r"\b(most|majority|all|every|each|nearly|almost|about|around|approximately|roughly|over|under|"
                         r"more than|less than|fewer than|at least|at most|half|largest|smallest|most common|least common|"
                         r"rarest|most frequent|only|none|enough|sufficient)\b|\d", re.I)


def split_sentences(paragraph):
    t = paragraph
    for a in ABBREV:
        t = re.sub(re.escape(a), lambda m: m.group(0).replace(".", "<dot>"), t, flags=re.I)
    t = re.sub(r"(\d)\.(\d)", r"\1<dot>\2", t)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])", t)
    return [p.replace("<dot>", ".").strip() for p in parts if p.strip()]


def is_checkable(sentence):
    if RECOMMEND.search(sentence):
        return False, "a recommendation, not a factual claim"
    s = sentence
    mentions = (find_layers(s) or find_attr_mentions(s) or parse_filters(s)
                or re.search(r"\b(?:primary )?tumou?rs?\b|\bsamples?\b|\bpatients?\b|\bcases?\b", s, re.I))
    if CLINICAL_WORDS.search(s) and mentions:
        return True, ""
    if mentions and QUANT_WORDS.search(s):
        return True, ""
    return False, "no checkable number or data statement"


def extract_claims(text):
    """Return (claims, skipped). Numbered or bulleted lists are used as written; otherwise prose is split into sentences."""
    lines = text.splitlines()
    listed = []
    for line in lines:
        m = re.match(r"^\s*(?:\d+[.)]|[-*\u2022])\s+(.*\S)\s*$", line)
        if m:
            listed.append(m.group(1))
    if listed:
        return [{"text": c, "source": c} for c in listed], []
    claims, skipped, paragraphs, cur = [], [], [], []
    for line in lines:
        st = line.strip()
        if not st:
            if cur:
                paragraphs.append(" ".join(cur))
                cur = []
            continue
        if st.startswith("#"):
            continue
        if re.match(r"^\*[^*].*[^*]\*$", st) or re.match(r"^_[^_].*[^_]_$", st):
            skipped.append({"text": st, "reason": "an italic note, not a claim"})
            continue
        cur.append(st)
    if cur:
        paragraphs.append(" ".join(cur))
    for par in paragraphs:
        for sent in split_sentences(par):
            ok, why = is_checkable(sent)
            if not ok:
                skipped.append({"text": sent, "reason": why})
                continue
            claim = HEDGE_TAIL.sub("", sent).strip().rstrip(",")
            if not claim.endswith((".", "?", "!")):
                claim += "."
            claims.append({"text": claim, "source": sent})
    return claims, skipped


def normalize_claim_text(text):
    t = re.sub(r"\bm?RNA(?:[- ]?seq)?(?:[- ]based)?\s+(?:intrinsic\s+)?subtypes?(?:\s+calls?)?", "PAM50 subtype", text, flags=re.I)
    t = re.sub(r"\bPAM50\s+(?:subtype\s+)?calls?\b", "PAM50 subtype", t, flags=re.I)
    t = re.sub(r"\bsubtype calls?\b", "PAM50 subtype", t, flags=re.I)
    return t


def find_layers(text):
    low = text.lower()
    if re.search(r"\ball (?:five|5) (?:molecular |data )?layers?\b|\bfive (?:data |molecular )?layers\b", low):
        return ["survival", "mutation", "copy_number", "rna", "protein"]
    found = []
    for name, pats in LAYER_WORDS.items():
        pos = [m.start() for p in pats for m in re.finditer(p, low)]
        if pos:
            found.append((min(pos), name))
    return [n for _, n in sorted(found)]


ATTR_MENTION = OrderedDict([
    ("er", r"\ber\b|estrogen"),
    ("pr", r"\bpr\b|progesterone"),
    ("her2", r"\bher2\b(?![- ]enriched)"),
    ("stage", r"\bstag(?:e|es|ing)\b"),
    ("subtype", r"subtypes?|pam50|luminal|\bbasal"),
    ("histology", r"histolog(?!y slide)|\bductal\b|\blobular\b"),
    ("gender", r"\bgender\b|\bsex\b"),
])


def find_attr_mentions(text):
    low = text.lower()
    found = []
    for key, pat in ATTR_MENTION.items():
        m = re.search(pat, low)
        if m:
            found.append((m.start(), key))
    return [k for _, k in sorted(found)]


def _status_filter(attr, value, label):
    return {"attr": attr, "label": label, "test": lambda v, value=value: v == value}


def parse_filters(text):
    low = text.lower()
    filters = []
    seen = set()

    def add(f):
        key = (f["attr"], f["label"])
        if key not in seen:
            seen.add(key)
            filters.append(f)

    if re.search(r"triple[- ]negative|\btnbc\b", low):
        add(_status_filter("er", "negative", "ER-negative"))
        add(_status_filter("pr", "negative", "PR-negative"))
        add(_status_filter("her2", "negative", "HER2-negative"))
    val = r"(positive|negative|\+|-(?=\s|$|[.,;)]))"
    for attr, name, label in (("er", r"(?:\ber|estrogen[- ]receptor)", "ER"),
                              ("pr", r"(?:\bpr|progesterone[- ]receptor)", "PR"),
                              ("her2", r"\bher2(?![- ]enriched)", "HER2")):
        for m in re.finditer(name + r"(?:\s+status)?\s*[- ]?\s*" + val, low):
            v = "positive" if m.group(1) in ("positive", "+") else "negative"
            add(_status_filter(attr, v, f"{label}-{v}"))
    # stage
    m = re.search(r"\bstage\s+(iv|iii|ii|i|4|3|2|1)\b", low)
    if m:
        g = {"4": "iv", "3": "iii", "2": "ii", "1": "i"}.get(m.group(1), m.group(1))
        add({"attr": "stage", "label": f"stage {g.upper()}", "test": lambda v, g=g: v == g})
    elif re.search(r"\bearly[- ]stage\b", low):
        add({"attr": "stage", "label": "early stage (I-II)", "test": lambda v: v in ("i", "ii")})
    elif re.search(r"\b(?:late|advanced)[- ]stage\b", low):
        add({"attr": "stage", "label": "advanced stage (III-IV)", "test": lambda v: v in ("iii", "iv")})
    # histology
    for token in ("ductal", "lobular", "mucinous", "medullary", "metaplastic"):
        if re.search(rf"\b{token}\b", low):
            add({"attr": "histology", "label": token, "test": lambda v, t=token: v is not None and t in v})
    # PAM50 subtype
    for pat, token, label in ((r"luminal a\b|\blum ?a\b|\bluma\b", "luma", "Luminal A"),
                              (r"luminal b\b|\blum ?b\b|\blumb\b", "lumb", "Luminal B"),
                              (r"her2[- ]enriched", "her2", "HER2-enriched"),
                              (r"\bbasal(?:[- ]like)?\b", "basal", "Basal-like"),
                              (r"normal[- ]like", "normal", "Normal-like")):
        if re.search(pat, low):
            add({"attr": "subtype", "label": label, "test": lambda v, t=token: v is not None and t in v})
    # gender
    if re.search(r"\bfemales?\b", low):
        add({"attr": "gender", "label": "female", "test": lambda v: v == "female"})
    elif re.search(r"\bmales?\b", low):
        add({"attr": "gender", "label": "male", "test": lambda v: v == "male"})
    return filters


NUM = r"(\d[\d,]*(?:\.\d+)?)"
NOUNS = r"(samples?|patients?|tumou?rs?|cases?|deaths?|events?)"


def parse_quantifier(text):
    """Return dict(kind, comparator, threshold, reading) or None. May return kind 'invalid'."""
    low = text.lower().replace("\u2019", "'")
    if re.search(r"(?:^|[\s(])[-\u2212]\s*\d[\d,]*(?:\.\d+)?\s*(?:%|percent|samples?|patients?|tumou?rs?|cases?|deaths?|events?)", low):
        return {"kind": "invalid", "reading": "a negative number cannot describe a count or a share"}
    m = re.search(r"\b(fewer than|less than|under|below|more than|over|above|at least|at most|up to|exactly)\s+" + NUM +
                  r"(?!\d)(?!\s*(?:%|percent|per cent))(?:\s+(?:[\w+\-]+\s+){0,3}?" + NOUNS + r"\b)?", low)
    if m:
        word, n = m.group(1), float(m.group(2).replace(",", ""))
        comp = {"fewer than": "<", "less than": "<", "under": "<", "below": "<", "more than": ">", "over": ">",
                "above": ">", "at least": ">=", "at most": "<=", "up to": "<=", "exactly": "=="}[word]
        noun = m.group(3) or "samples"
        return {"kind": "count", "comparator": comp, "threshold": n, "noun": noun,
                "reading": f"'{word} {int(n)}' {noun}"}
    m = re.search(r"\b(fewer than|less than|under|below|more than|over|above|at least|at most|about|around|approximately|"
                  r"roughly|nearly|almost)?\s*" + NUM + r"\s*(?:%|percent|per cent)", low)
    if m:
        word, pct = (m.group(1) or "about"), float(m.group(2).replace(",", ""))
        if pct > 100 or pct < 0:
            return {"kind": "invalid", "reading": f"{pct:g} percent is outside 0 to 100"}
        comp = {"fewer than": "<", "less than": "<", "under": "<", "below": "<", "more than": ">", "over": ">",
                "above": ">", "at least": ">=", "at most": "<=", "about": "~", "around": "~", "approximately": "~",
                "roughly": "~", "nearly": "~", "almost": "~"}[word]
        return {"kind": "fraction", "comparator": comp, "threshold": pct / 100.0,
                "reading": f"'{word} {pct:g} percent'" + (f" (within {int(CFG['about_tolerance'] * 100)} points)" if comp == "~" else "")}
    m = re.search(r"(?<![\w.,])(?<!stage )(?<!grade )(\d[\d,]*)\s+(?:[\w+\-]+\s+){0,3}?" + NOUNS + r"\b(?!\s*(?:%|percent))", low)
    if m:
        n = float(m.group(1).replace(",", ""))
        before = low[max(0, m.start() - 25):m.start()]
        hedge = re.search(r"\b(about|around|approximately|roughly|nearly|almost|some)\s*$", before)
        noun = m.group(2)
        return {"kind": "count", "comparator": "~c" if hedge else "==", "threshold": n, "noun": noun,
                "reading": ("'about " if hedge else "'exactly ") + f"{int(n)}' {noun}" + (" (within 2 percent)" if hedge else "")}
    for pat, comp, thr, reading in [
        (r"\b(nearly|almost) all\b", ">=", CFG["nearly_all"], f"'nearly all' means at least {int(CFG['nearly_all'] * 100)} percent"),
        (r"\b(less|fewer) than half\b", "<", 0.5, "'less than half' means under 50 percent"),
        (r"\b(more than|over) half\b", ">", 0.5, "'more than half' means over 50 percent"),
        (r"\b(every|each|all|entire)\b", "==", 1.0, "'all/every' means 100 percent"),
        (r"\b(most|majority)\b", ">", CFG["most_threshold"], f"'most' means more than {int(CFG['most_threshold'] * 100)} percent"),
    ]:
        if re.search(pat, low):
            return {"kind": "fraction", "comparator": comp, "threshold": thr, "reading": reading}
    return None


def parse_claim(text):
    low = text.lower()
    q = parse_quantifier(text)
    if q and q["kind"] == "invalid":
        return {"type": "invalid", "reading": q["reading"]}
    target_text, cond_text = text, ""
    m = re.search(r"\b(?:samples|tumou?rs|patients|cases)\s+(?:that\s+|which\s+)?(?:have|with|having)\s+(.+)$", text, re.I)
    if m:
        left = text[:m.start()]
        if find_layers(left) or find_attr_mentions(left):  # something before the clause means it is a condition
            target_text, cond_text = left, m.group(1)
    filters = parse_filters(text)
    filter_attrs = {f["attr"] for f in filters}
    t_layers = find_layers(target_text)
    c_layers = [c for c in find_layers(cond_text) if c not in t_layers]
    recorded = [a for a in find_attr_mentions(target_text) if a not in filter_attrs]
    c_attrs = [a for a in find_attr_mentions(cond_text) if a not in filter_attrs and a not in recorded]
    events = bool(re.search(r"\b(deaths?|died|deceased|events?)\b", low))
    code, pop_label = "01", "primary tumor samples"
    for word, c, label in POPULATION_WORDS:
        if word in low:
            code, pop_label = c, label
    comparison = bool(re.search(r"compar|large enough|enough|sufficient|adequate", low))
    analytic = re.search(r"\b(correlat\w*|associat\w*|predict\w*|caus\w*|relationship|risk factors?|impact\w*|effects?|differ\w*|linked to)\b", low)
    base = {"filters": filters, "conditions": c_layers, "cond_attrs": c_attrs, "quantifier": q,
            "pop_code": code, "pop_label": pop_label, "events": events,
            "explicit_pop": bool(re.search(r"\bprimary\b|normal tissue|metasta", low))}
    ext = re.search(r"\b(?:is|are)\s+the\s+(largest|biggest|most common|most frequent|smallest|rarest|least common)\b", low)
    if ext and filters:
        direction = "min" if ext.group(1) in ("smallest", "rarest", "least common") else "max"
        return dict(base, type="extremum", attr=filters[0]["attr"], target_filter=filters[0], direction=direction,
                    ext_word=ext.group(1))
    if analytic:
        known = list(OrderedDict.fromkeys([f["attr"] for f in filters] + recorded + c_attrs))
        if known:
            return dict(base, type="readiness", attr=known[0], association=True)
        return {"type": "unanswerable", "outside": False,
                "reason": "it asserts a relationship, effect or prediction, which this tool does not test, or it uses a field that is not loaded"}
    if recorded and not t_layers and not filters and comparison and q is None:
        return dict(base, type="readiness", attr=recorded[0])
    if (q and q["kind"] == "count" and not t_layers and not recorded and not filters and not events
            and re.search(r"\b(?:primary tumou?rs?|tumou?rs?|samples?|patients?|cases?)\b", low)
            and re.search(r"\b(there (?:are|were)|has|have|had|contains?|includes?|comprises?|totals?|consists? of|release|cohort|dataset)\b", low)):
        pop = "patients" if re.search(r"\bpatients?\b", low) else ("samples" if re.search(r"\bsamples?\b", low) else "primary")
        return dict(base, type="popsize", pop=pop)
    if t_layers or recorded or (events and not filters) or (events and filters):
        return dict(base, type="measure", mode="targets", targets=t_layers, recorded=recorded)
    if filters:
        return dict(base, type="measure", mode="group", targets=[], recorded=[])
    outside = re.search(OTHER_DATASET_WORDS, low)
    return {"type": "unanswerable", "outside": bool(outside),
            "reason": ("it refers to a different cancer type or dataset than the loaded TCGA-BRCA release" if outside
                       else "it needs a field that is not among the loaded layers or clinical attributes")}


# ---------- computing ----------
def attr_label(ctx, key):
    return ATTR_SPECS[key]["label"]


def build_ops(ctx, parsed):
    """Return (pop_ops, tgt_ops). Each op is (label, function(sample_id) -> bool)."""
    def layer_op(name):
        lay = ctx.layers[name]
        return (f"has {LAYER_LABEL[name]}", lambda s, lay=lay: lay.contains(s))

    def recorded_op(key, tag="has"):
        return (f"{tag} {attr_label(ctx, key)} recorded", lambda s, key=key: ctx.attr(key, s) is not None)

    def filter_op(f):
        return (f["label"], lambda s, f=f: f["test"](ctx.attr(f["attr"], s)))

    pop_ops, tgt_ops = [], []
    if parsed["mode"] == "group":
        for key in OrderedDict.fromkeys(f["attr"] for f in parsed["filters"]):
            pop_ops.append(recorded_op(key))
        tgt_ops = [filter_op(f) for f in parsed["filters"]]
        return pop_ops, tgt_ops
    pop_ops += [filter_op(f) for f in parsed["filters"]]
    pop_ops += [(f"has {LAYER_LABEL[c]} (condition)", layer_op(c)[1]) for c in parsed["conditions"]]
    pop_ops += [recorded_op(a, "has (condition)") for a in parsed["cond_attrs"]]
    if parsed["events"]:
        pop_ops.append(layer_op("survival"))
        tgt_ops.append(("died (OS event)", lambda s: ctx.os_event(s) == 1))
    for t in parsed["targets"]:
        if parsed["events"] and t == "survival":
            continue
        tgt_ops.append(layer_op(t))
    for a in parsed["recorded"]:
        tgt_ops.append(recorded_op(a))
    return pop_ops, tgt_ops


def run_ops(ids, ops, start_label):
    cur = list(ids)
    steps = [{"step": start_label, "n_before": len(cur), "n_after": len(cur)}]
    for label, fn in ops:
        before = len(cur)
        cur = [s for s in cur if fn(s)]
        steps.append({"step": label, "n_before": before, "n_after": len(cur)})
    return steps, cur


def satisfied(q, value, count):
    v = value if q["kind"] == "fraction" else count
    t, c = q["threshold"], q["comparator"]
    if c == "~":
        return abs(value - t) <= CFG["about_tolerance"]
    if c == "~c":
        return abs(count - t) <= max(1, CFG["about_count_rel"] * t)
    return {"==": v == t, ">": v > t, ">=": v >= t, "<": v < t, "<=": v <= t}[c]


def missing_text(q, lead):
    """Plain wording for how far a result sits from the claim's bar."""
    t = q["threshold"]
    if q["kind"] == "count":
        gap = lead - t
        return f"{abs(int(gap))} {'above' if gap > 0 else 'below'} the bar of {int(t)}"
    return f"{abs(lead - t) * 100:.1f} points {'above' if lead > t else 'below'} the bar of {t * 100:.0f}%"


def source_files(parsed):
    files = [LAYER_SOURCE[l] for l in parsed.get("targets", []) + parsed.get("conditions", []) if l in LAYER_SOURCE]
    if parsed.get("filters") or parsed.get("recorded") or parsed.get("cond_attrs") or parsed.get("type") == "readiness":
        files.append("clinical.tsv")
    if parsed.get("events"):
        files.append("survival.tsv")
    return list(OrderedDict.fromkeys(files)) + ["sample_manifest.csv"]


def attr_used_text(ctx, keys):
    parts = []
    for n in ctx.attr_notes:
        for k in keys:
            if ATTR_SPECS[k]["label"] == n["attribute"]:
                alt = ", ".join(f"{a['column']} ({a['primary_tumors_with_recorded_value']})" for a in n["alternatives"])
                parts.append(f"{n['attribute']} read from {n['column_used']} (recorded for {n['primary_tumors_with_recorded_value']} of "
                             f"{n['primary_tumors']} primary tumors" + (f"; alternatives: {alt}" if alt else "") + ")")
    return "; ".join(parts)


def limitation_for(parsed, layers_used):
    parts = ["Presence in a file means the sample appears there; it says nothing about data quality or completeness inside the file."]
    if "slides" in layers_used:
        parts = ["A slide counts only when its barcode matches the sample; diagnostic and frozen slides are not separated here."]
    if parsed.get("filters") or parsed.get("recorded") or parsed.get("cond_attrs") or parsed.get("type") == "readiness":
        parts.append("A clinical field counts as recorded when it holds a value (not blank or 'not available'); the values themselves were not verified. "
                     "Where several columns hold the same field, the one with the most recorded values is used unless overridden, "
                     "which favors completeness over how definitive the measurement is.")
    if "survival" in layers_used or parsed.get("events"):
        parts.append("Survival presence says nothing about follow-up length; events are overall-survival deaths.")
    return " ".join(parts)


# ---------- findings ----------
def blank_finding(fid, text):
    return OrderedDict([
        ("id", fid), ("claim_text", text), ("verdict", "insufficient_evidence"),
        ("evidence", OrderedDict([("metric_name", "not_computed"), ("value", None), ("n_samples", 0),
                                   ("denominator", 0), ("source_files", []), ("calculation", "")])),
        ("cohort_trace", []), ("limitation", ""), ("needs_human_review", False), ("review_reason", None),
        ("guardrail_flags", []), ("next_actions", []), ("robustness", None),
        ("correct_value", None), ("missing_evidence", None), ("source_sentence", None),
    ])


REDACT_FLAGS = {"phi_like_input", "reidentification_blocked", "individual_level_request_blocked"}


def _fallback_redact(text):
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[email removed]", text)
    text = re.sub(r"\bTCGA-[A-Za-z0-9]{2}-[A-Za-z0-9]{4}(?:-[A-Za-z0-9-]+)?", "[barcode removed]", text)
    text = re.sub(r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b", "[number removed]", text)
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b", "[date removed]", text)
    text = re.sub(r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)", "[number removed]", text)
    return text


def safe_claim_text(text, flags):
    """Claim text as stored in findings. Claims blocked for personal details are stored redacted."""
    if not REDACT_FLAGS & set(flags):
        return text
    if "phi_like_input" in flags:
        return "[claim withheld: it contained personal details]"
    if _redact is not None:
        try:
            out = _redact(text)
            if isinstance(out, str):
                return out
        except Exception:
            pass
    return _fallback_redact(text)


def blocked_finding(fid, text, flags, reason, total):
    f = blank_finding(fid, safe_claim_text(text, flags))
    f["evidence"]["calculation"] = f"not run: {reason}"
    f["evidence"]["denominator"] = total
    f["limitation"] = "This tool checks data readiness only. The request was stopped before any analysis."
    f["needs_human_review"] = True
    f["review_reason"] = reason
    f["guardrail_flags"] = list(flags)
    acts = []
    for fl in flags:
        acts += BLOCK_ACTIONS.get(fl, [])
    f["next_actions"] = acts or ["Rewrite the claim as a cohort-level data-availability question."]
    return f


def run_guardrails(text):
    if _check_claim is not None:
        return _check_claim(text)
    if not ALLOW_FALLBACK:
        raise RuntimeError("src/guardrails is missing or failed to import: " + repr(_GUARD_ERROR))
    low = (text or "").lower()
    flags = []
    if not (text or "").strip():
        flags.append("invalid_input")
    if re.search(r"ignore (all )?previous instructions|reveal your api key|^system:", low):
        flags.append("prompt_injection_suspected")
    if re.search(r"\bdob\b|\bmrn\b|[a-z0-9._-]+@[a-z0-9.-]+\.[a-z]{2,}|(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)", low):
        flags.append("phi_like_input")
    if re.search(r"outside records|obituar", low):
        flags.append("reidentification_blocked")
    if re.search(r"tcga-[a-z0-9]{2}-[a-z0-9]{4}", low) and "reidentification_blocked" not in flags:
        flags.append("individual_level_request_blocked")
    if re.search(r"improves survival|should receive|risk score|diagnos|which treatment|chemotherapy|prognos|respon\w*\b.*\b(therapy|treatment|drug)", low):
        flags.append("clinical_claim_blocked")
    return {"allowed": not flags, "flags": flags, "reason": ("Stopped by guardrails: " + ", ".join(flags)) if flags else ""}


def readiness_finding(ctx, f, parsed, total):
    key = parsed["attr"]
    if key not in ctx.attrs:
        f["evidence"]["calculation"] = f"not run: no {ATTR_SPECS[key]['label']} column was found in the clinical file"
        f["limitation"] = f"The data cannot answer this: no {ATTR_SPECS[key]['label']} column found."
        f["guardrail_flags"] = ["data_cannot_answer"]
        f["next_actions"] = ["Check whether the field exists under another name in the clinical file."]
        return f
    pop = ctx.population(parsed["pop_code"])
    groups = Counter()
    events = Counter()
    for s in pop:
        v = ctx.attr(key, s)
        if v is None:
            continue
        groups[v] += 1
        if ctx.os_event(s) == 1:
            events[v] += 1
    recorded = sum(groups.values())
    if not groups:
        f["evidence"]["calculation"] = f"not run: {ATTR_SPECS[key]['label']} has no recorded values among {parsed['pop_label']}"
        f["limitation"] = "The data cannot answer this: the field is empty for this population."
        f["guardrail_flags"] = ["data_cannot_answer"]
        f["next_actions"] = ["Use a different attribute or a different column for the grouping."]
        return f
    breakdown = [{"group": ctx.display_name(key, g), "n": n, "events": events.get(g, 0)} for g, n in groups.most_common()]
    smallest = min(breakdown, key=lambda b: b["n"])
    low_events = [b for b in breakdown if b["events"] < CFG["min_events"]]
    shown = "; ".join(f"{b['group']} {b['n']} ({b['events']} deaths)" for b in breakdown)
    ev = f["evidence"]
    ev.update({"metric_name": f"group_sizes_{key}", "value": smallest["n"], "n_samples": recorded,
               "denominator": len(pop), "source_files": source_files(parsed), "breakdown": breakdown,
               "calculation": (f"{ATTR_SPECS[key]['label']} among {parsed['pop_label']}: recorded for {recorded} of {len(pop)}. "
                               f"Groups (samples, OS deaths): {shown}. Smallest group: {smallest['group']} with {smallest['n']} samples "
                               f"and {smallest['events']} deaths. {attr_used_text(ctx, [key])}.")})
    f["cohort_trace"] = [{"step": parsed["pop_label"], "n_before": len(pop), "n_after": len(pop)},
                         {"step": f"has {ATTR_SPECS[key]['label']} recorded", "n_before": len(pop), "n_after": recorded}]
    f["limitation"] = limitation_for(parsed, [])
    reasons = ["The claim has no measurable threshold; a person must decide what counts as large enough."]
    if parsed.get("association"):
        ev["calculation"] = ("This tool does not test whether the relationship holds; it checks whether the groups are large enough to study it. "
                             + ev["calculation"])
        reasons = ["The claim asserts a relationship, which this tool does not test; a person must decide whether these group sizes are enough to study it."]
    if smallest["n"] < CFG["min_group_size"]:
        reasons.append(f"The smallest group has only {smallest['n']} samples.")
    if low_events:
        f["guardrail_flags"] = ["low_event_count"]
        reasons.append(f"{len(low_events)} group(s) have fewer than {CFG['min_events']} deaths, which is thin for survival comparisons.")
    f["needs_human_review"], f["review_reason"] = True, " ".join(reasons)
    f["next_actions"] = ["State the minimum group size (and deaths) the comparison needs, then re-run.",
                         f"Merge or drop the smallest group ({smallest['group']}, {smallest['n']} samples) if the comparison needs balanced groups."]
    if recorded < len(pop):
        f["next_actions"].append(f"Check why {len(pop) - recorded} of {len(pop)} samples have no recorded {ATTR_SPECS[key]['label']}.")
    return f


def evaluate_claim(ctx, fid, text):
    total = len(ctx.population("01")) or len(ctx.all_samples)
    guard = run_guardrails(text)
    if not guard["allowed"]:
        return blocked_finding(fid, text, guard["flags"], guard.get("reason") or "Stopped by guardrails.", total)
    parsed = parse_claim(normalize_claim_text(text))
    f = blank_finding(fid, text)
    f["evidence"]["denominator"] = total
    if parsed["type"] == "invalid":
        f["evidence"]["calculation"] = f"not run: {parsed['reading']}"
        f["limitation"] = "A percentage outside 0 to 100 is impossible, so the claim cannot be checked as written."
        f["guardrail_flags"] = ["invalid_input"]
        f["needs_human_review"], f["review_reason"] = True, "The claim contains an impossible percentage."
        f["next_actions"] = BLOCK_ACTIONS["invalid_input"] + ["Rewrite the claim with a percentage between 0 and 100."]
        return f
    if parsed["type"] == "unanswerable":
        f["evidence"]["calculation"] = f"not run: {parsed['reason']}"
        f["limitation"] = f"The data cannot answer this: {parsed['reason']}."
        f["guardrail_flags"] = ["data_cannot_answer"]
        f["next_actions"] = ["Rephrase the claim around the available layers (clinical, survival, mutation, copy number, RNA, protein, slides) "
                             "or clinical fields (ER, PR, HER2, stage, histology, PAM50 subtype, gender).",
                             "Check whether the needed field exists in another data file."]
        return f
    if parsed["type"] == "readiness":
        return readiness_finding(ctx, f, parsed, total)
    if parsed["type"] == "popsize":
        return popsize_finding(ctx, f, parsed, total)
    if parsed["type"] == "extremum":
        return extremum_finding(ctx, f, parsed, total)

    # measure
    attr_keys = list(OrderedDict.fromkeys([x["attr"] for x in parsed["filters"]] + parsed["recorded"] + parsed["cond_attrs"]))
    missing = [l for l in parsed["conditions"] + parsed["targets"] if l not in ctx.layers]
    missing += [ATTR_SPECS[a]["label"] for a in attr_keys if a not in ctx.attrs]
    if parsed["events"] and not ctx.os:
        missing.append("survival events")
    if missing:
        f["evidence"]["calculation"] = f"not run: not loaded or not found: {missing}"
        f["limitation"] = f"The data cannot answer this: {missing} not available."
        f["guardrail_flags"] = ["data_cannot_answer"]
        f["next_actions"] = ["Re-run the data download, or check the column names in the clinical file."]
        return f
    pop_ids = ctx.population(parsed["pop_code"])
    pop_ops, tgt_ops = build_ops(ctx, parsed)
    steps, final = run_ops(pop_ids, pop_ops + tgt_ops, parsed["pop_label"])
    den = steps[len(pop_ops)]["n_after"]
    num = len(final)
    q = parsed["quantifier"]
    layers_used = parsed["conditions"] + parsed["targets"] + (["survival"] if parsed["events"] else [])
    is_count = bool(q and q["kind"] == "count")
    value = num / den if den else None
    labels = [t[0] for t in tgt_ops]
    if parsed["mode"] == "group":
        kind = "count" if is_count else "share"
        metric = f"{kind}_" + "_".join(re.sub(r"\W+", "_", l.lower()).strip("_") for l in labels)
        calc = (f"{' + '.join(labels)} among {parsed['pop_label']} with "
                f"{' and '.join(ATTR_SPECS[a]['label'] for a in OrderedDict.fromkeys(x['attr'] for x in parsed['filters']))} recorded: "
                f"{num} / {den}" + (f" = {value * 100:.1f}%" if value is not None else ""))
    else:
        tl = " and ".join(["deaths" if t[0].startswith("died") else t[0].replace("has ", "") for t in tgt_ops])
        denom_text = parsed["pop_label"]
        extra = [o[0].replace(" (condition)", "") for o in pop_ops]
        if extra:
            denom_text += " that are/have " + " and ".join(extra)
        metric = ("count_" if is_count else "overlap_" if len(tgt_ops) > 1 else "coverage_") + "_".join(
            re.sub(r"\W+", "_", t[0].lower()).strip("_") for t in tgt_ops)
        calc = f"samples with {tl} among {denom_text}: {num} / {den}" + (f" = {value * 100:.1f}%" if value is not None else "")
    if attr_keys:
        calc += ". " + attr_used_text(ctx, attr_keys)
    ev = f["evidence"]
    shown = num if is_count else (round(value, 4) if value is not None else None)
    ev.update({"metric_name": metric, "value": shown, "n_samples": num, "denominator": den,
               "source_files": source_files(parsed)})
    f["cohort_trace"] = steps
    f["limitation"] = limitation_for(parsed, layers_used)

    # survival events in the final group
    want_events = parsed["events"] or "survival" in layers_used
    n_events = None
    if want_events and ctx.os:
        n_events = sum(1 for s in final if ctx.os_event(s) == 1)
        calc += f". OS deaths among these {num} samples: {n_events}"
    analysis = bool(re.search(r"\b(study|studies|analy[sz]e|analysis|compar\w*|model|predict\w*|associat\w*|test|evaluate|enough|sufficient)\b", text.lower()))
    low_events = (want_events and n_events is not None and n_events < CFG["min_events"]
                  and not parsed["events"] and analysis)
    if low_events:
        f["guardrail_flags"] = ["low_event_count"]

    if den < CFG["min_population"] and not is_count:
        ev["calculation"] = calc + f". Only {den} samples are in the denominator, which is too few to judge."
        f["needs_human_review"], f["review_reason"] = True, "The denominator is too small to judge the claim."
        f["next_actions"] = ["Widen the population or drop a condition so more samples remain."]
        return f
    if q is None:
        ev["calculation"] = calc + ". The claim has no measurable threshold, so no verdict is given."
        reasons = ["The claim has no measurable threshold; a person must decide what counts as enough."]
        if low_events:
            reasons.append(f"Only {n_events} deaths remain, below {CFG['min_events']}, which is thin for survival comparisons.")
        f["needs_human_review"], f["review_reason"] = True, " ".join(reasons)
        f["next_actions"] = ["State a number the claim should meet (for example, at least 75 percent), then re-run.",
                             "Ask a reviewer what counts as enough for the intended question."]
        return f
    ok = satisfied(q, value, num)
    f["verdict"] = "supported" if ok else "contradicted"
    ev["calculation"] = calc + f". Claim read as: {q['reading']}."
    lead = value if q["kind"] == "fraction" else num
    reasons = []
    if q["comparator"] not in ("~", "~c") and not (q["kind"] == "count" and q["comparator"] == "=="):
        near = abs(lead - q["threshold"]) <= (CFG["borderline_margin"] if q["kind"] == "fraction" else 0)
        if near:
            reasons.append(f"The result sits {missing_text(q, lead)}.")
    if not ok and q["comparator"] in ("==", ">=", ">") and q["kind"] == "fraction" and den - num > 0 and q["comparator"] == "==":
        ev["calculation"] += f" {den - num} of {den} samples fall short of 'all'."
    if low_events:
        reasons.append(f"Only {n_events} deaths remain, below {CFG['min_events']}, which is thin for survival comparisons.")

    if f["verdict"] == "contradicted":
        if q["kind"] == "fraction" and value is not None:
            f["correct_value"] = {"value": round(value * 100, 1), "unit": "percent", "text": f"{value * 100:.1f}% ({num} of {den})"}
        else:
            unit = q.get("noun") or "samples"
            f["correct_value"] = {"value": num, "unit": unit, "text": f"{num} {unit} ({num} of {den} {parsed['pop_label']})"}

    # robustness: one alternative reading of the same claim
    rob = None
    if parsed["mode"] == "group" and q["kind"] == "fraction" and len(pop_ids):
        alt_val = num / len(pop_ids)
        alt_ok = satisfied(q, alt_val, num)
        rob = {"alt_rule": "count samples with no recorded value in the denominator too",
               "alt_value": round(alt_val, 4), "verdict_changes": alt_ok != ok}
    elif (parsed["pop_code"] == "01" and len(ctx.all_samples) != len(pop_ids) and not parsed["explicit_pop"]
          and not (q["kind"] == "count" and q["comparator"] in ("==", "~c"))):
        a_steps, a_final = run_ops(ctx.all_samples, pop_ops + tgt_ops, "all samples")
        a_den = a_steps[len(pop_ops)]["n_after"]
        if a_den:
            a_val = len(a_final) / a_den
            alt_ok = satisfied(q, a_val, len(a_final))
            rob = {"alt_rule": "count every sample type (tumor, normal, metastasis) instead of primary tumors only",
                   "alt_value": round(a_val, 4) if q["kind"] == "fraction" else len(a_final), "verdict_changes": alt_ok != ok}
    f["robustness"] = rob
    if rob and rob["verdict_changes"]:
        reasons.append("The verdict flips under the alternative reading: " + rob["alt_rule"] + ".")
    if reasons:
        f["needs_human_review"], f["review_reason"] = True, " ".join(reasons)
    if f["verdict"] == "contradicted":
        f["next_actions"] = [f"Restrict the question to the {num} samples that match, or choose a layer or field with better coverage.",
                             f"Restate the claim with the measured figure ({num} of {den})."]
        for n in ctx.attr_notes:
            if any(a["primary_tumors_with_recorded_value"] > n["primary_tumors_with_recorded_value"] for a in n["alternatives"]) and n["attribute"] in [ATTR_SPECS[k]["label"] for k in attr_keys]:
                best = max(n["alternatives"], key=lambda a: a["primary_tumors_with_recorded_value"])
                f["next_actions"].append(f"Try the column {best['column']}: recorded for {best['primary_tumors_with_recorded_value']} primary tumors vs {n['primary_tumors_with_recorded_value']}.")
    else:
        f["next_actions"] = ["Check data quality inside the file, not just presence, before relying on it."]
        if rob and rob["verdict_changes"]:
            f["next_actions"].append("Decide which reading of the claim the question really needs.")
    if low_events:
        f["next_actions"].append("Use a larger group or a longer-follow-up outcome before comparing survival.")
    return f


def popsize_finding(ctx, f, parsed, total):
    key = parsed["pop"]
    if key == "samples":
        n, label = len(ctx.all_samples), "samples in the release"
    elif key == "patients":
        n, label = len({L.patient_of(x) for x in ctx.all_samples}), "patients in the release"
    else:
        n, label = len(ctx.population("01")), "primary tumor samples"
    q = parsed["quantifier"]
    ok = satisfied(q, None, n)
    f["evidence"].update({"metric_name": f"population_size_{key}", "value": n, "n_samples": n, "denominator": n,
                          "source_files": ["sample_manifest.csv"],
                          "calculation": f"{label}: {n}. Claim read as: {q['reading']}."})
    f["cohort_trace"] = [{"step": label, "n_before": n, "n_after": n}]
    f["verdict"] = "supported" if ok else "contradicted"
    f["limitation"] = "Counts come from the release's sample list: one sample is one barcode, and one patient can have several samples."
    if ok:
        f["next_actions"] = ["State which sample types the count covers (primary tumor, normal tissue, metastasis) so readers can reproduce it."]
    else:
        f["correct_value"] = {"value": n, "unit": key, "text": f"{n} {label}"}
        f["next_actions"] = [f"Restate the count as {n} {label}.", "Say which sample types the count covers."]
    return f


def extremum_finding(ctx, f, parsed, total):
    key, flt = parsed["attr"], parsed["target_filter"]
    pop = ctx.population(parsed["pop_code"])
    counts, deaths = Counter(), Counter()
    for sid in pop:
        v = ctx.attr(key, sid)
        if v is None:
            continue
        counts[v] += 1
        if ctx.os_event(sid) == 1:
            deaths[v] += 1
    if key not in ctx.attrs or not counts:
        f["evidence"]["calculation"] = f"not run: no recorded {ATTR_SPECS[key]['label']} values were found"
        f["limitation"] = "The data cannot answer this: the needed field is empty or missing."
        f["guardrail_flags"] = ["data_cannot_answer"]
        f["next_actions"] = ["Check whether the field exists under another name in the clinical file."]
        return f
    recorded = sum(counts.values())
    pick = min if parsed["direction"] == "min" else max
    extreme_n = pick(counts.values())
    leaders = [g for g, n in counts.items() if n == extreme_n]
    x_groups = [g for g in counts if flt["test"](g)]
    shown = "; ".join(f"{ctx.display_name(key, g)} {n}" for g, n in counts.most_common())
    breakdown = [{"group": ctx.display_name(key, g), "n": n, "events": deaths.get(g, 0)} for g, n in counts.most_common()]
    word = parsed["ext_word"]
    leader_txt = ", ".join(ctx.display_name(key, g) for g in leaders)
    if not x_groups:
        f["evidence"].update({"metric_name": f"extremum_{key}", "value": None, "n_samples": 0, "denominator": recorded,
                              "source_files": ["clinical.tsv", "sample_manifest.csv"], "breakdown": breakdown,
                              "calculation": f"{flt['label']} does not occur among the {recorded} recorded {ATTR_SPECS[key]['label']} values: {shown}."})
        f["limitation"] = "The group named in the claim was not found in the data."
        f["guardrail_flags"] = ["data_cannot_answer"]
        f["next_actions"] = ["Check the group name against the values in the data: " + shown + "."]
        return f
    ok = all(g in leaders for g in x_groups)
    x_n = sum(counts[g] for g in x_groups)
    f["evidence"].update({"metric_name": f"extremum_{key}", "value": x_n, "n_samples": x_n, "denominator": recorded,
                          "source_files": ["clinical.tsv", "sample_manifest.csv"], "breakdown": breakdown,
                          "calculation": (f"Groups of {ATTR_SPECS[key]['label']} among {parsed['pop_label']} with it recorded "
                                          f"({recorded} of {len(pop)}): {shown}. The {'smallest' if parsed['direction'] == 'min' else 'largest'} "
                                          f"group is {leader_txt} ({extreme_n} of {recorded}). Claim: {flt['label']} is the {word}. "
                                          f"{attr_used_text(ctx, [key])}.")})
    f["cohort_trace"] = [{"step": parsed["pop_label"], "n_before": len(pop), "n_after": len(pop)},
                         {"step": f"has {ATTR_SPECS[key]['label']} recorded", "n_before": len(pop), "n_after": recorded}]
    f["limitation"] = limitation_for(parsed, [])
    f["verdict"] = "supported" if ok else "contradicted"
    if ok:
        f["next_actions"] = ["Check data quality inside the field, not just counts, before relying on the ranking."]
    else:
        f["correct_value"] = {"value": extreme_n, "unit": "samples",
                              "text": f"The {'smallest' if parsed['direction'] == 'min' else 'largest'} group is {leader_txt} ({extreme_n} of {recorded}); "
                                      f"{flt['label']} has {x_n} of {recorded}"}
        f["next_actions"] = [f"Restate the claim: {leader_txt} is the {'smallest' if parsed['direction'] == 'min' else 'largest'} group."]
    return f


def split_subclaims(text):
    """Split one sentence into the separate checks it contains (kept small and explicit)."""
    t = text.strip()
    m = re.match(r"^Of the (?P<M>\d[\d,]*) (?P<pop>[\w\s-]+?)(?: in [^,]*)?,\s*(?P<N>\d[\d,]*)\s+(?P<rest>(?:have|had|has|carry|show|with)\b.*)$", t, re.I)
    if not m:
        m = re.match(r"^(?P<N>\d[\d,]*) of the (?P<M>\d[\d,]*) (?P<pop>[^,]+?)(?: in [^,]*?)?\s+(?P<rest>(?:have|had|has)\b.*)$", t, re.I)
    if m:
        pop = m.group("pop").strip()
        return [f"There are {m.group('M')} {pop}.", f"{m.group('N')} {pop} {m.group('rest').strip()}"]
    m = re.match(r"^(?:there (?:are|were)|the release (?:has|contains)|it (?:has|contains))\s+(?P<a>\d[\d,]*)\s+samples?\s+(?:from|across|belonging to|representing)\s+(?P<b>\d[\d,]*)\s+patients?\b", t, re.I)
    if m:
        return [f"There are {m.group('a')} samples.", f"There are {m.group('b')} patients."]
    m = re.match(r"^(?P<subj>.+?)\s+(?:is|are)\s+the\s+(?P<ext>largest|biggest|most common|most frequent|smallest|rarest|least common)"
                 r"(?P<what>[^,]*?),\s*(?:accounting for|making up|representing|comprising|constituting|which (?:accounts for|makes up|represents))\s+(?P<tail>.+)$", t, re.I)
    if m:
        return [f"{m.group('subj')} is the {m.group('ext')}{m.group('what')}.", f"{m.group('subj')} accounts for {m.group('tail').strip()}"]
    return [t]


VERDICT_RANK = {"supported": 1, "insufficient_evidence": 2, "contradicted": 3}
CLINICAL_MISSING = ("Treatment, drug-response or outcome-by-treatment records. The loaded TCGA-BRCA files hold clinical stage and receptor fields, "
                    "survival times, and molecular layers, but no treatment or response data.")


def combine_parts(parts, text):
    import copy
    worst = parts[0]
    for part in parts:
        if VERDICT_RANK[part["verdict"]] >= VERDICT_RANK[worst["verdict"]]:
            worst = part
    f = copy.deepcopy(worst)
    f["claim_text"] = text
    f["verdict"] = worst["verdict"]
    f["evidence"]["calculation"] = " | ".join(p["evidence"]["calculation"] for p in parts if p["evidence"]["calculation"])
    f["evidence"]["sub_checks"] = [{"claim": p["claim_text"], "verdict": p["verdict"], "value": p["evidence"]["value"],
                                    "n_samples": p["evidence"]["n_samples"], "denominator": p["evidence"]["denominator"]} for p in parts]
    f["guardrail_flags"] = list(OrderedDict.fromkeys(fl for p in parts for fl in p["guardrail_flags"]))
    f["needs_human_review"] = any(p["needs_human_review"] for p in parts)
    reasons = [p["review_reason"] for p in parts if p["review_reason"]]
    f["review_reason"] = " ".join(OrderedDict.fromkeys(reasons)) if reasons else None
    if f["needs_human_review"] and not f["review_reason"]:
        f["review_reason"] = "At least one part of this claim needs a person to look at it."
    f["next_actions"] = list(OrderedDict.fromkeys(a for p in parts for a in p["next_actions"]))
    f["limitation"] = " ".join(OrderedDict.fromkeys(p["limitation"] for p in parts if p["limitation"]))
    wrong = [p["correct_value"]["text"] for p in parts if p["verdict"] == "contradicted" and p.get("correct_value")]
    f["correct_value"] = ({"value": next(p["correct_value"]["value"] for p in parts if p["verdict"] == "contradicted" and p.get("correct_value")),
                           "unit": "mixed" if len(wrong) > 1 else next(p["correct_value"]["unit"] for p in parts if p["verdict"] == "contradicted" and p.get("correct_value")),
                           "text": "; ".join(wrong)} if wrong else None)
    return f


def finalize_finding(f, source):
    # The stored source sentence can be longer than the checked claim (for example a trimmed tail),
    # so run the guardrails on the full sentence too and redact it the same way when flagged.
    guard = run_guardrails(source)
    flags = set(f["guardrail_flags"]) | (set() if guard.get("allowed", True) else set(guard.get("flags", [])))
    f["source_sentence"] = safe_claim_text(source, sorted(flags)) if REDACT_FLAGS & flags else source
    if f["verdict"] == "insufficient_evidence" and not f.get("missing_evidence"):
        flags = set(f["guardrail_flags"])
        if "clinical_claim_blocked" in flags:
            f["missing_evidence"] = CLINICAL_MISSING
        elif "data_cannot_answer" in flags:
            f["missing_evidence"] = (f["limitation"].replace("The data cannot answer this: ", "").rstrip(".") +
                                     ". A data field that covers this question would be needed.")
        elif flags & {"individual_level_request_blocked", "reidentification_blocked", "phi_like_input", "prompt_injection_suspected"}:
            f["missing_evidence"] = "Not applicable: this tool answers cohort-level data-readiness questions only."
        elif "invalid_input" in flags:
            f["missing_evidence"] = "A well-formed claim with a valid number."
        else:
            f["missing_evidence"] = f["review_reason"] or "A measurable threshold or a defined comparison for the claim."
    return f


def evaluate_item(ctx, fid, item):
    text = item["text"] if isinstance(item, dict) else item
    source = item.get("source", text) if isinstance(item, dict) else text
    subs = split_subclaims(text)
    if len(subs) == 1:
        f = evaluate_claim(ctx, fid, text)
    else:
        guard = run_guardrails(text)
        if not guard["allowed"]:
            total = len(ctx.population("01")) or len(ctx.all_samples)
            f = blocked_finding(fid, text, guard["flags"], guard.get("reason") or "Stopped by guardrails.", total)
        else:
            f = combine_parts([evaluate_claim(ctx, fid, sub) for sub in subs], text)
    return finalize_finding(f, source)


def audit(ctx, claims, title, skipped=None):
    findings = [evaluate_item(ctx, f"claim-{i:03d}", c) for i, c in enumerate(claims, 1)]
    doc = _build_document(ctx, findings, title)
    if skipped:
        kept = []
        for sk in skipped:
            g = run_guardrails(sk["text"]) if (_check_claim is not None or ALLOW_FALLBACK) else {"allowed": False}
            kept.append({"text": sk["text"] if g.get("allowed") else "[withheld]", "reason": sk["reason"]})
        doc["skipped_sentences"] = kept
    if not ALLOW_FALLBACK:
        if _check_document is None:
            raise RuntimeError("src/guardrails post-check (check_document) is missing or failed to import")
        problems = _check_document(doc)
        if problems:
            raise PostCheckError(problems)
    return doc


def _build_document(ctx, findings, title):
    return OrderedDict([
        ("is_mock", False), ("schema_version", "draft-0"),
        ("data_release", {"name": "TCGA-BRCA (frozen event release)",
                          "checksum_verified": ctx.checksums["status"] == "verified",
                          "checksum_status": ctx.checksums["status"]}),
        ("report_title", title), ("interpretation_config", CFG),
        ("guardrails_source", GUARDRAILS_SOURCE), ("data_notes", ctx.attr_notes), ("findings", findings),
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Evidence engine v1.2.1")
    ap.add_argument("--data-dir", default=L.DEFAULT_DIR)
    ap.add_argument("--report", help="text or markdown file with numbered or bulleted claims")
    ap.add_argument("--claim", action="append", default=[], help="a single claim (can repeat)")
    ap.add_argument("--out", default=os.path.join("out", "findings.json"))
    ap.add_argument("--notes", action="store_true", help="print which clinical columns were chosen")
    ap.add_argument("--extract-only", action="store_true", help="show which sentences would be checked and which skipped, then stop")
    ap.add_argument("--unsafe-no-guardrails", action="store_true",
                    help="use the small built-in rules if src/guardrails is missing (quick local tests only, never for submission)")
    ap.add_argument("--column", action="append", default=[],
                    help="force a clinical column, e.g. --column her2=HER2_Final_Status_nature2012 (keys: " + ", ".join(ATTR_SPECS) + ")")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # never crash on characters the console cannot show
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    global ALLOW_FALLBACK, GUARDRAILS_SOURCE
    if _check_claim is None:
        if not args.unsafe_no_guardrails:
            sys.exit("src/guardrails is missing or failed to import (" + repr(_GUARD_ERROR) + ").\n"
                     "Copy the guardrails module into src/guardrails, or add --unsafe-no-guardrails for a quick local test only.")
        ALLOW_FALLBACK = True
        GUARDRAILS_SOURCE = "built-in fallback (limited, NOT for submission)"
        print("WARNING: running without the real guardrails module.", file=sys.stderr)
    claims, title, skipped = list(args.claim), "Ad hoc claims", []
    if args.report:
        with open(args.report, encoding="utf-8") as fh:
            extracted, skipped = extract_claims(fh.read())
        claims += extracted
        title = os.path.basename(args.report)
        if args.extract_only:
            print(f"\nWould check {len(extracted)} claim(s):")
            for i, c in enumerate(extracted, 1):
                print(f"  {i}. {c['text']}")
            print(f"\nSkipped {len(skipped)} sentence(s):")
            for sk in skipped:
                print(f"  - ({sk['reason']}) {sk['text'][:100]}")
            return
    if not claims:
        sys.exit("give --report FILE or at least one --claim TEXT")
    if not os.path.isdir(args.data_dir):
        sys.exit(f"data folder not found: {os.path.abspath(args.data_dir)}")
    overrides = {}
    for item in args.column:
        if "=" not in item or item.split("=", 1)[0] not in ATTR_SPECS:
            sys.exit(f"bad --column {item!r}; use key=ColumnName with key one of {list(ATTR_SPECS)}")
        k, v = item.split("=", 1)
        overrides[k] = v
    ctx = Context(args.data_dir, overrides)
    try:
        doc = audit(ctx, claims, title, skipped)
    except PostCheckError as err:
        print("Refusing to write output: the guardrails post-check found problems.", file=sys.stderr)
        for problem in err.problems:
            print("  -", problem, file=sys.stderr)
        sys.exit(3)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    print(f"\nGuardrails: {GUARDRAILS_SOURCE}   Checksums: {ctx.checksums['status']}\n")
    if args.notes:
        print("Clinical columns chosen (recorded values among primary tumors):")
        for n in ctx.attr_notes:
            alts = ", ".join(f"{a['column']}={a['primary_tumors_with_recorded_value']}" for a in n["alternatives"]) or "none"
            print(f"  {n['attribute']:<18} {n['column_used']}  ({n['primary_tumors_with_recorded_value']}/{n['primary_tumors']}, {n['chosen_by']})  alternatives: {alts}")
        print()
    problems = 0
    for f in doc["findings"]:
        ev = f["evidence"]
        val = "-" if ev["value"] is None else (f"{ev['value']:.3f}" if isinstance(ev["value"], float) else ev["value"])
        errs = VF.check_finding(f) if VF else []
        problems += len(errs)
        print(f"{f['id']}  {f['verdict']:<22} value={val:<7} n={ev['n_samples']}/{ev['denominator']}  "
              f"flags={f['guardrail_flags']} review={f['needs_human_review']}")
        print(f"          {f['claim_text'][:90]}")
        for e in errs:
            print("          CONTRACT PROBLEM:", e)
    print(f"\nSaved {args.out}  ({len(doc['findings'])} findings, {problems} contract problems)")


if __name__ == "__main__":
    main()
