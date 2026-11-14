import { h } from '../util.js';
import { state, findings, saveFilters, FLAG_TEXT, isBlocked, hasNumber } from '../state.js';
import { verdictBadge, trustRow, heroVerdict, sourceLine, redFlags, flagChips, headlineText, shareText, factLine, plainResult, exportButtons, forRoles } from '../ui.js';
import { decisionPanel } from '../decisionPanel.js';
import { filesOf } from './claim.js';
import { pct, plural } from '../util.js';

let active = -1;
let shown = [];
const ORDER = { contradicted: 0, insufficient_evidence: 1, supported: 2 };

function apply() {
  const f = state.filters;
  const q = f.q.trim().toLowerCase();
  let out = findings().filter((x) =>
    (!f.verdict || (f.verdict === 'blocked' ? isBlocked(x) : x.verdict === f.verdict)) &&
    (!f.review || x.needs_human_review) &&
    (!f.flag || (f.flag === 'none' ? !x.guardrail_flags.length : x.guardrail_flags.includes(f.flag))) &&
    (!q || (x.claim_text + ' ' + x.id + ' ' + (x.evidence.metric_name || '')).toLowerCase().includes(q)));
  if (f.sort === 'verdict') out = out.slice().sort((a, b) => ORDER[a.verdict] - ORDER[b.verdict]);
  else if (f.sort === 'review') out = out.slice().sort((a, b) => Number(!!b.needs_human_review) - Number(!!a.needs_human_review));
  else if (f.sort === 'text') out = out.slice().sort((a, b) => a.claim_text.localeCompare(b.claim_text));
  return out;
}

export function resultsPage() {
  const root = h('div', { class: 'page', 'data-title': 'Results' });
  const all = findings();
  root.append(h('div', { class: 'title-row' }, h('h1', {}, 'Results'), exportButtons('Download the audit')));
  if (!all.length) {
    root.append(h('div', { class: 'empty' }, h('div', { class: 'ic', 'aria-hidden': 'true' }, '\u{1F4ED}'), h('h2', {}, 'No claims in this file'),
      h('p', { class: 'muted' }, 'The findings file loaded but holds no claims.'), h('a', { class: 'btn primary', href: '#/' }, 'Back to Start')));
    return root;
  }
  const pick = (p) => { Object.assign(state.filters, { verdict: '', review: false }, p); saveFilters(); window.dispatchEvent(new Event('hashchange'));
    setTimeout(() => { const l = document.getElementById('claim-list'); l && l.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 50); };
  root.append(sourceLine(), heroVerdict(all, pick), trustRow(all), redFlags(all));

  const flags = [...new Set(all.flatMap((x) => x.guardrail_flags))];
  const f = state.filters;
  const list = h('ul', { class: 'claims', id: 'claim-list' });
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
    sel('f-sort', 'Sort', [['order', 'Report order'], ['verdict', 'Verdict, problems first'], ['review', 'Needs review first'], ['text', 'Claim text A to Z']], 'sort'),
    h('button', { class: 'btn', type: 'button', onclick: () => { Object.assign(f, { q: '', verdict: '', review: false, flag: '', sort: 'order' }); saveFilters(); window.dispatchEvent(new Event('hashchange')); } }, 'Clear')));
  root.append(count, list, bar);
  const dp = decisionPanel('results');
  root.append(h('details', { class: 'dp-wrap' }, h('summary', {}, 'Record the team decision'), dp));

  function drawBar() {
    const s = state.selected;
    bar.hidden = !s.length;
    const two = s.length === 2;
    bar.replaceChildren(h('span', {}, s.length + ' selected. Pick two to compare.'),
      h('a', { class: 'btn primary', href: two ? '#/compare?a=' + s[0] + '&b=' + s[1] : null, 'aria-disabled': two ? null : 'true', style: two ? null : 'opacity:.5;pointer-events:none', tabindex: two ? null : '-1' }, 'Compare selected'),
      h('button', { class: 'btn', type: 'button', onclick: () => { state.selected = []; draw(); } }, 'Clear selection'));
  }
  function draw() {
    shown = apply(); active = Math.min(active, shown.length - 1);
    count.textContent = shown.length + ' of ' + plural(all.length, 'claim') + ' shown';
    if (!shown.length) {
      list.replaceChildren(h('li', { class: 'empty' }, h('h2', {}, 'No claims match'), h('p', { class: 'muted' }, 'Change or clear the filters.'),
        h('button', { class: 'btn', type: 'button', onclick: () => { Object.assign(f, { q: '', verdict: '', review: false, flag: '', sort: 'order' }); saveFilters(); window.dispatchEvent(new Event('hashchange')); } }, 'Clear filters')));
    } else list.replaceChildren(...shown.map((x, i) => row(x, i)));
    drawBar();
  }
  function row(x, i) {
    const hl = headlineText(x);
    const cb = h('input', { type: 'checkbox', 'aria-label': 'Select for compare: ' + x.claim_text, checked: state.selected.includes(x.id) });
    cb.addEventListener('change', () => {
      if (cb.checked) { if (state.selected.length >= 2) state.selected.shift(); state.selected.push(x.id); }
      else state.selected = state.selected.filter((s) => s !== x.id);
      draw();
    });
    return h('li', { class: 'claim-row' + (i === active ? ' active' : ''), 'data-i': i },
      h('div', { class: 'pick no-print' }, cb),
      h('a', { class: 'claim-link', href: '#/claim/' + encodeURIComponent(x.id) }, verdictBadge(x),
        h('div', { class: 'text' }, h('div', {}, x.claim_text),
          h('div', { class: 'plain-line' }, plainResult(x)),
          !x.correct_value && factLine(x) ? h('div', { class: 'muted', style: 'font-size:.9rem', 'data-for': forRoles('researcher', 'datause') }, factLine(x)) : null,
          filesOf(x).length ? h('div', { class: 'muted mono', style: 'font-size:.8rem', 'data-for': forRoles('engineer') }, 'Files: ' + filesOf(x).join(', ')) : null,
          h('div', { class: 'meta' }, h('span', { class: 'chip' }, x.id), flagChips(x))),
        h('div', { class: 'num', 'data-for': forRoles('researcher', 'engineer') }, hl ? [hl, h('small', {}, shareText(x))] : h('small', {}, isBlocked(x) ? 'No number' : 'No number available'))));
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
