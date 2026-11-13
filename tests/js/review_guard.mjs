// Checks the app's review rules in app/js/state.js without a browser.
// Run by tests/test_app_review_guard.py: node tests/js/review_guard.mjs
// Prints one JSON object with the observed results; the Python test asserts on it.
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

const mem = new Map();
globalThis.localStorage = {
  getItem: (k) => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => { mem.set(k, String(v)); },
  removeItem: (k) => { mem.delete(k); },
};

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const S = await import(pathToFileURL(path.join(root, 'app', 'js', 'state.js')).href);

const SECRET = 'highest protein responded best to therapy';
const finding = (id, verdict, flags) => ({ id, verdict, claim_text: id + ' text', guardrail_flags: flags, evidence: {}, next_actions: [], cohort_trace: [] });
const doc = () => ({
  report_title: 't.md',
  findings: [
    finding('claim-001', 'supported', []),
    finding('claim-002', 'contradicted', ['low_event_count']),
    Object.assign(finding('claim-003', 'insufficient_evidence', ['clinical_claim_blocked']), { claim_text: SECRET }),
  ],
});
const reset = () => { mem.clear(); S.setData(doc(), 'test'); };
const saved = (id) => (S.decisions()[id] || null);
const out = { flags: {} };

// Refusals on a blocked claim: decide() returns false and stores nothing.
reset();
out.reject = S.decide('claim-003', { decision: 'reject', verdict: 'supported', note: 'n' });
out.rejectSaved = saved('claim-003');
out.approveSupported = S.decide('claim-003', { decision: 'approve', verdict: 'supported' });
out.moreSupported = S.decide('claim-003', { decision: 'more', verdict: 'contradicted' });
out.bareVerdict = S.decide('claim-003', { verdict: 'supported' });
out.afterRefusals = saved('claim-003');

// Every blocking flag is guarded.
for (const flag of S.BLOCKED) {
  mem.clear();
  const d = doc(); d.findings[0].guardrail_flags = [flag]; S.setData(d, 'test');
  out.flags[flag] = S.decide('claim-001', { decision: 'reject', verdict: 'contradicted' });
}

// Allowed paths on a blocked claim.
reset();
out.accept = S.decide('claim-003', { decision: 'approve', verdict: 'insufficient_evidence', note: 'ok' });
out.acceptStatus = S.reviewStatus(S.byId('claim-003'));
out.acceptItem = S.reviewJson().items[2];
out.more = S.decide('claim-003', { decision: 'more', verdict: null });
out.moreStatus = S.reviewStatus(S.byId('claim-003'));
out.moreItem = S.reviewJson().items[2];

// Unblocked claims can still be overridden (low_event_count is not a block).
out.overrideOk = S.decide('claim-002', { decision: 'reject', verdict: 'supported' });
out.overrideStatus = S.reviewStatus(S.byId('claim-002'));

// A stale override saved before this rule existed: review.json refuses with the fixed message.
reset();
localStorage.setItem('en.decisions', JSON.stringify({ 'claim-003': { decision: 'reject', verdict: 'supported', note: 'my note' } }));
try { S.reviewJson(); out.staleError = null; } catch (e) { out.staleError = e.message; }
out.message = S.BLOCKED_OVERRIDE_ERROR;
out.secretInError = !!(out.staleError && (out.staleError.includes(SECRET) || out.staleError.includes('my note')));

console.log(JSON.stringify(out));
