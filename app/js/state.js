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
  data: null, source: '', error: null, live: false,
  filters: store('en.filters') || { q: '', verdict: '', review: false, flag: '', sort: 'order' },
  selected: [], scroll: 0,
};

export function dataUrl() {
  const p = new URLSearchParams(location.search).get('data');
  return new URL('../' + (p ? p.replace(/^\/+/, '') : 'out/findings.json'), location.href).href;
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
export async function loadData() {
  state.error = null;
  const url = dataUrl();
  try {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error('Could not load ' + url.replace(location.origin, '') + ' (HTTP ' + r.status + ').');
    state.data = normalize(await r.json());
    state.source = url.replace(location.origin, '');
    state.selected = [];
  } catch (e) {
    state.data = null;
    state.error = e instanceof SyntaxError ? 'The findings file is not valid JSON.' : e.message;
  }
  return !!state.data;
}
export function setData(d, source) { state.data = normalize(d); state.source = source; state.selected = []; state.error = null; }

export const findings = () => (state.data ? state.data.findings : []);
export const byId = (id) => findings().find((f) => f.id === id);
export const isBlocked = (f) => f.guardrail_flags.some((x) => BLOCKED.includes(x));
export const cannotAnswer = (f) => f.guardrail_flags.includes('data_cannot_answer');
export const hasNumber = (f) => !isBlocked(f) && !cannotAnswer(f) && f.evidence.value != null;
export const minGroup = () => (state.data.interpretation_config || {}).min_group_size ?? 30;
export const minEvents = () => (state.data.interpretation_config || {}).min_events ?? 20;

export const decisions = () => store('en.decisions') || {};
export function decide(id, patch) {
  const all = decisions();
  all[id] = Object.assign({}, all[id], patch, { at: new Date().toISOString() });
  store('en.decisions', all);
}
export const DECISION_TEXT = { approve: 'Approved', reject: 'Rejected', more: 'More information requested' };
export function saveFilters() { store('en.filters', state.filters); }
