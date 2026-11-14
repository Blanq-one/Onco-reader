import { h } from '../util.js';
import { state, findings, saveFilters, FLAG_TEXT, isBlocked, hasNumber } from '../state.js';
import { verdictBadge, howWeChecked, scorecard, countsSentence, reviewsLine, sourceLine, exportButtons, stackTable, isRatio, ratioText, groupsText, isSurvivalGroups, deathsText } from '../ui.js';
import { decisionPanel } from '../decisionPanel.js';
import { pct, plural, fmtNum } from '../util.js';

let active = -1;
let shown = [];

function apply() {
  const f = state.filters;
  const q = f.q.trim().toLowerCase();
  let out = findings().filter((x) =>
    (!f.verdict || (f.verdict === 'blocked' ? isBlocked(x) : x.verdict === f.verdict)) &&
    (!f.review || x.needs_human_review) &&
    (!f.flag || (f.flag === 'none' ? !x.guardrail_flags.length : x.guardrail_flags.includes(f.flag))) &&
    (!q || (x.claim_text + ' ' + x.id + ' ' + (x.evidence.metric_name || '')).toLowerCase().includes(q)));
  if (f.sort === 'verdict') out = out.slice().sort((a, b) => RANK(a) - RANK(b));
  else if (f.sort === 'review') out = out.slice().sort((a, b) => Number(!!b.needs_human_review) - Number(!!a.needs_human_review));
  else if (f.sort === 'text') out = out.slice().sort((a, b) => a.claim_text.localeCompare(b.claim_text));
  return out;
}

// Problem rows first: contradicted, then stopped by a safety check, then insufficient evidence, then supported.
const RANK = (x) => (isBlocked(x) ? 1 : { contradicted: 0, insufficient_evidence: 2, supported: 3 }[x.verdict] ?? 3);
// What the data says, in one short phrase: "49.9% (421 of 844)", "2.10 to 1 (...)", or the deaths in each survival group.
function dataSays(x) {
  if (!hasNumber(x)) return isBlocked(x) ? 'No number' : 'No number available';
  const e = x.evidence, metric = String(e.metric_name || '');
  if (isSurvivalGroups(x)) return deathsText(x);
  if (isRatio(x)) return ratioText(x) + ' (' + groupsText(x) + ')';
  if (/^(share_|coverage_|overlap_)/.test(metric) && e.denominator) return pct(e.n_samples, e.denominator) + ' (' + fmtNum(e.n_samples) + ' of ' + fmtNum(e.denominator) + ')';
  return fmtNum(e.n_samples) + ' of ' + fmtNum(e.denominator);
}

export function resultsPage() {
  const root = h('div', { class: 'page', 'data-title': 'Results' });
  const all = findings();
  root.append(h('div', { class: 'title-row' }, h('h1', {}, 'Results'), exportButtons('Download the audit')));
  if (!all.length) {
    root.append(h('div', { class: 'empty' }, h('h2', {}, 'No claims in this file'),
      h('p', { class: 'muted' }, 'The findings file loaded but holds no claims.'), h('a', { class: 'btn primary', href: '#/' }, 'Back to Start')));
    return root;
  }
  root.append(sourceLine(), countsSentence(all), scorecard(all), reviewsLine(), decisionPanel('results'));

  const flags = [...new Set(all.flatMap((x) => x.guardrail_flags))];
  const f = state.filters;
  const tbody = h('tbody', {});
  const table = h('table', { class: 'claims-t', id: 'claim-list' },
    h('thead', {}, h('tr', {}, ['Compare', 'Claim', 'Verdict', 'Data says', 'Review', 'Evidence'].map((t) => h('th', { scope: 'col' }, t)))), tbody);
  stackTable(table);
  const none = h('div', { class: 'empty', hidden: true }, h('h2', {}, 'No claims match'), h('p', { class: 'muted' }, 'Change or clear the filters.'),
    h('button', { class: 'btn', type: 'button', onclick: () => { Object.assign(f, { q: '', verdict: '', review: false, flag: '', sort: 'verdict' }); saveFilters(); window.dispatchEvent(new Event('hashchange')); } }, 'Clear filters'));
  const count = h('p', { class: 'muted', role: 'status' });
  const bar = h('div', { class: 'compare-bar no-print', hidden: true });
  const sel = (id, label, opts, key) => h('label', {}, label, h('select', { id, onchange: (e) => { f[key] = e.target.value; saveFilters(); draw(); } },
    opts.map(([v, t]) => h('option', Object.assign({ value: v }, f[key] === v ? { selected: true } : {}), t))));
  const search = h('input', { type: 'search', id: 'search', value: f.q, placeholder: 'Search claims', 'aria-label': 'Search claims', oninput: (e) => { f.q = e.target.value; saveFilters(); draw(); } });
  root.append(h('h2', { class: 'list-h' }, 'Every claim'));
  root.append(h('div', { class: 'filters', role: 'search' },
    h('label', {}, 'Search', search),
    sel('f-verdict', 'Verdict', [['', 'All'], ['supported', 'Supported'], ['contradicted', 'Contradicted'], ['insufficient_evidence', 'Insufficient evidence'], ['blocked', 'Stopped by a safety check']], 'verdict'),
    sel('f-flag', 'Flag', [['', 'Any'], ['none', 'No flags'], ...flags.map((x) => [x, FLAG_TEXT[x] || x])], 'flag'),
    h('label', { class: 'inline' }, h('input', { type: 'checkbox', id: 'f-review', checked: f.review, onchange: (e) => { f.review = e.target.checked; saveFilters(); draw(); } }), 'Needs review only'),
    sel('f-sort', 'Sort', [['verdict', 'Problems first'], ['order', 'Report order'], ['review', 'Needs review first'], ['text', 'Claim text A to Z']], 'sort'),
    h('button', { class: 'btn', type: 'button', onclick: () => { Object.assign(f, { q: '', verdict: '', review: false, flag: '', sort: 'verdict' }); saveFilters(); window.dispatchEvent(new Event('hashchange')); } }, 'Clear')));
  root.append(count, table, none, bar, howWeChecked(all));

  function drawBar() {
    const s = state.selected;
    bar.hidden = !s.length;
    const two = s.length === 2;
    bar.replaceChildren(h('span', {}, s.length + ' selected. Pick two to compare.'),
      h('a', { class: 'btn primary', href: two ? '#/compare?a=' + s[0] + '&b=' + s[1] : null, 'aria-disabled': two ? null : 'true', style: two ? null : 'pointer-events:none', tabindex: two ? null : '-1' }, 'Compare selected'),
      h('button', { class: 'btn', type: 'button', onclick: () => { state.selected = []; draw(); } }, 'Clear selection'));
  }
  function draw() {
    shown = apply(); active = Math.min(active, shown.length - 1);
    count.textContent = shown.length + ' of ' + plural(all.length, 'claim') + ' shown';
    table.hidden = !shown.length; none.hidden = !!shown.length;
    tbody.replaceChildren(...shown.map((x, i) => row(x, i)));
    drawBar();
  }
  function row(x, i) {
    const cb = h('input', { type: 'checkbox', 'aria-label': 'Select for compare: ' + x.claim_text, checked: state.selected.includes(x.id) });
    cb.addEventListener('change', () => {
      if (cb.checked) { if (state.selected.length >= 2) state.selected.shift(); state.selected.push(x.id); }
      else state.selected = state.selected.filter((s) => s !== x.id);
      draw();
    });
    const tr = h('tr', { class: 'claim-row' + (i === active ? ' active' : ''), 'data-i': i },
      h('td', { class: 'pick no-print' }, cb),
      h('td', { class: 'claim-cell' }, h('p', { class: 'claim-text' }, x.claim_text), h('a', { class: 'cid', href: '#/claim/' + encodeURIComponent(x.id) }, x.id)),
      h('td', {}, verdictBadge(x)),
      h('td', {}, dataSays(x)),
      h('td', {}, x.needs_human_review ? 'needs review' : null),
      h('td', {}, h('a', { href: '#/claim/' + encodeURIComponent(x.id), 'aria-label': 'Open the evidence for ' + x.id }, 'Open')));
    // label each cell for the stacked phone layout (stackTable ran before the rows existed)
    [...tr.children].forEach((c, k) => { const t = ['Compare', 'Claim', 'Verdict', 'Data says', 'Review', 'Evidence'][k]; if (t) c.setAttribute('data-label', t); });
    return tr;
  }
  draw();
  return root;
}

export function resultsShortcut(e) {
  const links = () => document.querySelectorAll('.claim-row');
  const move = (d) => {
    e.preventDefault();
    if (!shown.length) return;
    active = Math.max(0, Math.min(shown.length - 1, active + d));
    links().forEach((r, i) => r.classList.toggle('active', i === active));
    links()[active].scrollIntoView({ block: 'nearest' });
  };
  if (e.key === 'j' || e.key === 'ArrowDown') move(1);
  else if (e.key === 'k' || e.key === 'ArrowUp') move(-1);
  else if (e.key === 'Enter' && active >= 0 && (e.target === document.body || e.target.id === 'main')) location.hash = '#/claim/' + encodeURIComponent(shown[active].id);
  else if (e.key === '/') { e.preventDefault(); const s = document.getElementById('search'); s && s.focus(); }
  else if (e.key === 'c') {
    if (state.selected.length === 2) location.hash = '#/compare?a=' + state.selected[0] + '&b=' + state.selected[1];
    else if (active >= 0 && shown.length > 1) location.hash = '#/compare?a=' + shown[active].id + '&b=' + shown[(active + 1) % shown.length].id;
    else import('../util.js').then((m) => m.toast('Select two claims first, or press j to pick a row.'));
  }
}
void hasNumber;
