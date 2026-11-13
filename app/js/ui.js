import { h, sv, pct, fmtNum } from './util.js';
import { VERDICT, FLAG_TEXT, isBlocked, cannotAnswer, hasNumber, decisions, decide, DECISION_TEXT, minGroup, minEvents } from './state.js';

export function verdictBadge(f) {
  if (isBlocked(f)) return h('span', { class: 'badge v-blocked' }, h('span', { class: 'ic', 'aria-hidden': 'true' }, '⛔'), 'Blocked');
  const v = VERDICT[f.verdict] || { label: String(f.verdict), icon: '?' };
  return h('span', { class: 'badge v-' + f.verdict }, h('span', { class: 'ic', 'aria-hidden': 'true' }, v.icon), v.label);
}
export function flagChips(f) {
  const out = f.guardrail_flags.map((x) => h('span', { class: 'chip ' + (x === 'low_event_count' ? 'warn' : 'block') }, FLAG_TEXT[x] || x));
  if (f.needs_human_review) out.push(h('span', { class: 'chip review' }, 'Needs review'));
  return out;
}
export function headlineText(f) {
  if (!hasNumber(f)) return null;
  const e = f.evidence;
  return fmtNum(e.n_samples) + ' of ' + fmtNum(e.denominator);
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
      if (lowN) notes.push('under ' + mg + ' samples');
      if (lowE) notes.push('under ' + me + ' deaths');
      return h('div', { class: 'bk-row', role: 'listitem' },
        h('div', {}, h('b', {}, r.group), notes.length ? h('div', { class: 'bk-note chip warn' }, '⚠ ' + notes.join(', ')) : null),
        sv('svg', { viewBox: '0 0 100 22', preserveAspectRatio: 'none', 'aria-hidden': 'true' },
          sv('rect', { class: 'bk-bar' + (lowN || lowE ? ' low' : ''), x: 0, y: 3, width: Math.max(0.5, 100 * r.n / max), height: 16, rx: 2 }),
          sv('line', { class: 'bk-line', x1: 100 * mg / max, x2: 100 * mg / max, y1: 0, y2: 22, 'vector-effect': 'non-scaling-stroke' })),
        h('div', { class: 'f-num' }, fmtNum(r.n) + ' samples', r.events != null ? h('small', { style: 'color:var(--muted)' }, fmtNum(r.events) + ' deaths') : null));
    })),
    h('p', { class: 'muted bk-note' }, 'Dashed line: minimum group size (' + mg + ' samples). Marker: group under ' + mg + ' samples or ' + me + ' deaths.'));
}

// approve / reject / ask for more, saved in localStorage
export function decisionBlock(f, onChange) {
  const cur = decisions()[f.id] || {};
  const status = h('span', { class: 'dec-saved', role: 'status' }, cur.decision ? 'Saved: ' + DECISION_TEXT[cur.decision] : '');
  const note = h('textarea', { id: 'note-' + f.id, 'aria-label': 'Optional note', placeholder: 'Optional note' });
  note.value = cur.note || '';
  note.addEventListener('change', () => { decide(f.id, { note: note.value }); status.textContent = 'Note saved'; onChange && onChange(); });
  const btn = (key, label) => {
    const b = h('button', { class: 'btn', type: 'button', 'aria-pressed': String(cur.decision === key) }, label);
    b.addEventListener('click', () => {
      decide(f.id, { decision: key, note: note.value });
      b.parentNode.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', 'false'));
      b.setAttribute('aria-pressed', 'true');
      status.textContent = 'Saved: ' + DECISION_TEXT[key];
      onChange && onChange(key);
    });
    return b;
  };
  return h('div', {},
    h('div', { class: 'decision', role: 'group', 'aria-label': 'Review decision' }, btn('approve', 'Approve'), btn('reject', 'Reject'), btn('more', 'Ask for more')),
    h('label', { for: 'note-' + f.id, class: 'muted', style: 'font-size:.85rem' }, 'Note (optional)'), note, status);
}
export { pct };

// One plain-English sentence saying what the headline numerator and denominator are.
export function caption(f) {
  const e = f.evidence, t = f.cohort_trace || [];
  const n = fmtNum(e.n_samples), d = fmtNum(e.denominator);
  let ns = null;
  for (let i = t.length - 1; i >= 0; i--) if (t[i].n_after === e.n_samples) { ns = t[i]; break; }
  const ds = t.find((s) => s.n_after === e.denominator);
  if (Array.isArray(e.breakdown) && e.breakdown.length) {
    const small = e.breakdown.reduce((a, b) => (b.n < a.n ? b : a));
    return 'The number to watch is ' + fmtNum(small.n) + ' samples, the size of the smallest group (' + small.group + '). '
      + n + ' of ' + d + ' samples' + (ns ? ' remain after "' + ns.step + '"' : ' were counted') + ' and are split into ' + e.breakdown.length + ' groups.';
  }
  if (!ns || !ds) return n + ' samples were counted out of ' + d + ' in the calculation (see the calculation panel).';
  if (e.n_samples === e.denominator) return 'All ' + d + ' samples at "' + ds.step + '" also pass "' + ns.step + '".';
  if (ns === ds) return n + ' of ' + d + ' samples are at the step "' + ns.step + '".';
  return 'Of ' + d + ' samples at "' + ds.step + '", ' + n + ' remain after "' + ns.step + '".';
}
