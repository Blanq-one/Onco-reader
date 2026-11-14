// Live mode: talks to the local server when there is one. Every call fails quietly into a message.
// Assumed shapes (not fixed in docs/): see the final report of the build.
import { state, setData, normalize } from './state.js';
import { store } from './util.js';
import { claimsPayload, hasReviewerChanges, reviewerEdits } from './extract_logic.js';

export async function checkHealth() {
  try {
    const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 1500);
    const r = await fetch('/api/health', { signal: ctl.signal }); clearTimeout(t);
    const j = r.ok ? await r.json() : null;
    state.live = !!(j && j.ok === true);
    state.pdfOk = j && typeof j.pdf_text === 'boolean' ? j.pdf_text : null; // null: unknown, try it
  } catch (e) { state.live = false; }
  return state.live;
}

async function readJson(r) {
  const j = await r.json().catch(() => ({ error: 'The server sent an unreadable answer.' }));
  if (!r.ok || j.error) throw new Error(j.error || 'The server returned an error (HTTP ' + r.status + ').');
  return j;
}
const post = (path, body, signal) => fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });

// POST /api/extract {report} -> {claims: [{text, source}], skipped: [{text, reason}]}
export async function extractReport(text, title, signal) {
  const j = await readJson(await post('/api/extract', { report: text, title: title || undefined }, signal));
  const claims = (j.claims || []).map((c) => (typeof c === 'string' ? { text: c, source: c } : { text: c.text || c.claim_text || '', source: c.source || c.source_sentence || c.text || '' }));
  state.extract = { claims, skipped: j.skipped || j.skipped_sentences || [] };
  state.reportText = text; state.reportTitle = title || '';
  return state.extract;
}

// POST /api/audit -> same shape as out/practice_audit.json.
// Untouched report: {report}. After the reviewer edited, added or re-included a claim: {claims: [{text, source, origin?}]},
// so the audit checks the reviewer's wording.
export async function runAudit(signal) {
  const claimsMode = !!(state.extract && hasReviewerChanges(state.extract.claims));
  const body = claimsMode ? { claims: claimsPayload(state.extract.claims), title: state.reportTitle || undefined }
    : { report: state.reportText, title: state.reportTitle || undefined };
  const j = await readJson(await post('/api/audit', body, signal));
  const keep = state.extract;
  setData(j, 'your report (live)');
  state.extract = keep; state.mode = 'live';
  state.origin = 'live'; state.liveReport = { text: state.reportText, title: state.reportTitle, claims: claimsMode ? body.claims : null };
  state.liveEdits = claimsMode ? reviewerEdits(keep.claims) : [];
  store('en.decisions', {});
  store('en.nextstep', null); // a new report starts with no recorded next step
  return j;
}

// POST /api/audit {report} for the multiple-reports view: returns the findings and leaves the open report alone.
export async function auditOnly(text, title, signal) {
  return normalize(await readJson(await post('/api/audit', { report: text, title: title || undefined }, signal)));
}

// POST /api/pdf-text (raw PDF bytes) -> {text}. Returns null when the server cannot do it.
export async function pdfText(file) {
  if (state.pdfOk === false) return null;
  try {
    const r = await fetch('/api/pdf-text', { method: 'POST', headers: { 'Content-Type': 'application/pdf' }, body: file });
    if (!r.ok) return null;
    const j = await r.json();
    return typeof j.text === 'string' && j.text.trim() ? j.text : null;
  } catch (e) { return null; }
}
