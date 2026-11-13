// The suggested next step for the whole report, the reasons behind it, who must review it, and the
// recorded decision. Logic only (no page building), so review.json can use it too.
import { store, plural } from './util.js';
import { state, findings, isBlocked, cannotAnswer, reviewStatus, decisions, effectiveVerdict, ROLES } from './state.js';

export const STEPS = {
  proceed: { label: 'Proceed', icon: '✓', text: 'Every claim matches the data and nothing is flagged for review.' },
  proceed_review: { label: 'Proceed with review', icon: '!', text: 'Every claim matches the data, but a person must check the flagged ones before the report is used.' },
  fix: { label: 'Fix a problem', icon: '✕', text: 'At least one number in the report does not match the data. Correct it before anyone relies on the report.' },
  narrow: { label: 'Narrow the question', icon: '?', text: 'No number is wrong, but some claims cannot be settled with this data. Reword them, or narrow them to what the data holds.' },
  stop: { label: 'Stop', icon: '⛔', text: 'None of the claims can be checked with this data, so the report cannot be trusted on these points.' },
};
export const STEP_ORDER = ['proceed', 'proceed_review', 'fix', 'narrow', 'stop'];
const outOfScope = (f) => isBlocked(f) || cannotAnswer(f);

// Which step the findings point to, and why (counts with the claims behind them).
export function analyse() {
  const all = findings();
  const ids = (pred) => all.filter(pred).map((f) => f.id);
  const ev = effectiveVerdict;
  const g = {
    contradicted: ids((f) => ev(f) === 'contradicted'),
    insufficient: ids((f) => ev(f) === 'insufficient_evidence' && !outOfScope(f)),
    cannot: ids((f) => !isBlocked(f) && cannotAnswer(f)),
    blocked: ids(isBlocked),
    review: ids((f) => f.needs_human_review && ['pending', 'more_evidence_requested'].includes(reviewStatus(f))),
    overridden: ids((f) => reviewStatus(f) === 'overridden'),
    supported: ids((f) => ev(f) === 'supported'),
  };
  let step;
  if (!all.length || all.every(outOfScope)) step = 'stop';
  else if (g.contradicted.length) step = 'fix';
  else if (all.some((f) => ev(f) === 'insufficient_evidence')) step = 'narrow';
  else if (g.review.length) step = 'proceed_review';
  else step = 'proceed';

  const n = (k) => g[k].length;
  const reasons = [
    ['contradicted', plural(n('contradicted'), 'claim') + ' contradicted by the data'],
    ['insufficient', plural(n('insufficient'), 'claim') + ' without enough evidence to settle'],
    ['cannot', plural(n('cannot'), 'claim') + ' the data cannot answer'],
    ['blocked', plural(n('blocked'), 'claim') + ' stopped by a safety check'],
    ['review', plural(n('review'), 'claim still needs', 'claims still need') + " a person's review"],
    ['overridden', plural(n('overridden'), 'verdict') + ' changed by a reviewer'],
    ['supported', plural(n('supported'), 'claim') + ' supported by the data'],
  ].filter(([k]) => n(k)).map(([k, text]) => ({ key: k, text, ids: g[k] }));

  const reviewers = [];
  const research = [];
  if (n('contradicted')) research.push('correct ' + plural(n('contradicted'), 'contradicted claim'));
  if (n('insufficient')) research.push('reword or narrow ' + plural(n('insufficient'), 'claim') + ' the data cannot settle');
  const flaggedOk = g.review.filter((id) => !g.blocked.includes(id)).length;
  if (flaggedOk) research.push('check ' + plural(flaggedOk, 'flagged result'));
  if (research.length) reviewers.push({ role: 'researcher', why: cap(research.join('; ')) + '.' });
  if (n('blocked')) reviewers.push({ role: 'datause', why: `Confirm the ${plural(n('blocked'), 'claim')} stopped by a safety check stay out of the report.` });
  const rel = (state.data && state.data.data_release) || {};
  const unverified = rel.checksum_status && rel.checksum_status !== 'verified';
  if (n('cannot') || unverified) {
    const parts = [];
    if (unverified) parts.push('the data files were not confirmed against their checksums');
    if (n('cannot')) parts.push(plural(n('cannot'), 'claim') + ' need a field the data does not have');
    reviewers.push({ role: 'engineer', why: cap(parts.join('; ')) + '.' });
  }
  reviewers.push({ role: 'leader', why: 'Approve the next step for the report.' });
  return { step, groups: g, reasons, reviewers, count: all.length };
}
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

// Every distinct limitation sentence across the findings, with the claims that carry it.
export function keyLimitations() {
  const seen = new Map();
  for (const f of findings()) {
    for (const s of String(f.limitation || '').split(/(?<=[.!?])\s+(?=[A-Z])/)) {
      const t = s.trim();
      if (!t) continue;
      if (!seen.has(t)) seen.set(t, []);
      seen.get(t).push(f.id);
    }
  }
  return [...seen].map(([text, ids]) => ({ text, finding_ids: ids }));
}

// The recorded decision belongs to one report: ignore one saved for different findings.
const keyOf = () => (state.data ? (state.data.report_title || '') + '|' + findings().map((f) => f.id).join(',') : '');
export function savedStep() {
  const s = store('en.nextstep');
  return s && s.key === keyOf() && STEPS[s.step] ? s : null;
}
export function recordStep(step, reason, role) {
  const rec = { key: keyOf(), step, suggested: analyse().step, reason: reason || null, role, at: new Date().toISOString() };
  store('en.nextstep', rec);
  return rec;
}
export function clearStep() { store('en.nextstep', null); }

// The next-step part of review.json.
export function nextStepExport() {
  const a = analyse(), s = savedStep(), dec = decisions();
  return {
    suggested_step: STEPS[a.step].label,
    recorded: !!s,
    chosen_step: s ? STEPS[s.step].label : null,
    differs_from_suggestion: s ? s.step !== s.suggested : null,
    reason_for_different_step: s ? s.reason : null,
    suggested_when_recorded: s ? STEPS[s.suggested].label : null,
    reviewer_role: s ? (ROLES[s.role] || {}).name || null : null,
    decided_at: s ? s.at : null,
    reasons: a.reasons.map((r) => ({ text: r.text, count: r.ids.length, finding_ids: r.ids })),
    reviewers_needed: a.reviewers.map((r) => ({ role: ROLES[r.role].name, why: r.why })),
    key_limitations: keyLimitations(),
    overridden_verdicts: findings().filter((f) => reviewStatus(f) === 'overridden').map((f) => ({
      finding_id: f.id, machine_verdict: f.verdict, reviewer_verdict: (dec[f.id] || {}).verdict || null,
      note: (dec[f.id] || {}).note || null, reviewer_role: (dec[f.id] || {}).reviewer_role || null })),
  };
}
