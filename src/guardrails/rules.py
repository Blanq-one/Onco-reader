r"""Guardrail rules: the one config block. Every refusal this tool makes is listed here.

This tool checks DATA READINESS only (is the data there, how much of it, can it
be joined). The rules stop five kinds of input before any number is computed:
instructions aimed at the system, identifying information, attempts to
re-identify people, questions about one individual, and clinical claims.

Each rule carries two short comments:
  WHY  the reason the rule exists.
  FP   a legitimate data question the rule could wrongly block (a false
       positive), where we know of one. Near misses that must stay ALLOWED are
       pinned in tests/edge_cases.csv, so a pattern that grows too greedy fails
       the tests.

How false blocks are kept down:
  * Bare clinical words never block on their own. "Treatment records", "age at
    diagnosis", "radiation_therapy", "date of birth" and "survival data" are
    real fields or layers in the release, and asking whether they are recorded
    is exactly what this tool is for. A rule needs a clinical VERB or FRAMING
    ("improves survival", "should receive", "responded to", "is prognostic").
  * Outcome or treatment words followed by a data noun ("survival data",
    "survival coverage", "treatment records") are skipped by the NOT_DATA and
    TREAT_NOT_DATA lookaheads.
  * Softer rules marked readiness_exempt step aside when the claim is framed as
    a data-availability question ("...is recorded for...", "...is enough to...").

Patterns run on normalised text (check.normalise: NFKC, invisible characters
removed, accents folded, whitespace collapsed), lower-cased, except rules with
on_original=True, which need capital letters to spot names.
"""
import re
from dataclasses import dataclass
from typing import Optional, Pattern, Tuple

# Order in which flags are reported. Names match GUARDRAIL_FLAGS in contract/validate_findings.py.
FLAG_ORDER = (
    "invalid_input",
    "prompt_injection_suspected",
    "phi_like_input",
    "reidentification_blocked",
    "individual_level_request_blocked",
    "clinical_claim_blocked",
)

# WHY: one claim is one sentence. Anything longer is a pasted document or an
# attempt to bury instructions in a long blob.
# FP: a genuine run-on claim over this length is rejected; the reason asks the
# author to split it.
MAX_CLAIM_CHARS = 1000

# Never run the patterns over more than this many characters (keeps huge input fast).
SCAN_LIMIT = 20000


@dataclass(frozen=True)
class Rule:
    id: str
    flag: str
    label: str                          # completes the reason sentence shown to the reviewer
    patterns: Tuple[Pattern, ...]       # any match fires the rule
    requires: Optional[Pattern] = None  # if set, this must ALSO match somewhere in the claim
    readiness_exempt: bool = False      # skip when the claim is framed as a data-availability question
    on_original: bool = False           # match case-preserved text (needed for names)


def _c(*pats, flags=re.I):
    return tuple(re.compile(p, flags) for p in pats)


# ---------- shared vocabulary ----------
PERSON = r"(?:patient|woman|man|person|individual|donor|participant|subject|lady)"
PERSONS = r"(?:patients|women|men|people|persons|individuals|donors|participants|subjects)"
GROUP_WORDS = r"(?:population|cohort|group|subgroup|level|samples?|records?|data|ids?|barcodes?)"

TREATMENT = (r"(?:treatments?|therap(?:y|ies)|regimens?|drugs?|medications?|medicines?|chemo\w*|radiation|radiotherapy|"
             r"surgery|surgeries|mastectomy|lumpectomy|tamoxifen|letrozole|anastrozole|trastuzumab|herceptin|pertuzumab|"
             r"aromatase inhibitors?|endocrine|hormon(?:e|al) therap(?:y|ies)|immunotherapy|inhibitors?|olaparib)")
# "treatment records", "therapy fields", "radiation data" are data questions, not clinical ones.
TREAT_NOT_DATA = (r"(?![\s-]+(?:data|records?|history|histories|fields?|columns?|variables?|information|info|status|"
                  r"annotations?|exposure|codes?|dates?|timing|types?)\b)")
TREATMENT_REF = TREATMENT + r"\b" + TREAT_NOT_DATA

SURV_PREFIX = (r"(?:(?:overall|disease[- ]free|progression[- ]free|relapse[- ]free|recurrence[- ]free|event[- ]free|"
               r"metastasis[- ]free|5[- ]year|five[- ]year|10[- ]year|ten[- ]year)\s+)?")
OUTCOME = r"(?:survival|prognos[ie]s|outcomes?|mortality|life expectancy|recurrence|relapse)"
# "survival data", "survival coverage", "survival analysis" are about the data layer, not patients' outcomes.
NOT_DATA = (r"(?![\s-]+(?:data|records?|coverage|information|info|follow[- ]?up|files?|layers?|analys[ie]s|annotations?|"
            r"status|fields?|columns?|variables?|cohort|samples?|counts?|labels?|tables?|endpoints?|events?)\b)")
COMPARATIVE = (r"(?:better|worse|worst|poorer|poorest|best|longer|shorter|higher|lower|improved|reduced|inferior|superior|"
               r"favou?rable|unfavou?rable|excellent|dismal|grim)")

MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE = (r"(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2}|" + MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}|"
        r"\d{1,2}(?:st|nd|rd|th)?\s+" + MONTH + r",?\s+\d{4})")

# Words that frame a claim as a question about the data rather than about patients.
# Used only by rules marked readiness_exempt.
READINESS = re.compile(
    r"\b(?:recorded|records?|available|availability|missing|captured|documented|populated|exists?|enough|sufficient|"
    r"adequate|feasib\w*|coverage|how many|number of|count of|fields?|columns?)\b", re.I)


RULES = (
    # ======================= invalid input =======================
    # (Empty, symbol-only and over-long text are handled in check.py.)
    # WHY: a negative count or percentage cannot be true. The engine reads
    # "-20 percent" as "20 percent" and gives a verdict with a number, so stop it here.
    # Percentages over 100 are left to the engine, which already rejects them.
    # FP: none known; ranges such as "10-20 percent" pass (digit before the hyphen).
    Rule("invalid_negative_number", "invalid_input", "the claim uses a negative count or percentage, which cannot be true", _c(
        r"(?<![\w.,-])-\s?\d[\d,]*(?:\.\d+)?\s*(?:%|percent\b|per cent\b)",
        r"\b(?:at least|at most|more than|fewer than|less than|over|under|about|around|exactly|only)\s+-\s?\d",
        r"(?<![\w.,-])-\s?\d[\d,]*\s+(?:samples?|patients?|tumou?rs?|cases?|deaths?|events?)\b",
    )),

    # ======================= prompt injection =======================
    # WHY: report text is untrusted. A "claim" that tells the system to drop its
    # checks, change verdicts or reveal secrets must not be obeyed or scored.
    # FP: none known. "Ignoring the earlier AJCC rules, most tumors are stage II"
    # passes because "rules" alone is not a target word.
    Rule("injection_override", "prompt_injection_suspected", "tries to override the tool's instructions", _c(
        r"\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(?:instructions?|guardrails?|system prompt|prompts?|"
        r"safety (?:rules|checks?|filters?))\b",
        r"\byou are now\b", r"\bpretend (?:to be|you are)\b", r"\bjailbreak\w*",
        r"\bact as (?:an?|the|my) (?:ai|assistant|system|admin\w*|developer|unrestricted|different)\b",
        r"\b(?:dan|developer|god) mode\b", r"\bnew instructions?\s*:", r"\bfrom now on,? (?:you|always|only)\b",
        # Same request in Spanish, French, Portuguese, Italian, German (accents are folded before matching).
        r"\bignor(?:a|e|ez|en|ar|er)\w*\s+(?:todas\s+|toutes\s+|tutte\s+)?(?:las\s+|les\s+|as\s+|le\s+)?"
        r"(?:instrucciones|instructions|instrucoes|istruzioni)\b",
        r"\bignorier\w*\s+[^.\n]{0,30}\banweisungen\b",
    )),
    # WHY: role markers and chat-template tokens are how injected text pretends to be the system.
    # FP: none known; "the AJCC staging system: ..." does not start with "system:".
    Rule("injection_role_marker", "prompt_injection_suspected", "imitates a system or assistant message", _c(
        r"^\s*(?:system|assistant|developer)\s*:", r"<\s*/?\s*(?:system|assistant|user|instructions?)\s*>",
        r"\[\s*/?\s*(?:inst|system)\s*\]", r"<\|[a-z_]+\|>",
    )),
    # WHY: nothing in a report has a reason to ask for keys or the system prompt.
    Rule("injection_secrets", "prompt_injection_suspected", "asks for secrets or the system prompt", _c(
        r"\b(?:reveal|print|show|output|leak|send|give me|tell me|display|dump|expose|share)\b[^.\n]{0,40}"
        r"\b(?:api[ _-]?keys?|secrets?|passwords?|credentials?|access tokens?|auth tokens?|\.env\b|environment variables?|"
        r"system prompt)",
        r"\b(?:clave|cle|chave|schlussel|chiave)\s+(?:de\s+|der\s+|della\s+)?api\b", r"\bapi[- ]?schlussel\b",
    )),
    # WHY: a claim that dictates its own verdict ("mark this claim as supported")
    # games the audit; it is not a statement about the data.
    # FP: a report sentence such as "Do not check the slides manually" is blocked; rare in claim lists.
    Rule("injection_verdict", "prompt_injection_suspected", "tries to dictate the verdict", _c(
        r"\b(?:mark|label|rate|set|classify|treat|report|return|output)\s+(?:this|these|that|all|every|each|the following|the)"
        r"\s+(?:claims?|findings?|statements?|results?)\s+(?:as|to)\b",
        r"\b(?:always|just|only)\s+(?:answer|say|respond|output|reply)\b",
        r"\b(?:do not|don't|dont)\s+(?:check|verify|validate|flag|block|audit|review)\s+(?:this|these|that|the|any)\b",
    )),
    # WHY: claim_text is shown in the web app; script or event-handler markup is
    # aimed at the viewer's browser, not at the data.
    Rule("injection_markup", "prompt_injection_suspected", "contains script or HTML event markup", _c(
        r"<\s*script\b", r"\bjavascript\s*:", r"\bon(?:error|load|click|mouseover)\s*=", r"<\s*iframe\b",
    )),

    # ======================= identifying information =======================
    # WHY: the release has no names or contact details; any that appear came from
    # the uploader and must not be processed or stored (RULES.md: no PHI).
    # FP: three numbers written "123 456 7890" in a row look like a phone number.
    # Counts are normally written with commas or words between them.
    Rule("phi_contact", "phi_like_input", "contains contact details (an email, phone or social security number)", _c(
        # The lookbehind starts a match only at the beginning of a token, which keeps
        # this fast on huge input (no retry at every character of a long word).
        r"(?<![a-z0-9._%+-])[a-z0-9._%+-]{1,64}@[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63}){0,8}\.[a-z]{2,24}\b",
        r"(?<![\d,.])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?![\d,])",
        r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)",
    )),
    # WHY: record numbers identify a person. Fires only when an actual value
    # follows, so "medical record numbers are absent" still passes.
    Rule("phi_record_number", "phi_like_input", "contains a medical record or ID number", _c(
        r"\b(?:mrn|medical record(?: number| no\.?| #)?|hospital (?:number|no\.?|id)|nhs (?:number|no\.?)|ssn|"
        r"social security(?: number| no\.?)?|insurance (?:number|id))\b\s*[:#]?\s*(?:is\s+)?[a-z0-9-]*\d",
    )),
    # WHY: exact dates of birth, death or admission identify people (HIPAA safe
    # harbor lists them). Only a FULL date next to the event word fires.
    # FP: "date of birth is recorded for most patients" passes (no date value).
    # An aggregate window written as a full date ("diagnosed on 2001-01-01 or
    # later") is blocked; write the year instead.
    Rule("phi_dates", "phi_like_input", "contains an exact personal date (birth, death or visit)", _c(
        r"(?:\bdob\b|\bd\.o\.b\.?|\bdate of birth\b|\bbirth ?date\b|\bbirthday\b|\bborn(?: on)?\b)[^.\n]{0,20}?" + DATE,
        r"\b(?:died|deceased|admitted|discharged|diagnosed|seen|operated)\s+on\s+" + DATE,
        r"\bdate of (?:death|diagnosis|admission|discharge|surgery)\s*(?:is|was|:|=|of)?\s*" + DATE,
    )),
    # WHY: a personal name with a title, or "patient named X", is direct PHI.
    # FP: "Dr." is deliberately left out so citations such as "Dr. Perou's PAM50
    # labels" pass. The cost: a name written with no title is not caught.
    Rule("phi_name", "phi_like_input", "contains a personal name", _c(
        r"\b(?:Mr|Mrs|Ms|Miss|Mx)\.?\s+[A-Z][a-z'-]+",
        r"(?i:\b(?:patient|woman|man|person|participant|donor|subject|lady)\s+(?:named|called)\s+)[A-Z][a-z]+",
        r"(?i:\b(?:patient'?s?|her|his|their)\s+(?:full\s+|real\s+)?name\s*(?:is|was|:|=)\s*)[A-Z][a-z]+",
        flags=0,
    ), on_original=True),
    # WHY: a street address locates a person.
    Rule("phi_address", "phi_like_input", "contains a street address", _c(
        r"\b\d{1,5}\s+(?:[a-z]+\s+){1,3}(?:street|avenue|road|boulevard|lane|terrace)\b",
        r"\b\d{1,5}\s+(?:[a-z]+\s+){1,3}(?:st|ave|rd|blvd)\.",
    )),

    # ======================= re-identification =======================
    # WHY: RULES.md forbids attempts to re-identify anyone.
    # FP: a statement ABOUT privacy ("the release prevents re-identification") is
    # blocked too. It cannot be checked against the data, so little is lost.
    # "de-identified" does NOT match.
    Rule("reid_terms", "reidentification_blocked", "request to re-identify or de-anonymise people", _c(
        r"\bre-?identif\w*", r"\bde-?anonymi[sz]\w*", r"\bunmask\w*",
    )),
    # WHY: asking who a person is, or for a real name, is re-identification even
    # without the word. "Identify samples with missing RNA" (a cohort filter)
    # does NOT match: the rule needs a single person or an identity word.
    Rule("reid_identity", "reidentification_blocked", "request for a person's identity", _c(
        r"\bwho\s+(?:is|was|are|were)\s+(?:this|that|the|these|those)\s+(?:%s|%s)\b(?![\s-]+%s)" % (PERSON, PERSONS, GROUP_WORDS),
        r"\b(?:identit(?:y|ies)|real names?|actual names?|true names?|full names?)\s+of\s+"
        r"(?:the\s+|this\s+|that\s+|these\s+|those\s+|each\s+|any\s+)?(?:%s|%s)\b" % (PERSON, PERSONS),
        r"\b(?:identify|locate|track down|trace|contact|name)\s+(?:the|this|that|which)\s+(?:specific\s+|individual\s+|actual\s+|real\s+)?"
        r"%s\b(?![\s-]+%s)" % (PERSON, GROUP_WORDS),
        r"\bidentif\w*\s+[^.\n]{0,30}\b(?:by name|personally|in person)\b",
        r"\bconfirm\w*\s+(?:their\s+|the\s+|patients'?\s+)?identit(?:y|ies)\b",
    )),
    # WHY: linking records to outside sources about individuals is the classic
    # re-identification route, and RULES.md names it.
    # FP: external DATABASES (COSMIC, ClinVar, METABRIC) are not listed, so
    # annotation and cohort-level comparisons pass. "matched to external records"
    # is blocked even if the author meant something harmless.
    Rule("reid_linkage", "reidentification_blocked", "request to link records to outside sources about people", _c(
        r"\bobituar\w*", r"\bvoter (?:rolls?|records?|registration|lists?|files?)\b", r"\bsocial media\b",
        r"\b(?:facebook|linkedin|twitter|instagram|tiktok)\b", r"\bgenealog\w*", r"\bancestry\.com\b", r"\b23andme\b",
        r"\bgedmatch\b", r"\bcourt records?\b", r"\bpeople[- ]search\b", r"\bwhite pages\b",
        r"\b(?:link|match|cross-?reference|merge|combine|look\s*up|lookup|search|compare|join)\w*\b[^.\n]{0,50}"
        r"\b(?:(?:outside|external|third[- ]party|public|state|cancer)\s+(?:records?|registr(?:y|ies))|"
        r"(?:hospital|insurance|electronic health|ehr|emr|medical|personal|identifiable)\s+(?:records?|databases?|files?))\b",
    )),
    # WHY: where someone lives or how to reach them only matters for finding a person.
    Rule("reid_location", "reidentification_blocked", "request for where a person lives or how to reach them", _c(
        r"\bhome address\w*",
        r"\bwhere\s+(?:she|he|they|this patient|the patient|that patient)\s+(?:lives?|lived|works?|worked)\b",
        r"\b(?:phone numbers?|email address(?:es)?|contact details|contact information)\s+(?:of|for)\s+"
        r"(?:the\s+|this\s+|that\s+|each\s+|these\s+)?(?:%s|%s)\b" % (PERSON, PERSONS),
    )),

    # ======================= individual-level requests =======================
    # WHY: the contract allows cohort-level questions only. A participant barcode
    # (TCGA-XX-XXXX) points at one person.
    # FP: a data-quality claim about one barcode ("TCGA-A7-A0DB-01 has RNA but no
    # protein data") is blocked although it is a fair QC question. A tissue-site
    # prefix alone ("TCGA-BH samples") does not match. GDC UUIDs are not matched.
    Rule("individual_barcode", "individual_level_request_blocked", "the claim names a single participant barcode", _c(
        r"\btcga-[a-z0-9]{2}-[a-z0-9]{4}\b",
    )),
    # WHY: "patient #12", "case id 0042" single out one person.
    # FP: "patient number 1,097" used to mean a COUNT is blocked; "1,097 patients" passes.
    Rule("individual_patient_id", "individual_level_request_blocked", "the claim names a single patient by number", _c(
        r"\b(?:patient|case|participant|donor|subject)\s*(?:id|identifier|number|no\.?|#)\s*[:#=]?\s*[a-z0-9-]*\d",
        r"\b(?:patient|participant|donor|subject)\s+#?\d+\b(?!\s*(?:%|percent|samples?|patients?|tumou?rs?|cases?|years?))",
    )),
    # WHY: "this patient", "a specific woman", "the only male patient" ask about one person.
    # FP: "the same patient" and "a single patient" are deliberately left out:
    # "several samples come from the same patient" is a real data question.
    # "an individual patient" inside a privacy statement is blocked.
    Rule("individual_singular", "individual_level_request_blocked", "the claim is about one specific person", _c(
        r"\b(?:this|that|a specific|one specific|a particular|one particular|an individual|the individual)\s+%s(?:'s)?\b"
        r"(?![\s-]+%s)" % (PERSON, GROUP_WORDS),
        r"\bthe only\s+(?:[\w-]+\s+){0,3}?(?:%s|case)\b(?![\s-]+level)" % PERSON,
        r"\b(?:full|complete|entire|raw)\s+(?:clinical\s+|medical\s+)?(?:records?|history|histories|chart|file)\s+(?:of|for)\s+"
        r"(?:this|that|the|a|one|each|every)\s+%s\b" % PERSON,
    )),
    # WHY: dumping identifiers turns an aggregate tool into a per-person lookup.
    # Only fires on an imperative ("List the patient IDs..."), so "a list of
    # sample IDs is in the manifest" passes.
    # FP: a QC request "List the sample barcodes missing RNA" is blocked.
    Rule("individual_id_dump", "individual_level_request_blocked", "the claim asks for a list of personal identifiers", _c(
        r"(?:^|\bplease\s+|\bcan you\s+|\bcould you\s+|\bnow\s+)(?:list|print|export|dump|output|give me|return|enumerate|send)\b"
        r"[^.\n]{0,40}\b(?:patient|participant|donor|case|sample)s?\s*(?:ids?|identifiers?|barcodes?|names?|uuids?)\b",
    )),

    # ======================= clinical claims =======================
    # Out of scope (RULES.md): diagnosis, treatment recommendation, patient risk
    # score, claims of clinical validity, regulatory status or real-world readiness.
    # Contract: clinical claims never get a number or a supported verdict.

    # WHY: "patients should receive X" is a treatment recommendation.
    # FP: "patients should receive equal weight" is blocked. "Patients should be
    # treated as the unit of analysis" passes (the "as" lookahead).
    # "Analysts should check whether chemotherapy agents were recorded" is
    # blocked ("agents" is not a data noun); "...treatment records..." passes.
    Rule("clinical_recommendation", "clinical_claim_blocked", "treatment recommendation", _c(
        r"\b(?:patients?|women|men|people|individuals?)\b[^.\n]{0,60}?\b(?:should|must|ought to|needs? to|is advised to|are advised to)"
        r"\s+(?:not\s+)?(?:be\s+)?(?:receive[ds]?|undergo|treated|prescribed|offered|avoid|skip|forgo|switch to)\b(?!\s+as\b)",
        r"\b(?:should|must|ought to|needs? to|is advised to|are advised to|recommend\w*|advis\w*|prescrib\w*)\b[^.\n]{0,40}?\b" + TREATMENT_REF,
        # (?!to\b): "responded best to hormone therapy" is a response claim, labelled by clinical_response.
        r"\b(?:best|preferred|optimal|first[- ]line|second[- ]line|standard[- ]of[- ]care|right|appropriate|ideal|recommended)\s+"
        r"(?!to\b)(?:\w+\s+){0,2}?" + TREATMENT_REF,
        # Question form and treatment-first form: "Should a patient with stage II get
        # radiation?", "Is chemotherapy the right choice for...?"
        r"\bshould\s+(?:a|an|the|this|my|these|those)?\s*(?:%s|%s)\b[^.\n]{0,60}?\b(?:receive|get|take|undergo|be treated|"
        r"be given|be offered|start|stop|avoid)\b(?!\s+as\b)" % (PERSON, PERSONS),
        TREATMENT_REF + r"[^.\n]{0,30}?\b(?:the\s+)?(?:right|best|better|correct|appropriate|preferred|optimal)\s+"
        r"(?:choice|option|treatment|approach|course)\b",
        # Advice for a person: "What would you advise for a woman with HER2-positive disease?"
        r"\b(?:advi[sc]e|recommend\w*|suggest\w*)\s+(?:for|to)\s+(?:a|an|this|that|my|the)\s+%s\b" % PERSON,
        r"\bguide\s+(?:patient\s+)?(?:treatment|therapy|care)\b",
        r"\b(?:guide|inform|drive|support|change)\s+(?:patient\s+|clinical\s+)?(?:treatment|therapy|therapeutic|clinical|care|management)"
        r"\s+(?:decisions?|choices?|selection|planning)\b",
    )),
    # WHY: "which treatment works" asks the tool to choose a therapy.
    # Readiness-exempt, so "which treatment fields are recorded" passes.
    # FP: "Which chemotherapy agents appear most often?" is blocked (no readiness word).
    Rule("clinical_which_treatment", "clinical_claim_blocked", "request to choose a treatment", _c(
        r"\bwhich\s+(?:\w+\s+){0,2}?" + TREATMENT_REF,
    ), readiness_exempt=True),
    # WHY: "Drug X improves survival" is a treatment-effect claim (contract mock-004).
    # FP: "Adding protein data reduces the survival cohort" passes (NOT_DATA).
    # "...reduces survival among stage IV samples", meaning fewer samples, is blocked.
    Rule("clinical_efficacy", "clinical_claim_blocked", "treatment effect or survival-benefit claim", _c(
        r"\b(?:improv\w*|prolong\w*|extend\w*|increas\w*|boost\w*|worsen\w*|shorten\w*|reduc\w*|decreas\w*|lower\w*|harm\w*)"
        r"\s+(?:the\s+|patient\s+|patients'?\s+)?" + SURV_PREFIX + OUTCOME + NOT_DATA,
        r"\bbenefit\w*\s+(?:\w+\s+){0,2}?from\b[^.\n]{0,40}?" + TREATMENT_REF,
        r"\bcure[sd]?\b|\bcurative\b|\bcurable\b",
        # Treatment named before an effect verb: "tamoxifen works better", "the drug failed".
        TREATMENT_REF + r"[^.\n]{0,40}?\b(?:works?|worked|outperform\w*|is better|was better|is superior|was superior|"
        r"benefits?|benefited|helps?|helped|fail(?:s|ed)?|succeed\w*)\b",
    )),
    # WHY: "efficacy", "more effective" are clinical only when a treatment is
    # named, so "RNA is more effective than protein for subtype calls" passes.
    Rule("clinical_effectiveness", "clinical_claim_blocked", "treatment effectiveness claim", _c(
        r"\b(?:efficacy|effectiveness|efficacious|(?:more|less|most|least|highly|very|not)\s+effective|"
        r"effective\s+(?:against|in treating|for treating))\b",
    ), requires=re.compile(r"\b" + TREATMENT_REF, re.I)),
    # WHY: treatment response is a clinical outcome, and the release has no
    # response measure to check it against (practice brief: "responded best to
    # hormone therapy"). Readiness-exempt: "response to therapy is recorded for
    # fewer than 100 patients" passes.
    Rule("clinical_response", "clinical_claim_blocked", "treatment response claim", _c(
        r"\b(?:respond\w*|response|responsive\w*|resistan\w*|sensitiv\w*|refractory)\b[^.\n]{0,40}?\b(?:to|from|of|with)\b"
        r"[^.\n]{0,30}?\b" + TREATMENT_REF,
    ), readiness_exempt=True),
    # WHY: "basal tumors have worse survival" is a prognostic claim about patients'
    # outcomes. Counting deaths ("at least 30 deaths among ER-negative tumors") does
    # not match and stays an ordinary data question.
    # FP: "higher survival among stage I samples", meaning MORE SAMPLES WITH
    # SURVIVAL DATA, is blocked; "higher survival coverage" passes.
    Rule("clinical_outcome_comparison", "clinical_claim_blocked", "patient outcome or prognosis comparison", _c(
        r"\b" + COMPARATIVE + r"\s+" + SURV_PREFIX + r"(?:survival|prognos[ie]s|outcomes?|mortality|life expectancy)" + NOT_DATA,
        r"\b(?:survival|prognos[ie]s|outcomes?|mortality|life expectancy)\s+(?:is|was|are|were|appears?|seems?)\s+(?:\w+\s+)?"
        + COMPARATIVE + r"\b",
        r"\b(?:more|less|most|least)\s+likely\s+to\s+(?:die|survive|relapse|recur|respond|progress|metastasi[sz]e|benefit|be cured)\b",
        r"\b(?:higher|lower|increased|decreased|elevated|reduced|greater|smaller|excess)\s+(?:\w+\s+)?(?:risk|odds|hazard|chance|likelihood)"
        r"\s+of\s+(?:death|dying|recurrence|relapse|progression|metastas[ie]s|mortality|cure|response)\b",
    )),
    # WHY: "is prognostic", "predicts recurrence" are clinical-validity claims.
    # Readiness-exempt: "survival data is sufficient to study prognostic factors"
    # and "enough events to predict outcomes" pass as feasibility questions.
    # FP: "PAM50 is a prognostic label in this release" (a description) is blocked.
    Rule("clinical_prognosis", "clinical_claim_blocked", "prognosis or outcome-prediction claim", _c(
        r"\bprognos\w*",
        r"\brisk of (?:death|dying|recurrence|relapse|progression|metastas[ie]s)\b",
        r"\b(?:predict\w*|forecast\w*)\b[^.\n]{0,40}?\b(?:survival|death|mortality|outcomes?|recurrence|relapse|response|benefit)\b" + NOT_DATA,
    ), readiness_exempt=True),
    # WHY: RULES.md bans patient risk scores outright.
    # FP: "no risk score field is recorded" is blocked too. Not readiness-exempt
    # on purpose: the rule names an output the event bans.
    Rule("clinical_risk_score", "clinical_claim_blocked", "patient risk score", _c(
        r"\b(?:risk|recurrence|prognostic)\s+(?:scores?|calculators?|predictions?|signatures?|stratification|models?)\b",
    )),
    # WHY: diagnosis is out of scope. Only diagnostic CAPABILITY or diagnosing a
    # person fires. "Age at diagnosis", "diagnosed at stage II", "diagnosed with
    # lobular carcinoma" and "diagnostic slides" are data fields and pass.
    # FP: "pathologists used the slides to diagnose histology" (provenance) is blocked.
    Rule("clinical_diagnosis", "clinical_claim_blocked", "diagnosis or diagnostic-capability claim", _c(
        r"\b(?:can|could|will|would|to|able to|used to|helps?(?: to)?|in order to)\s+diagnos\w*",
        r"\bdiagnostic\s+(?:accuracy|performance|value|utility|tool|test|model|sensitivity|specificity|power|yield|aid|decisions?)\b",
        r"\bdiagnos\w*\s+(?:of\s+|for\s+)?(?:this|that|the|a|her|his)\s+%s\b(?![\s-]+%s)" % (PERSON, GROUP_WORDS),
        r"\b(?:does|did|do)\s+(?:this|that|the)\s+%s\s+have\b" % PERSON,
    )),
    # WHY: claims of clinical validity, regulatory status or real-world readiness
    # are out of scope (RULES.md).
    # FP: a disclaimer inside a report ("not for clinical use") is blocked. It is
    # not a checkable data claim, so the cost is a blocked card, not a wrong
    # verdict. "Clinically relevant fields (ER, PR, HER2)" passes.
    Rule("clinical_validity", "clinical_claim_blocked", "claim of clinical validity, regulatory status or real-world readiness", _c(
        r"\bclinically\s+(?:valid\w*|useful|actionable|proven|approved|ready|significant)\b",
        r"\bclinical\s+(?:validity|utility|grade|deployment|decision[- ]making)\b",
        r"\b(?:fda|ema)[- ]?(?:approv\w*|clear\w*)", r"\bce[- ]mark(?:ed)?\b",
        r"\bregulatory\s+(?:approv\w*|complian\w*|clearance|grade|ready|submission)\b",
        r"\b(?:hipaa|gdpr|clia)[- ]?(?:complian\w*|certified|approved)\b",
        r"\bproduction[- ]ready\b", r"\bready for (?:clinical|production|patient|bedside) use\b", r"\bfor (?:clinical|bedside) use\b",
        r"\bsafe\s+(?:for|to use (?:on|in|with))\s+patients\b",
    )),
    # WHY: the same clinical requests written in Spanish, Portuguese, French,
    # German or Italian. The engine cannot parse these languages, so a missed
    # one ends as "data cannot answer"; blocking says why instead.
    # FP: a non-English data question that uses one of these phrases (for example
    # "que tratamiento se registra") is blocked. Only these five languages are covered.
    Rule("clinical_other_language", "clinical_claim_blocked", "clinical claim written in another language", _c(
        r"\bmejora\w*\s+(?:la\s+)?supervivencia\b", r"\bmelhora\w*\s+(?:a\s+)?(?:sobrevida|sobrevivencia)\b",
        r"\bameliore\w*\s+(?:la\s+)?survie\b", r"\bverbesser\w*\s+(?:das\s+)?uberleben\b", r"\bmiglior\w*\s+(?:la\s+)?sopravvivenza\b",
        r"\b(?:debe|deben|deberia|deberian|deve|devem|deveria|doit|doivent|devrait|devraient|dovrebbe\w*)\s+(?:\w+\s+){0,2}?(?:recibir|receber|recevoir|ricevere)\b",
        r"\bsollte\w*\s+[^.\n]{0,40}\berhalten\b",
        r"\b(?:que|qual|quel|quelle|quels|quelles|quale|welche)\s+(?:\w+\s+){0,2}?(?:tratamiento|tratamento|traitement|trattamento|terapia|therapie|behandlung)\b",
        r"\bdiagnosticar\b", r"\bdiagnostiquer\b", r"\bdiagnostizieren\b",
        r"\b(?:puntuacion|pontuacao|score)\s+de\s+(?:riesgo|risco|risque)\b", r"\brisikoscore\b",
    )),
)

RULE_IDS = tuple(r.id for r in RULES)
assert len(set(RULE_IDS)) == len(RULE_IDS), "duplicate rule id"
assert all(r.flag in FLAG_ORDER for r in RULES), "rule uses a flag outside FLAG_ORDER"
