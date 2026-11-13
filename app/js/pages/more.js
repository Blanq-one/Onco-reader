import { h, fmtNum, fmtValue, pct, store } from '../util.js';
import { state, findings, byId, isBlocked, hasNumber, decisions, reviewStatus, FLAG_TEXT, VERDICT } from '../state.js';
import { verdictBadge, flagChips, reviewBlock, claimFacts, exportButtons, breadcrumbs, headlineText, factLine } from '../ui.js';

const enc = encodeURIComponent;

/* ---------- Compare ---------- */
const ROWS = [
  ['Claim', (f) => f.claim_text],
  ['Verdict', (f) => (isBlocked(f) ? 'Blocked' : (VERDICT[f.verdict] || {}).label || f.verdict), (f) => verdictBadge(f)],
  ['Headline', (f) => headlineText(f) || 'No number'],
  ['Share', (f) => (hasNumber(f) ? pct(f.evidence.n_samples, f.evidence.denominator) : 'n/a')],
  ['Metric', (f) => f.evidence.metric_name || 'n/a'],
  ['Metric value', (f) => (hasNumber(f) ? fmtValue(f.evidence.value) : 'no value')],
  ['Cohort steps', (f) => f.cohort_trace.length ? f.cohort_trace.map((s) => s.step + ': ' + fmtNum(s.n_after)).join('; ') : 'none recorded'],
  ['Source files', (f) => (f.evidence.source_files || []).join(', ') || 'none'],
  ['Flags', (f) => f.guardrail_flags.map((x) => FLAG_TEXT[x] || x).join(', ') || 'none'],
  ['Needs review', (f) => (f.needs_human_review ? 'Yes' : 'No')],
  ['Alternative rule', (f) => (f.robustness ? f.robustness.alt_rule + ' (' + fmtValue(f.robustness.alt_value) + ', verdict ' + (f.robustness.verdict_changes ? 'changes' : 'holds') + ')' : 'not tested')],
  ['Calculation', (f) => f.evidence.calculation || 'n/a'],
  ['Limitation', (f) => f.limitation || 'none given'],
  ['Next actions', (f) => f.next_actions.join(' | ') || 'none'],
];

export function comparePage(q) {
  const all = findings();
  const root = h('div', { class: 'page wide', 'data-title': 'Compare' });
  root.append(h('h1', {}, 'Compare two claims'));
  if (all.length < 2) {
    root.append(h('div', { class: 'empty' }, h('p', {}, 'Comparing needs at least two claims in the file.'), h('a', { class: 'btn', href: '#/results' }, 'Back to Results')));
    return { view: root, crumbs: breadcrumbs([{ label: 'Results', href: '#/results' }, { label: 'Compare' }]) };
  }
  let a = byId(q.get('a')) || all[0];
  let b = byId(q.get('b')) || all.find((x) => x !== a);
  const pick = (name, cur) => h('label', { class: 'cmp-pick' }, 'Claim ' + name.toUpperCase(),
    h('select', { 'aria-label': 'Claim ' + name, onchange: (ev) => {
      const o = name === 'a' ? [ev.target.value, b.id] : [a.id, ev.target.value];
      location.hash = '#/compare?a=' + enc(o[0]) + '&b=' + enc(o[1]);
    } }, all.map((x) => h('option', Object.assign({ value: x.id }, x === cur ? { selected: true } : {}), x.id + ': ' + x.claim_text.slice(0, 60)))));
  root.append(h('div', { class: 'row', style: 'margin-bottom:16px' }, pick('a', a), pick('b', b),
    h('button', { class: 'btn', type: 'button', onclick: () => { location.hash = '#/compare?a=' + enc(b.id) + '&b=' + enc(a.id); } }, 'Swap')));
  const head = h('tr', {}, h('th', { scope: 'col' }, 'Field'), h('th', { scope: 'col' }, h('a', { href: '#/claim/' + enc(a.id) }, a.id)), h('th', { scope: 'col' }, h('a', { href: '#/claim/' + enc(b.id) }, b.id)));
  const body = ROWS.map(([label, fn, node]) => {
    const ka = fn(a), kb = fn(b), diff = ka !== kb;
    const cell = (f, k) => h('td', { class: diff ? 'diff' : null }, diff ? h('span', { class: 'diff-tag' }, 'Differs') : null, node ? node(f) : k);
    return h('tr', {}, h('th', { scope: 'row' }, label), cell(a, ka), cell(b, kb));
  });
  root.append(h('div', { class: 'table-wrap' }, h('table', { class: 'cmp' }, h('thead', {}, head), h('tbody', {}, body))),
    h('p', { class: 'muted' }, 'Rows marked Differs have different values for the two claims.'));
  return { view: root, crumbs: breadcrumbs([{ label: 'Results', href: '#/results' }, { label: 'Compare' }]) };
}

/* ---------- Review queue: every verdict is accepted or overridden by a person ---------- */
const vText = (v) => (VERDICT[v] || { label: String(v) }).label;
export function reviewPage(q) {
  // items that need review come first, report order otherwise
  const queue = findings().slice().sort((a, b) => Number(!!b.needs_human_review) - Number(!!a.needs_human_review));
  const root = h('div', { class: 'page', 'data-title': 'Review' });
  const crumbs = breadcrumbs([{ label: 'Results', href: '#/results' }, { label: 'Review queue' }]);
  root.append(h('h1', {}, 'Review queue'));
  if (!queue.length) {
    root.append(h('div', { class: 'empty' }, h('h2', {}, 'Nothing to review'), h('a', { class: 'btn primary', href: '#/summary' }, 'Open the Summary')));
    return { view: root, crumbs };
  }
  let idx = queue.findIndex((f) => f.id === q.get('id'));
  if (idx < 0) idx = Math.max(0, parseInt(q.get('i') || '0', 10) || 0);
  if (idx >= queue.length) idx = queue.length - 1;
  const f = queue[idx];
  const done = () => queue.filter((x) => reviewStatus(x) !== 'pending').length;
  const over = () => queue.filter((x) => reviewStatus(x) === 'overridden').length;
  const prog = h('p', { role: 'status', class: 'muted' });
  const bar = h('div', { class: 'progress', 'aria-hidden': 'true' }, h('i'));
  const upd = () => { prog.textContent = done() + ' of ' + queue.length + ' reviewed, ' + over() + ' overridden. Showing item ' + (idx + 1) + '.'; bar.firstChild.style.width = (100 * done() / queue.length) + '%'; };
  upd();
  const last = idx === queue.length - 1;
  root.append(prog, bar, h('section', { class: 'card' },
    h('div', { class: 'row' }, verdictBadge(f), flagChips(f), h('span', { class: 'chip' }, f.id)),
    h('h2', { style: 'margin-top:8px' }, f.claim_text),
    ...claimFacts(f),
    hasNumber(f) ? h('p', {}, h('b', {}, headlineText(f)), ' (' + pct(f.evidence.n_samples, f.evidence.denominator) + ')  ', h('a', { href: '#/claim/' + enc(f.id) }, 'See the calculation')) : h('p', { class: 'muted' }, 'No number for this item. ', h('a', { href: '#/claim/' + enc(f.id) }, 'Open the full finding')),
    f.needs_human_review ? h('p', {}, h('b', {}, 'Why it needs review: '), f.review_reason || 'No reason given.') : null,
    h('div', { class: 'limit' }, h('h2', {}, 'Limitation'), h('p', { style: 'margin:0' }, f.limitation || 'None given.')),
    reviewBlock(f, upd)),
    h('div', { class: 'pager' },
      idx > 0 ? h('a', { class: 'btn', href: '#/review?i=' + (idx - 1) }, '← Previous') : h('span'),
      last ? h('a', { class: 'btn primary', href: '#/summary' }, 'Finish and open Summary') : h('a', { class: 'btn primary', href: '#/review?i=' + (idx + 1) }, 'Next →')),
    h('section', { class: 'card' }, h('h2', {}, 'Export'), h('p', { class: 'muted' }, 'review.json keeps the original verdict and the reviewer verdict side by side.'), exportButtons()));
  return { view: root, crumbs };
}

/* ---------- Summary ---------- */
export function summaryPage() {
  const d = state.data, all = findings(), dec = decisions();
  const root = h('div', { class: 'page', 'data-title': 'Summary' });
  const n = (v) => all.filter((x) => x.verdict === v).length;
  root.append(h('h1', {}, 'Summary'),
    h('p', { class: 'muted' }, (d.report_title || 'Report') + ' | ' + ((d.data_release && d.data_release.name) || 'unknown release') + ' | source ' + state.source + (d.is_mock ? ' | SAMPLE DATA' : '')),
    h('div', { class: 'row no-print', style: 'margin-bottom:16px' },
      h('button', { class: 'btn primary', type: 'button', onclick: () => window.print() }, 'Print this page'), exportButtons()),
    h('section', { class: 'card' }, h('h2', {}, 'Counts'), h('p', {}, all.length + ' claims. ' + n('supported') + ' supported, ' + n('contradicted') + ' contradicted, ' + n('insufficient_evidence') + ' insufficient evidence, ' + all.filter((x) => x.needs_human_review).length + ' need review, ' + all.filter(isBlocked).length + ' blocked. '
      + all.filter((x) => reviewStatus(x) === 'overridden').length + ' verdicts overridden by a reviewer.')));
  root.append(h('section', { class: 'card' }, h('h2', {}, 'Review decisions'),
    h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, ['Claim', 'Original verdict', 'Reviewer verdict', 'Status', 'Note'].map((t) => h('th', { scope: 'col' }, t)))),
      h('tbody', {}, all.map((f) => { const x = dec[f.id] || {}, st = reviewStatus(f);
        return h('tr', { class: st === 'overridden' ? 'overridden' : null }, h('td', {}, h('a', { href: '#/claim/' + enc(f.id) }, f.id), ' ' + f.claim_text),
          h('td', {}, vText(f.verdict)), h('td', {}, st === 'pending' || st === 'more_evidence_requested' ? 'none' : vText(x.verdict || f.verdict)),
          h('td', {}, st === 'overridden' ? '⚑ Overridden' : st === 'accepted' ? '✓ Accepted' : st === 'more_evidence_requested' ? 'More evidence requested' : 'Not reviewed yet'), h('td', {}, x.note || '')); })))),
    h('a', { class: 'btn no-print', href: '#/review' }, 'Open the review queue')));
  root.append(h('section', { class: 'card' }, h('h2', {}, 'All claims and limitations'),
    all.map((f) => h('div', { style: 'margin-bottom:14px;break-inside:avoid' }, h('div', { class: 'row' }, verdictBadge(f), h('b', {}, f.id), headlineText(f) ? h('span', {}, headlineText(f)) : null), h('div', {}, f.claim_text),
      factLine(f) ? h('div', {}, factLine(f)) : null,
      h('div', { class: 'muted' }, 'Limitation: ' + (f.limitation || 'none given'))))));
  root.append(h('section', { class: 'card' }, h('h2', {}, 'All next actions'),
    all.some((f) => f.next_actions.length) ? all.filter((f) => f.next_actions.length).map((f) => h('div', {}, h('h3', {}, f.id + ': ' + f.claim_text), h('ul', {}, f.next_actions.map((a) => h('li', {}, a)))))
      : h('p', { class: 'muted' }, 'No next actions.')));
  root.append(h('p', { class: 'muted' }, 'This tool checks data readiness only. It makes no clinical claims.'));
  return root;
}
void store;
