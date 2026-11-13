import { h, fmtNum } from '../util.js';
import { state, extractData } from '../state.js';
import { breadcrumbs } from '../ui.js';
import { runAudit } from '../live.js';

export function extractPage() {
  const ex = extractData();
  const root = h('div', { class: 'page wide', 'data-title': 'Extraction' });
  const crumbs = breadcrumbs([{ label: 'Start', href: '#/' }, { label: 'Extraction' }]);
  root.append(h('h1', {}, 'Extraction: what will be checked'));
  const claims = ex.claims, skipped = ex.skipped;
  const canRun = state.mode === 'live-extract' && state.live && !!state.reportText;
  root.append(h('p', { class: 'muted' }, fmtNum(claims.length) + ' claims found, ' + fmtNum(skipped.length) + ' sentences skipped. Check that each claim matches the sentence it came from before the audit runs.'));

  root.append(h('section', { class: 'card', 'aria-labelledby': 'cl-h' }, h('h2', { id: 'cl-h' }, 'Claims and their source sentences'),
    claims.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'ex' },
      h('thead', {}, h('tr', {}, ['#', 'Claim to check', 'Sentence it came from'].map((t) => h('th', { scope: 'col' }, t)))),
      h('tbody', {}, claims.map((c, i) => h('tr', {}, h('td', {}, String(i + 1)), h('td', {}, c.text),
        h('td', { class: c.source === c.text ? 'muted' : null }, c.source === c.text ? 'Same sentence' : c.source))))))
      : h('p', { class: 'muted' }, 'No checkable claims were found in this report.')));

  root.append(h('details', { class: 'card', id: 'skipped' }, h('summary', {}, 'Skipped sentences (' + fmtNum(skipped.length) + ')'),
    skipped.length ? h('ul', { class: 'skips' }, skipped.map((s) => h('li', {}, h('span', {}, s.text), h('span', { class: 'chip' }, 'Skipped: ' + (s.reason || 'no reason given')))))
      : h('p', { class: 'muted' }, 'Nothing was skipped.')));

  const status = h('div', { role: 'status', 'aria-live': 'polite' });
  const row = h('div', { class: 'row' });
  if (canRun) {
    const go = h('button', { class: 'btn primary big', type: 'button', id: 'audit-btn' }, 'Run the audit');
    const cancel = h('button', { class: 'btn', type: 'button', hidden: true }, 'Cancel');
    let ctl, timer;
    cancel.onclick = () => ctl && ctl.abort();
    go.onclick = async () => {
      ctl = new AbortController(); go.disabled = true; cancel.hidden = false;
      const t0 = Date.now();
      const msg = h('span', {}, 'Checking ' + claims.length + ' claims against the data...');
      status.replaceChildren(h('div', { class: 'progress indet', 'aria-hidden': 'true' }, h('i')), msg);
      timer = setInterval(() => { msg.textContent = 'Checking ' + claims.length + ' claims against the data... ' + Math.round((Date.now() - t0) / 1000) + ' s'; }, 1000);
      try {
        await runAudit(ctl.signal);
        location.hash = '#/results'; window.dispatchEvent(new Event('hashchange'));
      } catch (e) {
        status.replaceChildren(h('div', { class: 'notice err', role: 'alert' }, e.name === 'AbortError' ? 'Cancelled.' : e.message));
      } finally { clearInterval(timer); go.disabled = false; cancel.hidden = true; }
    };
    row.append(go, cancel);
  } else {
    row.append(h('a', { class: 'btn primary big', href: '#/results' }, 'Open the audit results'));
  }
  row.append(h('a', { class: 'btn', href: '#/' }, 'Back to Start'));
  root.append(row, status);
  return { view: root, crumbs };
}
