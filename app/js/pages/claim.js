import { h, countUp, copyText, toast, fmtNum, fmtValue, pct, plural } from '../util.js';
import { state, findings, isBlocked, cannotAnswer, hasNumber, VERDICT, FLAG_TEXT } from '../state.js';
import { samplesPanel } from '../samples.js';
import { verdictBadge, flagChips, caption, funnel, breakdownChart, reviewBlock, claimFacts, breadcrumbs, plainResult, interpTag, forRoles, isRatio, valueText, groupsText, isSurvivalGroups, deathsText } from '../ui.js';

const enc = encodeURIComponent;

// Where the reader came from, so the way back keeps their place.
const ORIGIN = { summary: ['Summary', (id) => '#/summary?at=' + enc(id)], results: ['Results', () => '#/results'], review: ['Review queue', (id) => '#/review?id=' + enc(id)] };

export function claimPage(f, q) {
  const all = findings();
  const i = all.indexOf(f);
  const prev = all[i - 1], next = all[i + 1];
  const e = f.evidence;
  const from = ORIGIN[q && q.get('from')] ? q.get('from') : 'results';
  const [backLabel, backHref] = ORIGIN[from];
  const keep = from === 'results' ? '' : '?from=' + from;
  const root = h('div', { class: 'page', 'data-title': f.id });
  const arrow = (t, label, x) => x ? h('a', { class: 'btn', href: '#/claim/' + enc(x.id) + keep, 'aria-label': label + ': ' + x.claim_text }, t) : h('span', { class: 'btn', 'aria-disabled': 'true', style: 'opacity:.4' }, t);
  root.append(h('div', { class: 'pager no-print' }, arrow('← Previous', 'Previous claim', prev), h('span', { class: 'muted' }, 'Claim ' + (i + 1) + ' of ' + all.length), arrow('Next →', 'Next claim', next)));
  root.append(h('h1', {}, f.claim_text));
  root.append(h('p', { class: 'plain' }, verdictBadge(f), ' ', h('span', {}, plainResult(f))));
  root.append(...claimFacts(f));

  // verdict / blocked / cannot answer
  if (isBlocked(f)) {
    root.append(h('section', { class: 'card', 'aria-labelledby': 'vh' }, h('h2', { id: 'vh' }, 'Blocked'),
      h('div', { class: 'row' }, verdictBadge(f), flagChips(f)),
      h('div', { class: 'notice block', role: 'note', style: 'margin-top:12px' }, 'This request was stopped before any analysis, so there is no number and no result. ',
        h('span', { 'data-for': forRoles('datause') }, f.review_reason || '')),
      h('p', { class: 'muted', 'data-for': forRoles('datause') }, 'Reason flags: ' + f.guardrail_flags.map((x) => FLAG_TEXT[x] || x).join(', '))));
  } else if (cannotAnswer(f) || e.value == null) {
    root.append(h('section', { class: 'card', 'aria-labelledby': 'vh' }, h('h2', { id: 'vh' }, 'The data cannot answer this'),
      h('div', { class: 'row' }, verdictBadge(f), flagChips(f)),
      h('p', { style: 'margin-top:12px', 'data-for': forRoles('researcher', 'datause', 'engineer') }, h('b', {}, 'What is missing: '), e.calculation || 'The needed field is not in the data.')));
  } else {
    const big = h('span', { class: 'big' }, fmtNum(e.n_samples));
    if (isRatio(f)) big.textContent = Number(e.value).toFixed(2); else countUp(big, e.n_samples);
    const lowEvents = f.guardrail_flags.includes('low_event_count');
    root.append(h('section', { class: 'card', 'aria-labelledby': 'vh' }, h('h2', { id: 'vh' }, 'Verdict'),
      h('div', { class: 'row' }, verdictBadge(f), flagChips(f)),
      isSurvivalGroups(f)
        ? h('p', { class: 'headline-text' }, h('b', {}, 'OS deaths by group: '), deathsText(f) + '. Not judged: a survival difference needs a statistician\'s test.')
        : h('div', { class: 'headline', 'data-for': forRoles('researcher', 'engineer') }, big,
          isRatio(f) ? [h('span', { class: 'of' }, 'to 1'), h('span', { class: 'p' }, groupsText(f))]
            : [h('span', { class: 'of' }, 'of ' + fmtNum(e.denominator)), h('span', { class: 'p' }, pct(e.n_samples, e.denominator))]),
      h('p', { class: 'caption', style: 'margin:4px 0 8px', 'data-for': forRoles('researcher', 'engineer') }, caption(f)),
      h('div', { class: 'muted', 'data-for': forRoles('engineer') }, 'Metric: ', h('span', { class: 'mono' }, e.metric_name || 'unknown'), ' | value ' + valueText(f))));
    if (lowEvents) root.append(h('div', { class: 'notice', role: 'alert', 'data-for': forRoles('datause', 'researcher') }, h('b', {}, '⚠ Low event count. '), 'Too few deaths for a stable comparison. This finding is flagged for review.'));
  }

  // limitation: always visible
  root.append(h('section', { class: 'limit', role: 'note', 'aria-labelledby': 'lh' }, h('h2', { id: 'lh' }, 'Limitation'), h('p', { style: 'margin:0' }, f.limitation || 'No limitation was provided in the file. Treat this finding as unverified.')));

  // funnel
  if (!isBlocked(f)) root.append(h('section', { class: 'card', 'aria-labelledby': 'fh', 'data-for': forRoles('engineer') }, h('h2', { id: 'fh' }, 'Cohort funnel'),
    h('p', { class: 'muted' }, 'How many samples remain after each step.'), funnel(f.cohort_trace)));

  // calculation
  root.append(calcPanel(f));
  { const sp = isBlocked(f) ? null : samplesPanel(f); if (sp) root.append(sp); }
  root.append(columnsUsed(f));

  // breakdown
  if (Array.isArray(e.breakdown) && e.breakdown.length && !isBlocked(f)) root.append(h('section', { class: 'card', 'aria-labelledby': 'bh', 'data-for': forRoles('researcher') }, h('h2', { id: 'bh' }, 'Breakdown by group'), breakdownChart(e.breakdown)));

  // robustness
  if (!isBlocked(f)) { const rb = robustness(f); rb.setAttribute('data-for', forRoles('researcher')); root.append(rb); }

  // next actions
  root.append(h('section', { class: 'card', 'aria-labelledby': 'nh' }, h('h2', { id: 'nh' }, 'Next actions ', interpTag()),
    f.next_actions.length ? h('ol', { class: 'actions' }, f.next_actions.map((a) => h('li', {}, a))) : h('p', { class: 'muted' }, 'No next actions were listed.')));

  // review
  root.append(h('section', { class: 'card', 'aria-labelledby': 'rh' }, h('h2', { id: 'rh' }, f.needs_human_review ? 'Needs review' : 'Your review'),
    f.needs_human_review ? h('p', { 'data-for': forRoles('datause') }, h('b', {}, 'Why: '), f.review_reason || 'No reason was given.') : null,
    f.needs_human_review ? h('p', { class: 'muted', 'data-for': forRoles('leader', 'researcher', 'engineer') }, 'A person must check this claim before it is used. The data-use reviewer view shows why.') : null,
    reviewBlock(f)));

  const other = next || prev;
  root.append(h('div', { class: 'row no-print' },
    other ? h('a', { class: 'btn', href: '#/compare?a=' + enc(f.id) + '&b=' + enc(other.id) }, 'Compare with another claim') : null,
    h('a', { class: 'btn', href: '#/review?id=' + enc(f.id) }, 'Review this'),
    h('a', { class: 'btn', href: backHref(f.id) }, 'Back to ' + backLabel)));

  return { view: root, crumbs: breadcrumbs([{ label: backLabel, href: backHref(f.id) }, { label: f.id }]) };
}

function calcPanel(f) {
  const e = f.evidence;
  const panel = h('div', { class: 'calc', id: 'calc-panel', hidden: true },
    h('h3', {}, 'Calculation'), h('pre', {}, e.calculation || 'No calculation text.'),
    h('h3', {}, 'Source files'),
    (e.source_files || []).length ? h('ul', { class: 'mono' }, e.source_files.map((s) => h('li', {}, s))) : h('p', { class: 'muted' }, 'No source files. Nothing was computed.'),
    h('p', { class: 'muted' }, 'Metric ' + (e.metric_name || 'unknown') + ', value ' + valueText(f) + ', ' + fmtNum(e.n_samples) + ' of ' + plural(e.denominator, 'sample') + '.'),
    h('button', { class: 'btn', type: 'button', onclick: async () => {
      const txt = [f.id + ': ' + f.claim_text, 'Verdict: ' + f.verdict, 'Metric: ' + e.metric_name + ' = ' + valueText(f) + ' (' + e.n_samples + ' of ' + e.denominator + ')',
        'Calculation: ' + e.calculation, 'Sources: ' + (e.source_files || []).join(', '), 'Limitation: ' + f.limitation].join('\n');
      toast((await copyText(txt)) ? 'Calculation copied' : 'Copy failed. Select the text instead.');
    } }, 'Copy calculation'));
  const btn = h('button', { class: 'btn', type: 'button', 'aria-expanded': 'false', 'aria-controls': 'calc-panel' }, 'Show me the calculation');
  btn.addEventListener('click', () => {
    const open = panel.hidden; panel.hidden = !open;
    btn.setAttribute('aria-expanded', String(open)); btn.textContent = open ? 'Hide the calculation' : 'Show me the calculation';
  });
  return h('section', { class: 'card', 'aria-labelledby': 'ch', 'data-for': forRoles('researcher', 'engineer') }, h('h2', { id: 'ch' }, 'Calculation and sources'), btn, panel);
}

// For the data engineer: the files and columns behind a finding, and whether the files matched their checksums.
export function columnsOf(f) {
  const e = f.evidence, cols = [];
  for (const s of e.source_files || []) { const m = String(s).match(/\(([^)]+)\)/); if (m) cols.push(m[1]); }
  for (const m of String(e.calculation || '').matchAll(/read from (\S+?)(?=[\s(;,]|$)/g)) cols.push(m[1]);
  return [...new Set(cols)];
}
export const filesOf = (f) => [...new Set((f.evidence.source_files || []).map((s) => String(s).replace(/\s*\(.*\)$/, '')))];
function columnsUsed(f) {
  const rel = (state.data && state.data.data_release) || {};
  const files = filesOf(f), cols = columnsOf(f);
  return h('section', { class: 'card', 'aria-labelledby': 'uh', 'data-for': forRoles('engineer') }, h('h2', { id: 'uh' }, 'Columns and files used'),
    h('dl', { class: 'keys' },
      h('dt', {}, 'Files'), h('dd', { class: 'mono' }, files.length ? files.join(', ') : 'none (nothing was computed)'),
      h('dt', {}, 'Columns'), h('dd', { class: 'mono' }, cols.length ? cols.join(', ') : 'none named beyond the files above'),
      h('dt', {}, 'Checksums'), h('dd', {}, (rel.checksum_status || 'unknown') + (rel.checksum_status === 'verified' ? ': every data file matched sources.csv' : ': the files were not confirmed against sources.csv')),
      h('dt', {}, 'Cohort steps'), h('dd', {}, f.cohort_trace.length ? f.cohort_trace.map((t) => t.step + ' ' + fmtNum(t.n_after)).join(' → ') : 'none')));
}

function robustness(f) {
  const r = f.robustness;
  const sec = h('section', { class: 'card', 'aria-labelledby': 'roh' }, h('h2', { id: 'roh' }, 'Robustness'));
  if (!r) { sec.append(h('p', { class: 'muted' }, 'No alternative rule was tested for this claim.')); return sec; }
  const body = h('div', { hidden: true, id: 'rob-body', style: 'margin-top:12px' },
    h('p', {}, h('b', {}, 'Alternative rule: '), r.alt_rule),
    h('p', {}, h('b', {}, 'Value under it: '), valueText(f, r.alt_value), ' (main rule: ' + valueText(f) + ')'),
    h('div', { class: 'notice ' + (r.verdict_changes ? '' : 'info'), role: 'status' }, r.verdict_changes
      ? h('span', {}, h('b', {}, '⚠ The verdict changes '), 'under this rule. Treat the main result with care.')
      : h('span', {}, h('b', {}, '✓ The verdict does not change '), 'under this rule.')));
  const b = h('button', { class: 'btn', type: 'button', 'aria-pressed': 'false', 'aria-controls': 'rob-body' }, 'Try the alternative rule');
  b.addEventListener('click', () => { const on = b.getAttribute('aria-pressed') !== 'true'; b.setAttribute('aria-pressed', String(on)); body.hidden = !on; });
  sec.append(h('p', { class: 'muted' }, 'Same claim, a different inclusion rule.'), b, body);
  return sec;
}

export function claimShortcut(e, id, ids, from) {
  const i = ids.indexOf(id);
  const keep = ORIGIN[from] && from !== 'results' ? '?from=' + from : '';
  const to = (j) => { if (ids[j]) { e.preventDefault(); location.hash = '#/claim/' + enc(ids[j]) + keep; } };
  if (e.key === 'j' || e.key === 'ArrowRight') to(i + 1);
  else if (e.key === 'k' || e.key === 'ArrowLeft') to(i - 1);
  else if (e.key === 'c') location.hash = '#/compare?a=' + enc(id) + '&b=' + enc(ids[i + 1] || ids[i - 1] || id);
}
void VERDICT; void hasNumber; void state;
