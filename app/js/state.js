import { store } from './util.js';

export const BLOCKED = ['clinical_claim_blocked', 'individual_level_request_blocked', 'reidentification_blocked',
  'phi_like_input', 'prompt_injection_suspected', 'invalid_input'];
export const FLAG_TEXT = {
  clinical_claim_blocked: 'Clinical claim blocked',
  individual_level_request_blocked: 'Individual request blocked',
  reidentification_blocked: 'Re-identification blocked',
  phi_like_input: 'Personal data in input',
  prompt_injection_suspected: 'Suspicious instruction in input',
  invalid_input: 'Invalid input',
  data_cannot_answer: 'Data cannot answer',
  low_event_count: 'Low event count',
};
export const VERDICT = {
  supported: { label: 'Supported', icon: '✓' },
  contradicted: { label: 'Contradicted', icon: '✕' },
  insufficient_evidence: { label: 'Insufficient evidence', icon: '?' },
};
export const state = {
  data: null, source: '', error: null, live: false, mode: null, extract: null, reportText: '', reportTitle: '', pdfOk: null,
  filters: store('en.filters') || { q: '', verdict: '', review: false, flag: '', sort: 'order' },
  selected: [], scroll: 0,
};

export const dataParam = () => new URLSearchParams(location.search).get('data');
export const DEMO_FILE = 'out/practice_audit.json';
export function dataUrl(file) {
  const p = file || dataParam();
  return new URL('../' + (p ? p.replace(/^\/+/, '') : DEMO_FILE), location.href).href;
}

export function normalize(d) {
  if (!d || !Array.isArray(d.findings)) throw new Error('This file does not look like a findings file (no findings list).');
  d.findings.forEach((f, i) => {
    f.id = f.id || 'claim-' + String(i + 1).padStart(3, '0');
    f.evidence = f.evidence || {};
    f.cohort_trace = f.cohort_trace || [];
    f.guardrail_flags = f.guardrail_flags || [];
    f.next_actions = f.next_actions || [];
  });
  return d;
}
export async function loadData(file) {
  state.error = null;
  const url = dataUrl(file);
  try {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error('Could not load ' + url.replace(location.origin, '') + ' (HTTP ' + r.status + ').');
    state.data = normalize(await r.json());
    state.origin = 'file'; state.liveReport = null;
    state.source = url.replace(location.origin, '');
    state.selected = []; state.extract = null;
  } catch (e) {
    state.data = null;
    state.error = e instanceof SyntaxError ? 'The findings file is not valid JSON.' : e.message;
  }
  return !!state.data;
}
export function setData(d, source) { state.data = normalize(d); state.source = source; state.selected = []; state.error = null; }
export const demoExtract = () => ({
  claims: findings().map((f) => ({ text: f.claim_text, source: f.source_sentence || f.claim_text })),
  skipped: (state.data && state.data.skipped_sentences) || [],
});
export const extractData = () => state.extract || (state.data ? demoExtract() : null);

export const findings = () => (state.data ? state.data.findings : []);
export const byId = (id) => findings().find((f) => f.id === id);
export const isBlocked = (f) => f.guardrail_flags.some((x) => BLOCKED.includes(x));
export const cannotAnswer = (f) => f.guardrail_flags.includes('data_cannot_answer');
export const hasNumber = (f) => !isBlocked(f) && !cannotAnswer(f) && f.evidence.value != null;
export const minGroup = () => (state.data.interpretation_config || {}).min_group_size ?? 30;
export const minEvents = () => (state.data.interpretation_config || {}).min_events ?? 20;

// Role views: every role sees the same findings; a role only changes which details are shown.
// 'all' shows everything (the default, so a first-time viewer misses nothing). Limitations are never hidden.
export const ROLES = {
  all: { label: 'All details', sees: 'every detail for every role' },
  leader: { label: 'Program leader', name: 'program leader', sees: 'verdicts, the decision and a one-sentence result for each claim' },
  researcher: { label: 'Researcher', name: 'researcher', sees: 'adds correct values, calculations and the parts of each sentence' },
  datause: { label: 'Data-use reviewer', name: 'data-use reviewer', sees: 'adds limitations, review reasons, flags and safety messages' },
  engineer: { label: 'Data engineer', name: 'data engineer', sees: 'adds columns used, source files, checksums and the cohort trace' },
};
export const REVIEW_ROLES = ['leader', 'researcher', 'datause', 'engineer'];
export function getRole() { const r = store('en.role'); return ROLES[r] ? r : 'all'; }
export function setRole(r) {
  const role = ROLES[r] ? r : 'all';
  store('en.role', role);
  document.documentElement.dataset.role = role;
  return role;
}

export const decisions = () => store('en.decisions') || {};
// A claim stopped by a guardrail has no result to override. A reviewer may only accept it as
// insufficient evidence or ask for more evidence. Same rule and same message as build_review in
// src/export/audit_json.py (BLOCKED_OVERRIDE_ERROR).
export const BLOCKED_OVERRIDE_ERROR = 'a blocked claim cannot be overridden; accept it as insufficient evidence or ask for more evidence';
export function decisionAllowed(f, d) {
  if (!f || !d || !isBlocked(f)) return true;
  if (d.decision === 'reject') return false;
  return d.verdict == null || d.verdict === 'insufficient_evidence';
}
// Returns false, and saves nothing, when the decision is not allowed for this claim.
export function decide(id, patch) {
  const all = decisions();
  const next = Object.assign({}, all[id], patch, { at: new Date().toISOString() });
  const role = getRole();
  if (role !== 'all') next.reviewer_role = ROLES[role].name;
  if (!decisionAllowed(byId(id), next)) return false;
  all[id] = next;
  store('en.decisions', all);
  if (typeof window !== 'undefined') window.dispatchEvent(new Event('en:decided'));
  return true;
}
export const DECISION_TEXT = { approve: 'Accepted', reject: 'Overridden', more: 'More evidence requested' };
// pending | accepted | overridden | more_evidence_requested (same rule as the exporter's build_review)
export function reviewStatus(f) {
  const d = decisions()[f.id] || {};
  if (d.decision === 'more') return 'more_evidence_requested';
  if (d.decision === 'approve' && isBlocked(f)) return 'accepted'; // accepted as insufficient evidence
  if (d.decision === 'reject' || (d.verdict && d.verdict !== f.verdict)) return 'overridden';
  if (d.decision === 'approve') return 'accepted';
  return 'pending';
}
// The verdict after review: the reviewer's verdict when they overrode it, else the machine verdict.
export function effectiveVerdict(f) {
  return reviewStatus(f) === 'overridden' ? (decisions()[f.id] || {}).verdict || f.verdict : f.verdict;
}

// Throws Error(id + ': ' + BLOCKED_OVERRIDE_ERROR) if a saved decision overrides a blocked claim.
export function reviewJson() {
  const d = state.data, dec = decisions();
  const bad = findings().find((f) => !decisionAllowed(f, dec[f.id]));
  if (bad) throw new Error(bad.id + ': ' + BLOCKED_OVERRIDE_ERROR);
  const items = findings().map((f) => {
    const x = dec[f.id] || {}, st = reviewStatus(f);
    const accepted = x.decision === 'approve' ? (isBlocked(f) ? 'insufficient_evidence' : f.verdict) : null;
    const human = x.decision === 'more' ? null : (x.verdict || accepted);
    return {
      finding_id: f.id, claim_text: String(f.source_sentence || f.claim_text || ''), machine_verdict: f.verdict,
      needs_human_review: !!f.needs_human_review, review_reason: f.review_reason || null, status: st,
      human_decision: x.decision || null, human_verdict: human, note: x.note || null, reviewer_role: x.reviewer_role || null, decided_at: x.at || null,
    };
  });
  const counts = {}; ['pending', 'accepted', 'overridden', 'more_evidence_requested'].forEach((k) => { counts[k] = items.filter((i) => i.status === k).length; });
  return {
    review_version: '1',
    about: 'Human review of the claim verdicts in audit.json. Machine verdicts are never changed; the reviewer verdict is kept beside the original.',
    audit_file: 'audit.json', report_title: d.report_title || null, counts, items,
  };
}
export function saveFilters() { store('en.filters', state.filters); }
