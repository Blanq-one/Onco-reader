import { h, sv, pct, fmtNum, fmtValue, plural, toast } from './util.js';
import { VERDICT, FLAG_TEXT, isBlocked, cannotAnswer, hasNumber, decisions, decide, decisionAllowed, BLOCKED_OVERRIDE_ERROR, reviewStatus, reviewJson, state, dataUrl, minGroup, minEvents, effectiveVerdict } from './state.js';
import { nextStepExport, analyse, STEPS } from './decision.js';

// Role views (see ROLES in state.js): an element tagged data-for="researcher engineer" shows only in those role
// views and in "All details"; untagged elements show for everyone. The CSS in app.css does the hiding.
export const forRoles = (...roles) => roles.join(' ');
// Recommendations are marked as interpretation, never as findings.
export const interpTag = () => h('span', { class: 'interp', title: 'A suggestion drawn from the findings, not a finding itself' }, 'Interpretation');

// What backs a finding, worked out from the findings file itself. A missing piece shows as a warning, never as a tick.
// The checksum status as the findings file states it: checksum_status, else checksum_verified true/false.
export function checksumStatus(d) {
  const r = ((d || state.data || {}).data_release) || {};
  return r.checksum_status || (r.checksum_verified === true ? 'verified' : r.checksum_verified === false ? 'not verified' : 'unknown');
}
export const checksumOk = () => { const r = (state.data && state.data.data_release) || {}; return r.checksum_verified === true || r.checksum_status === 'verified'; };
export const isTraced = (f) => hasNumber(f) && !!f.evidence.calculation && (f.evidence.source_files || []).length > 0;
export function assuranceItems(all) {
  const rel = (state.data && state.data.data_release) || {};
  const numeric = all.filter(hasNumber), traced = numeric.filter(isTraced);
  const lim = all.filter((f) => f.limitation), blocked = all.filter(isBlocked);
  return [
    [checksumOk() ? 'ok' : 'warn', checksumOk() ? 'Frozen data' : 'Checksums ' + checksumStatus(), (rel.name || 'The data release') + ': checksums ' + checksumStatus() + (checksumOk() ? '.' : ', so treat results with care.')],
    [traced.length === numeric.length ? 'ok' : 'warn', 'Numbers traced: ' + traced.length + ' of ' + numeric.length, traced.length + ' of ' + numeric.length + ' numbers show their calculation and source files.'],
    [lim.length === all.length ? 'ok' : 'warn', 'Limits shown: ' + lim.length + ' of ' + all.length, lim.length + ' of ' + plural(all.length, 'claim') + ' carry a limitation.'],
    ['info', 'Stopped by safety checks: ' + blocked.length, 'Clinical, individual and personal requests are stopped before any analysis. ' + (blocked.length ? plural(blocked.length, 'request was', 'requests were') + ' stopped in this report. ' : '') + 'Data readiness only.'],
    ['info', 'Reviews done: ' + reviewProgress().done + ' of ' + reviewProgress().total, 'A person makes the final call. Decisions are saved in review.json and never change audit.json.'],
  ];
}
// One row of trust badges; the full sentences open underneath on demand.
export function trustRow(all) {
  const items = assuranceItems(all);
  const IC = { ok: '✓ ', warn: '⚠ ', info: '' };
  return h('details', { class: 'trust' },
    h('summary', {}, h('span', { class: 'trust-chips' }, items.map(([st, head, text]) =>
      h('span', { class: 'trust-chip ' + st, title: text }, IC[st] ? h('span', { 'aria-hidden': 'true' }, IC[st]) : null, head))),
      h('span', { class: 'trust-more' }, 'How we checked')),
    h('ul', {}, items.map(([st, head, text]) => h('li', { class: st }, h('b', {}, head + '. '), text))));
}

// The hero: one answer for the whole report, and the verdict mix as one bar. Legend entries filter the list.
export function heroVerdict(all, onPick) {
  const a = analyse(), s = STEPS[a.step];
  // One bucket per claim (stopped first, then the verdict after review), so the sentence, bar and legend agree.
  const bucket = (f) => (isBlocked(f) ? 'blocked' : effectiveVerdict(f));
  const segs = [['supported', 'Supported', '✓'], ['contradicted', 'Contradicted', '✕'], ['insufficient_evidence', 'Cannot settle', '?'], ['blocked', 'Stopped', '⛔']]
    .map(([v, label, ic]) => ({ v, label, ic, n: all.filter((f) => bucket(f) === v).length }));
  const n = Object.fromEntries(segs.map((x) => [x.v, x.n]));
  const parts = [];
  if (n.supported) parts.push(n.supported + (n.supported === 1 ? ' matches' : ' match') + ' the data');
  if (n.contradicted) parts.push(n.contradicted + (n.contradicted === 1 ? ' does not' : ' do not'));
  if (n.insufficient_evidence) parts.push(n.insufficient_evidence + ' cannot be settled');
  if (n.blocked) parts.push(n.blocked + (n.blocked === 1 ? ' was' : ' were') + ' stopped by a safety check');
  const list = parts.length > 1 ? parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1] : parts[0] || 'none could be checked';
  const rp = reviewProgress();
  return h('section', { class: 'hero-v step-' + a.step, 'aria-labelledby': 'hv-h' },
    h('div', { class: 'hv-main' },
      h('div', { class: 'dp-kicker' }, h('span', {}, 'Suggested next step'), interpTag()),
      h('h2', { id: 'hv-h', class: 'hv-step' }, h('span', { class: 'dp-ic', 'aria-hidden': 'true' }, s.icon), s.label),
      h('p', { class: 'hv-line' }, 'Of ' + plural(all.length, 'claim') + ', ' + list + '.'),
      h('p', { class: 'muted hv-why' }, s.text)),
    h('div', { class: 'hv-mix' },
      h('div', { class: 'hv-bar', role: 'img', 'aria-label': segs.map((x) => x.n + ' ' + x.label).join(', ') },
        segs.filter((x) => x.n).map((x) => h('i', { class: 'seg v-' + x.v, style: 'flex:' + x.n }))),
      h('div', { class: 'hv-legend' }, segs.filter((x) => x.n).map((x) => h('button', { type: 'button', class: 'hv-key v-' + x.v,
        onclick: () => onPick && onPick({ verdict: x.v }) },
        h('b', {}, String(x.n)), h('span', {}, x.ic + ' ' + x.label)))),
      rp.required ? h('button', { type: 'button', class: 'hv-review', onclick: () => onPick && onPick({ review: true }) },
        plural(rp.required, 'claim needs', 'claims need') + " a person's review (" + rp.done + ' done)') : null));
}

export function checksumBadge(d) {
  const r = (d && d.data_release) || {};
  const ok = r.checksum_verified === true || r.checksum_status === 'verified';
  return h('span', { class: 'badge ' + (ok ? 'v-supported' : 'v-insufficient_evidence') },
    h('span', { class: 'ic', 'aria-hidden': 'true' }, ok ? '✓' : '!'), ok ? 'Checksum verified' : 'Checksum not verified');
}

// Where the results on screen come from. A live audit only when the server audited the report in this session;
// anything loaded from a file (the example report, ?data=) is labelled as precomputed.
export function sourceLine() {
  const d = state.data || {}, r = d.data_release || {};
  const status = checksumStatus(d);
  const rel = r.name || 'TCGA-BRCA frozen release';
  const live = state.origin === 'live';
  const title = d.report_title || (live && state.liveReport ? state.liveReport.title : '') || (live ? 'your pasted text' : 'untitled');
  return h('p', { class: 'source-line', id: 'source-line', 'data-source': live ? 'live' : 'example' },
    live ? null : h('span', { class: 'chip ex-chip' }, 'Example'), ' ',
    (live ? 'Live audit of: ' : 'Example report: ') + title + ' · ' + rel + ' · checksums ' + status);
}

// Review progress for the whole report. Required reviews are the flagged claims; with none flagged, every claim counts.
export function reviewProgress() {
  const all = (state.data && state.data.findings) || [];
  const req = all.filter((f) => f.needs_human_review);
  const pool = req.length ? req : all;
  const done = pool.filter((f) => reviewStatus(f) !== 'pending').length;
  return { done, total: pool.length, required: req.length, verified: pool.length > 0 && done === pool.length };
}
export function verificationBar() {
  const p = reviewProgress();
  const pill = p.verified ? h('span', { class: 'status-pill ok' }, '✓ Reviews recorded') : h('span', { class: 'status-pill auto' }, '⚙ Automated check');
  return h('div', { class: 'verify-in' }, pill,
    h('span', { class: 'vb-text' }, p.done + ' of ' + p.total + (p.required ? ' required reviews' : ' claims reviewed') + (p.required ? ' done' : '')),
    h('div', { class: 'progress vb-prog', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(p.total), 'aria-valuenow': String(p.done), 'aria-label': 'Review progress' },
      h('i', { style: 'width:' + (p.total ? 100 * p.done / p.total : 0) + '%' })),
    p.verified ? h('a', { class: 'btn', href: '#/summary' }, 'Open the Summary') : h('a', { class: 'btn primary', href: '#/review' }, 'Open the review queue'));
}
// Per-claim review state, next to the verdict.
export function statusPill(f) {
  const st = reviewStatus(f);
  const t = { pending: ['auto', '⚙ Automated check'], accepted: ['ok', '✓ Accepted by reviewer'], overridden: ['bad', '⚑ Overridden by reviewer'], more_evidence_requested: ['warn', '? More evidence requested'] }[st];
  return h('span', { class: 'status-pill ' + t[0] }, t[1]);
}

// Red-flag cards: one per category, only when it has claims. Each links to the claims behind it.
export function redFlags(all) {
  const link = (f, extra) => h('li', {}, h('a', { href: '#/claim/' + encodeURIComponent(f.id) }, f.id), ' ', h('span', {}, short(f.claim_text)), extra ? h('span', { class: 'rf-extra' }, ' ' + extra) : null);
  const cats = [
    ['bad', '✕', 'Numbers that do not match the data', all.filter((f) => f.verdict === 'contradicted'), (f) => f.correct_value && f.correct_value.text ? 'Data: ' + f.correct_value.text : ''],
    ['warn', '⚠', 'Too few events for a stable comparison', all.filter((f) => f.guardrail_flags.includes('low_event_count'))],
    ['warn', '⇄', 'Verdict changes under another rule', all.filter((f) => f.robustness && f.robustness.verdict_changes)],
    ['block', '⛔', 'Requests stopped before analysis', all.filter(isBlocked), (f) => '(' + f.guardrail_flags.filter((x) => FLAG_TEXT[x]).map((x) => FLAG_TEXT[x]).join(', ') + ')'],
  ].filter((c) => c[3].length);
  const cards = cats.map(([cls, ic, title, list, extra]) => h('div', { class: 'flag-card ' + cls },
    h('h3', {}, h('span', { 'aria-hidden': 'true' }, ic + ' '), title, h('span', { class: 'rf-n' }, String(list.length))),
    h('ul', {}, list.slice(0, 4).map((f) => link(f, extra && extra(f)))),
    list.length > 4 ? h('p', { class: 'muted' }, 'and ' + (list.length - 4) + ' more') : null));
  if (!checksumOk()) cards.unshift(h('div', { class: 'flag-card warn' }, h('h3', {}, h('span', { 'aria-hidden': 'true' }, '⚠ '), 'Data files not confirmed'),
    h('p', {}, 'The data files were not checked against their checksums. Treat every number with care.')));
  if (!cards.length) return h('p', { class: 'muted flags-none', role: 'status' }, 'No claims fall in a red-flag category.');
  return h('section', { class: 'flags', 'aria-labelledby': 'rf-h' }, h('h2', { id: 'rf-h' }, 'Red flags'), h('div', { class: 'flag-grid' }, cards));
}
const short = (t) => { t = String(t || ''); return t.length > 90 ? t.slice(0, 87).replace(/\s+\S*$/, '') + '...' : t; };

// Lab-style reference line: the value that matters next to its threshold.
export function referenceLine(f) {
  const b = (f.evidence && f.evidence.breakdown) || [];
  if (!b.length || isBlocked(f)) return null;
  const items = [];
  const ns = b.filter((r) => r.n != null);
  if (ns.length) { const s = ns.reduce((m, r) => (r.n < m.n ? r : m)); items.push([s.n >= minGroup(), 'Smallest group ' + fmtNum(s.n) + ' (' + s.group + '), minimum ' + fmtNum(minGroup())]); }
  const es = b.filter((r) => r.events != null);
  if (es.length) { const s = es.reduce((m, r) => (r.events < m.events ? r : m)); items.push([s.events >= minEvents(), 'Fewest deaths ' + fmtNum(s.events) + ' (' + s.group + '), minimum ' + fmtNum(minEvents())]); }
  if (!items.length) return null;
  return h('ul', { class: 'ref-line', 'aria-label': 'Reference thresholds' }, items.map(([ok, t]) =>
    h('li', { class: ok ? 'ok' : 'warn' }, h('span', { 'aria-hidden': 'true' }, ok ? '✓ ' : '⚠ '), t, ok ? '' : ' (low)')));
}

export function verdictBadge(f) {
  if (isBlocked(f)) return h('span', { class: 'badge v-blocked' }, h('span', { class: 'ic', 'aria-hidden': 'true' }, '⛔'), 'Blocked');
  const v = VERDICT[f.verdict] || { label: String(f.verdict), icon: '?' };
  return h('span', { class: 'badge v-' + f.verdict }, h('span', { class: 'ic', 'aria-hidden': 'true' }, v.icon), v.label);
}
export function flagChips(f) {
  const out = f.guardrail_flags.map((x) => h('span', { class: 'chip ' + (x === 'low_event_count' ? 'warn' : 'block'),
    'data-for': x === 'low_event_count' ? forRoles('datause', 'researcher') : forRoles('datause') }, FLAG_TEXT[x] || x));
  if (f.needs_human_review) out.push(h('span', { class: 'chip review' }, 'Needs review'));
  const rc = reviewChip(f); if (rc) out.push(rc);
  return out;
}
// One plain-language sentence saying what the check found, for every role.
const BLOCK_PLAIN = {
  clinical_claim_blocked: 'it reads as a clinical claim (treatment, survival or prognosis), which this tool does not judge',
  individual_level_request_blocked: 'it asks about an individual patient',
  reidentification_blocked: 'it tries to identify people',
  phi_like_input: 'it contains personal details',
  prompt_injection_suspected: 'it contains an instruction aimed at the tool',
  invalid_input: 'it is not a valid claim',
};
const firstSentence = (t) => { const m = String(t || '').match(/^.*?[.!?](?=\s|$)/); return (m ? m[0] : String(t || '')).trim(); };
export function plainResult(f) {
  let s;
  const e = f.evidence, metric = String(e.metric_name || '');
  if (isBlocked(f)) {
    s = 'Not checked: a safety check stopped it because ' + BLOCK_PLAIN[f.guardrail_flags.find((x) => BLOCK_PLAIN[x])] + '.';
  } else if (cannotAnswer(f)) {
    s = 'Not checked: the data has no field that can answer it.';
  } else if (metric.startsWith('survival_groups')) {
    s = 'Not judged: this tool shows how many deaths each group has, not whether one group lives longer.';
  } else if (f.verdict === 'supported' && isRatio(f) && hasNumber(f)) {
    s = 'The data agrees: ' + ratioText(f) + ' (' + groupsText(f) + ').';
  } else if (f.verdict === 'supported') {
    const share = /^(share_|coverage_|overlap_)/.test(metric) && e.denominator ? ' (' + pct(e.n_samples, e.denominator) + ')' : '';
    s = 'The data agrees' + (hasNumber(f) ? ': ' + fmtNum(e.n_samples) + ' of ' + fmtNum(e.denominator) + share : '') + '.';
  } else if (f.verdict === 'contradicted') {
    const cv = f.correct_value && f.correct_value.text;
    s = 'The data disagrees' + (cv ? ': it shows ' + cv : '') + '.';
  } else {
    const why = firstSentence(f.review_reason || f.missing_evidence || 'the claim cannot be settled with this data');
    s = 'Not settled: ' + why.charAt(0).toLowerCase() + why.slice(1).replace(/[.!?]?$/, '.');
  }
  if (reviewStatus(f) === 'overridden') s += ' A reviewer changed the verdict to ' + (VERDICT[effectiveVerdict(f)] || {}).label + '.';
  return s;
}
// Ratio claims (engine v1.3, metric ratio_...): the value is the ratio itself, so it is shown as "2.10 to 1",
// never as "141 of 208" or as a percentage.
export const isRatio = (f) => String((f.evidence || {}).metric_name || '').startsWith('ratio_');
export const ratioText = (f) => Number(f.evidence.value).toFixed(2) + ' to 1';
export const groupsText = (f) => ((f.evidence || {}).groups || []).map((g) => g.group + ' ' + fmtNum(g.n)).join(' vs ');
// Survival comparisons (metric survival_groups_...) are never judged: their numbers are the deaths in each group.
export const isSurvivalGroups = (f) => String((f.evidence || {}).metric_name || '').startsWith('survival_groups');
export const deathsText = (f) => ((f.evidence || {}).breakdown || []).map((g) => g.group + ' ' + plural(g.events, 'death')).join(' vs ');
const sizesText = (f) => ((f.evidence || {}).breakdown || []).map((g) => g.group + ' ' + plural(g.n, 'sample')).join(' vs ');
export function headlineText(f) {
  if (!hasNumber(f)) return null;
  const e = f.evidence;
  if (isSurvivalGroups(f)) return deathsText(f);
  return isRatio(f) ? ratioText(f) : fmtNum(e.n_samples) + ' of ' + fmtNum(e.denominator);
}
// The share that goes with the headline ("48.6%"), the group counts for a ratio, or the group sizes for a survival comparison.
export function shareText(f) {
  if (!hasNumber(f)) return null;
  if (isSurvivalGroups(f)) return sizesText(f);
  return isRatio(f) ? groupsText(f) : pct(f.evidence.n_samples, f.evidence.denominator);
}
export function valueText(f, v) {
  const x = v === undefined ? f.evidence.value : v;
  return isRatio(f) && x != null ? Number(x).toFixed(2) + ' to 1' : fmtValue(x);
}
// On a phone a table with class "stack" shows one block per row, each cell labeled with its column header (app.css).
export function stackTable(table) {
  const heads = [...table.querySelectorAll('thead th')].map((th) => th.textContent.trim());
  table.classList.add('stack');
  table.querySelectorAll('tbody tr').forEach((tr) => [...tr.children].forEach((c, i) => {
    if (c.tagName === 'TD' && heads[i]) c.setAttribute('data-label', heads[i]);
  }));
  return table;
}
export function breadcrumbs(items) {
  return h('nav', { class: 'crumbs', 'aria-label': 'Breadcrumb' }, h('ol', {}, items.map((it, i) =>
    h('li', i === items.length - 1 ? { 'aria-current': 'page' } : {}, it.href && i < items.length - 1 ? h('a', { href: it.href }, it.label) : it.label))));
}

export function funnel(trace) {
  if (!trace.length) return h('p', { class: 'muted' }, 'No cohort steps were recorded for this finding.');
  const max = Math.max(1, trace[0].n_before);
  return h('div', { class: 'funnel', role: 'list', 'aria-label': 'Cohort funnel' }, trace.map((s, i) => {
    const dropped = s.n_before - s.n_after;
    return h('div', { class: 'f-row', role: 'listitem' },
      h('div', {}, h('b', {}, (i + 1) + '. ' + s.step), h('div', { class: 'muted', style: 'font-size:.85rem' }, 'from ' + fmtNum(s.n_before))),
      sv('svg', { viewBox: '0 0 100 26', preserveAspectRatio: 'none', 'aria-hidden': 'true' },
        sv('rect', { class: 'f-bg', x: 0, y: 0, width: 100 * s.n_before / max, height: 26, rx: 2 }),
        sv('rect', { class: 'f-bar', x: 0, y: 0, width: Math.max(0.5, 100 * s.n_after / max), height: 26, rx: 2, style: 'animation-delay:' + (i * 90) + 'ms' })),
      h('div', { class: 'f-num' }, fmtNum(s.n_after), dropped > 0 ? h('small', {}, '-' + fmtNum(dropped) + ' removed') : h('small', { style: 'color:var(--muted)' }, 'none removed')));
  }));
}

export function breakdownChart(rows) {
  const mg = minGroup(), me = minEvents();
  const max = Math.max(mg, ...rows.map((r) => r.n || 0), 1);
  return h('div', {},
    h('div', { class: 'bk', role: 'list', 'aria-label': 'Group sizes' }, rows.map((r) => {
      const lowN = r.n < mg, lowE = r.events != null && r.events < me;
      const notes = [];
      if (lowN) notes.push('under ' + plural(mg, 'sample'));
      if (lowE) notes.push('under ' + plural(me, 'death'));
      return h('div', { class: 'bk-row', role: 'listitem' },
        h('div', {}, h('b', {}, r.group), notes.length ? h('div', { class: 'bk-note chip warn' }, '⚠ ' + notes.join(', ')) : null),
        sv('svg', { viewBox: '0 0 100 22', preserveAspectRatio: 'none', 'aria-hidden': 'true' },
          sv('rect', { class: 'bk-bar' + (lowN || lowE ? ' low' : ''), x: 0, y: 3, width: Math.max(0.5, 100 * r.n / max), height: 16, rx: 2 }),
          sv('line', { class: 'bk-line', x1: 100 * mg / max, x2: 100 * mg / max, y1: 0, y2: 22, 'vector-effect': 'non-scaling-stroke' })),
        h('div', { class: 'f-num' }, plural(r.n, 'sample'), r.events != null ? h('small', { style: 'color:var(--muted)' }, plural(r.events, 'death')) : null));
    })),
    h('p', { class: 'muted bk-note' }, 'Dashed line: minimum group size (' + plural(mg, 'sample') + '). Marker: group under ' + plural(mg, 'sample') + ' or ' + plural(me, 'death') + '.'));
}

// Accept or override the machine verdict. Both verdicts are kept (see reviewJson in state.js).
const vLabel = (v) => (VERDICT[v] || { label: String(v) }).label;
export function reviewBlock(f, onChange) {
  const blocked = isBlocked(f);
  const cur = decisions()[f.id] || {};
  const status = h('p', { class: 'dec-saved', role: 'status' });
  const activeKey = (st) => (st === 'accepted' ? 'approve' : st === 'overridden' ? 'reject' : st === 'more_evidence_requested' ? 'more' : '');
  const show = (refused) => {
    const st = reviewStatus(f), c = decisions()[f.id] || {};
    status.classList.toggle('dec-refused', !!refused || !decisionAllowed(f, c));
    status.textContent = refused ? 'Not saved: ' + BLOCKED_OVERRIDE_ERROR + '.'
      : !decisionAllowed(f, c) ? 'A saved override is not allowed for a blocked claim. Choose Accept or Ask for more evidence.'
      : st === 'pending' ? 'Not reviewed yet.'
      : st === 'overridden' ? 'Overridden. Original: ' + vLabel(f.verdict) + '. Reviewer: ' + vLabel(c.verdict) + '.'
      : st === 'accepted' ? 'Accepted: ' + (blocked ? 'blocked, recorded as insufficient evidence' : vLabel(f.verdict)) + '.' : 'More evidence requested.';
    group.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.k === activeKey(st))));
  };
  const note = h('textarea', { id: 'note-' + f.id, placeholder: 'Optional note' });
  note.value = cur.note || '';
  note.addEventListener('change', () => { if (decisions()[f.id]) { decide(f.id, { note: note.value }); show(); onChange && onChange(); } });
  const save = (k, verdict) => { const ok = decide(f.id, { decision: k, verdict, note: note.value }); show(!ok); if (ok && onChange) onChange(k); };
  const btn = (k, label, fn) => h('button', { class: 'btn', type: 'button', 'data-k': k, 'aria-pressed': 'false', onclick: fn }, label);
  const noteParts = [h('label', { for: 'note-' + f.id, class: 'muted', style: 'font-size:.85rem;display:block;margin-top:8px' }, 'Note (optional)'), note, status];
  const original = h('p', { class: 'row' }, h('span', { class: 'muted' }, 'Original verdict:'), verdictBadge(f));
  let group;
  if (blocked) {
    // No override control at all: there is no result to change.
    group = h('div', { class: 'decision', role: 'group', 'aria-label': 'Review decision', 'aria-describedby': 'why-' + f.id },
      btn('approve', 'Accept as insufficient evidence', () => save('approve', 'insufficient_evidence')),
      btn('more', 'Ask for more evidence', () => save('more', null)));
    show();
    return h('div', {}, original,
      h('p', { class: 'notice block', id: 'why-' + f.id }, 'A guardrail stopped this claim before any analysis, so there is no result to override. You can accept it as insufficient evidence or ask for more evidence.'),
      group, ...noteParts);
  }
  const others = Object.keys(VERDICT).filter((v) => v !== f.verdict);
  const pick = h('select', { id: 'rv-' + f.id }, others.map((v) => h('option', Object.assign({ value: v }, cur.verdict === v ? { selected: true } : {}), VERDICT[v].label)));
  group = h('div', { class: 'decision', role: 'group', 'aria-label': 'Review decision' },
    btn('approve', 'Accept ' + vLabel(f.verdict), () => save('approve', f.verdict)),
    btn('reject', 'Override with the verdict below', () => save('reject', pick.value)),
    btn('more', 'Ask for more evidence', () => save('more', null)));
  show();
  return h('div', {}, original, group,
    h('label', { for: 'rv-' + f.id, class: 'muted', style: 'font-size:.85rem;display:block' }, 'Override with this verdict'), pick, ...noteParts);
}
export function reviewChip(f) {
  const st = reviewStatus(f);
  if (st === 'pending') return null;
  const c = decisions()[f.id] || {};
  if (st === 'overridden') return h('span', { class: 'chip over' }, '⚑ Overridden: ' + vLabel(f.verdict) + ' to ' + vLabel(c.verdict));
  return h('span', { class: 'chip rev-ok' }, st === 'accepted' ? '✓ Accepted' : '? More evidence requested');
}

// Source sentence, correct value, missing evidence and sub-checks for one claim.
export function claimFacts(f) {
  const out = [];
  const subs = f.sub_checks || (f.evidence && f.evidence.sub_checks) || [];
  if (f.source_sentence) out.push(h('section', { class: 'card', 'aria-label': 'Source sentence' }, h('h2', {}, 'Source sentence'), h('blockquote', { class: 'src' }, f.source_sentence)));
  if (f.correct_value && (f.correct_value.text || f.correct_value.value != null)) out.push(h('section', { class: 'card fact bad', 'aria-label': 'Correct value', 'data-for': forRoles('researcher') }, h('h2', {}, 'Correct value from the data'),
    h('p', { class: 'fact-v' }, f.correct_value.text || (f.correct_value.value + ' ' + (f.correct_value.unit || '')))));
  if (f.missing_evidence) out.push(h('section', { class: 'card fact warn', 'aria-label': 'Missing evidence', 'data-for': forRoles('researcher', 'datause', 'engineer') }, h('h2', {}, 'Data that would be needed'), h('p', { style: 'margin:0' }, f.missing_evidence)));
  if (subs.length) out.push(h('section', { class: 'card', 'aria-label': 'Parts of this sentence', 'data-for': forRoles('researcher') }, h('h2', {}, 'This sentence has ' + plural(subs.length, 'part')),
    h('ul', { class: 'subs' }, subs.map((s) => h('li', {}, verdictBadge({ verdict: s.verdict, guardrail_flags: [] }), h('span', {}, ' ' + s.claim),
      s.value != null ? h('small', { class: 'muted' }, ' (' + fmtNum(s.n_samples) + ' of ' + fmtNum(s.denominator) + ')') : null)))));
  return out;
}
export function factLine(f) {
  if (f.correct_value && f.correct_value.text) return 'Correct value: ' + f.correct_value.text;
  if (f.missing_evidence) return 'Needed: ' + f.missing_evidence;
  return null;
}

// audit.json (server, or the precomputed example file) and review.json (built here)
export function saveBlob(text, name) {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
  const a = h('a', { href: url, download: name }); document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
// audit.json in the shared format: the server makes it for a live report; the example report uses the precomputed file.
// Kept per report, so the download and the data engineer's checksum table share one request.
let auditCache = { key: null, text: null };
export async function auditJsonText() {
  const lr = state.origin === 'live' && state.liveReport && state.liveReport.text ? state.liveReport : null;
  const live = !!lr;
  const key = live ? 'live|' + lr.title + '|' + lr.text : 'file|' + state.source;
  if (auditCache.key === key && auditCache.text) return auditCache.text;
  const r = live
    ? await fetch('/api/audit-json', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ report: lr.text, title: lr.title || undefined }) })
    : await fetch(dataUrl('out/audit.json'), { cache: 'no-store' });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  auditCache = { key, text: await r.text() };
  return auditCache.text;
}
export function exportButtons(label) {
  const audit = h('button', { class: 'btn', type: 'button', onclick: async (ev) => {
    const b = ev.currentTarget; b.disabled = true;
    try { saveBlob(await auditJsonText(), 'audit.json'); toast('audit.json downloaded'); } catch (e) { toast('audit.json is not available right now.'); }
    b.disabled = false;
  } }, 'Download audit.json');
  const review = h('button', { class: 'btn', type: 'button', onclick: () => {
    let doc;
    try { doc = reviewJson(); } catch (e) { toast('review.json not saved. ' + e.message + '.'); return; }
    doc.next_step = nextStepExport();
    saveBlob(JSON.stringify(doc, null, 2) + '\n', 'review.json'); toast('review.json downloaded');
  } }, 'Download review.json');
  return h('div', { class: 'row no-print', role: 'group', 'aria-label': label || 'Downloads' }, audit, review);
}
export { pct };

// One plain-English sentence saying what the headline numerator and denominator are.
export function caption(f) {
  const e = f.evidence, t = f.cohort_trace || [];
  if (isRatio(f)) return 'The ratio compares two group sizes: ' + groupsText(f) + ', so ' + fmtNum(e.n_samples) + ' of the ' + fmtNum(e.denominator) + ' samples in the two groups are in the first.';
  const n = fmtNum(e.n_samples), d = fmtNum(e.denominator);
  let ns = null;
  for (let i = t.length - 1; i >= 0; i--) if (t[i].n_after === e.n_samples) { ns = t[i]; break; }
  const ds = t.find((s) => s.n_after === e.denominator);
  if (Array.isArray(e.breakdown) && e.breakdown.length) {
    const small = e.breakdown.reduce((a, b) => (b.n < a.n ? b : a));
    return 'The number to watch is ' + plural(small.n, 'sample') + ', the size of the smallest group (' + small.group + '). '
      + n + ' of ' + plural(e.denominator, 'sample') + (ns ? (e.n_samples === 1 ? ' remains' : ' remain') + ' after "' + ns.step + '"' : (e.n_samples === 1 ? ' was counted' : ' were counted')) + ' and are split into ' + plural(e.breakdown.length, 'group') + '.';
  }
  if (!ns || !ds) return plural(e.n_samples, 'sample was', 'samples were') + ' counted out of ' + d + ' in the calculation (see the calculation panel).';
  if (e.n_samples === e.denominator) return (e.denominator === 1 ? 'The 1 sample' : 'All ' + d + ' samples') + ' at "' + ds.step + '" also ' + (e.denominator === 1 ? 'passes' : 'pass') + ' "' + ns.step + '".';
  if (ns === ds) return n + ' of ' + plural(e.denominator, 'sample') + (e.n_samples === 1 ? ' is' : ' are') + ' at the step "' + ns.step + '".';
  return 'Of ' + plural(e.denominator, 'sample') + ' at "' + ds.step + '", ' + n + (e.n_samples === 1 ? ' remains' : ' remain') + ' after "' + ns.step + '".';
}
