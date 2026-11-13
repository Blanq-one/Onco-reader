import { h, store, fmtNum } from '../util.js';
import { state, loadData, setData, findings } from '../state.js';

const rerender = () => window.dispatchEvent(new Event('hashchange'));
function enter() {
  const to = store('en.intended');
  store('en.intended', '');
  location.hash = to && to.startsWith('/') ? '#' + to : '#/results';
  if (!to) rerender();
}

export function checksumBadge(d) {
  const ok = d.data_release && (d.data_release.checksum_verified === true || d.data_release.checksum_status === 'verified');
  return h('span', { class: 'badge ' + (ok ? 'v-supported' : 'v-insufficient_evidence') },
    h('span', { class: 'ic', 'aria-hidden': 'true' }, ok ? '✓' : '!'), ok ? 'Checksum verified' : 'Checksum not verified');
}

export function startPage() {
  const d = state.data;
  const root = h('div', { class: 'page', 'data-title': 'Start' });
  const notice = state.notice; state.notice = null;
  root.append(h('section', { class: 'hero' },
    h('h1', {}, 'Check claims about TCGA-BRCA against the data'),
    h('p', { class: 'lead' }, 'Each claim gets a verdict, the numbers behind it, the calculation, and the limit of what the data can say. This tool checks data readiness only. It makes no clinical claims.')));
  if (notice) root.append(h('div', { class: 'notice info', role: 'status' }, notice));
  if (!d) {
    root.append(h('div', { class: 'notice err', role: 'alert' }, h('b', {}, 'Findings could not be loaded. '), state.error || 'Unknown error.'),
      h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: async (ev) => { ev.target.disabled = true; (await loadData()) ? enter() : rerender(); } }, 'Try again'),
        h('a', { class: 'btn', href: '#/about' }, 'About')),
      h('p', { class: 'muted', style: 'margin-top:16px' }, 'Serve the repository root with python -m http.server and open /app/. Add ?data=contract/mock_findings.json to load the sample file.'));
  } else {
    root.append(h('div', { class: 'checks' },
      h('span', { class: 'chip' }, 'Release: ' + ((d.data_release && d.data_release.name) || 'unknown')), checksumBadge(d),
      h('span', { class: 'chip' }, fmtNum(findings().length) + ' claims checked'), h('span', { class: 'chip' }, 'Report: ' + (d.report_title || 'untitled'))),
      h('div', { class: 'row' },
        h('button', { class: 'btn primary big', type: 'button', onclick: enter }, 'Open the demo findings'),
        h('a', { class: 'btn big', href: '#/about' }, 'How this works and what it will not do')));
  }
  const slot = h('div', { id: 'live-slot' });
  root.append(slot);
  root.afterMount = () => liveBox(slot);
  return root;
}

async function liveBox(slot) {
  let ok = false;
  try {
    const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 1500);
    const r = await fetch('/api/health', { signal: ctl.signal }); clearTimeout(t);
    ok = r.ok && (await r.json()).ok === true;
  } catch (e) { ok = false; }
  if (!ok || !slot.isConnected) return;
  state.live = true;
  const mode = h('select', { id: 'live-mode' }, h('option', { value: 'claims' }, 'One claim per line'), h('option', { value: 'report' }, 'Report text'));
  const ta = h('textarea', { id: 'live-text', placeholder: 'ER status is recorded for most samples.' });
  const status = h('div', { role: 'status', 'aria-live': 'polite' });
  const go = h('button', { class: 'btn primary', type: 'button' }, 'Check these claims');
  const cancel = h('button', { class: 'btn', type: 'button', hidden: true }, 'Cancel');
  let ctl;
  cancel.onclick = () => ctl && ctl.abort();
  go.onclick = async () => {
    const text = ta.value.trim();
    if (!text) { status.replaceChildren(h('div', { class: 'notice err' }, 'Type or paste at least one claim.')); return; }
    const body = mode.value === 'report' ? { report: text } : { claims: text.split(/\n+/).map((s) => s.trim()).filter(Boolean) };
    ctl = new AbortController(); go.disabled = true; cancel.hidden = false;
    status.replaceChildren(h('div', { class: 'progress indet', 'aria-hidden': 'true' }, h('i')), h('span', {}, 'Reading claims and running checks...'));
    try {
      const r = await fetch('/api/audit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: ctl.signal });
      const j = await r.json().catch(() => ({ error: 'The server sent an unreadable answer.' }));
      if (!r.ok || j.error) throw new Error(j.error || 'The server returned an error (HTTP ' + r.status + ').');
      setData(j, 'your claims (live)');
      location.hash = '#/results'; rerender();
    } catch (e) {
      status.replaceChildren(h('div', { class: 'notice err', role: 'alert' }, e.name === 'AbortError' ? 'Cancelled.' : e.message));
    } finally { go.disabled = false; cancel.hidden = true; }
  };
  slot.replaceChildren(h('section', { class: 'card' }, h('h2', {}, 'Run your own claims'),
    h('p', { class: 'muted' }, 'Runs on this computer against the local data. Clinical or individual-patient requests are blocked.'),
    h('label', { for: 'live-mode', class: 'muted' }, 'Input type '), mode, h('div', { style: 'height:8px' }), ta,
    h('div', { class: 'row', style: 'margin-top:8px' }, go, cancel), status));
}

export function aboutPage() {
  const d = state.data;
  const root = h('div', { class: 'page', 'data-title': 'About' });
  root.append(h('h1', {}, 'How this works and what it will not do'));
  root.append(h('section', { class: 'card' }, h('h2', {}, 'Data release'),
    d ? h('div', { class: 'row' }, h('span', {}, (d.data_release && d.data_release.name) || 'unknown'), checksumBadge(d),
      d.schema_version ? h('span', { class: 'chip' }, 'schema ' + d.schema_version) : null)
      : h('p', { class: 'muted' }, 'No findings are loaded, so there is no release to show.')));
  root.append(h('section', { class: 'card' }, h('h2', {}, 'The rules'), h('ul', {},
    h('li', {}, 'No clinical claims. Nothing here is a diagnosis, a treatment recommendation or a risk score.'),
    h('li', {}, 'No individual patients. Requests about one person are blocked.'),
    h('li', {}, 'Every number comes with its calculation and source files.'),
    h('li', {}, 'Every finding shows its limitation. It cannot be hidden.'),
    h('li', {}, 'A person makes the final call on anything marked needs review.'))));
  root.append(h('section', { class: 'card' }, h('h2', {}, 'What each verdict means'), h('dl', { class: 'keys' },
    h('dt', {}, h('span', { class: 'badge v-supported' }, '✓ Supported')), h('dd', {}, 'The data, read the way the claim is worded, meets the claim.'),
    h('dt', {}, h('span', { class: 'badge v-contradicted' }, '✕ Contradicted')), h('dd', {}, 'The data, read the same way, does not meet the claim.'),
    h('dt', {}, h('span', { class: 'badge v-insufficient_evidence' }, '? Insufficient evidence')), h('dd', {}, 'The data cannot settle the claim: too few samples, a missing column, or no measurable threshold.'),
    h('dt', {}, h('span', { class: 'badge v-blocked' }, '⛔ Blocked')), h('dd', {}, 'The request was stopped before any analysis. No number is shown.'))));
  const notes = d && d.data_notes;
  const sec = h('section', { class: 'card' }, h('h2', {}, 'Which clinical column was used and why'));
  if (!notes || !notes.length) sec.append(h('p', { class: 'muted' }, 'This findings file has no data notes.'));
  else sec.append(h('div', { class: 'table-wrap' }, h('table', {},
    h('thead', {}, h('tr', {}, ['Attribute', 'Column used', 'Chosen because', 'Recorded', 'Alternatives'].map((t) => h('th', { scope: 'col' }, t)))),
    h('tbody', {}, notes.map((n) => h('tr', {},
      h('td', {}, n.attribute), h('td', { class: 'mono' }, n.column_used), h('td', {}, n.chosen_by),
      h('td', {}, fmtNum(n.primary_tumors_with_recorded_value) + ' of ' + fmtNum(n.primary_tumors)),
      h('td', {}, (n.alternatives || []).length ? (n.alternatives).map((a) => h('div', { class: 'mono' }, a.column + ' (' + fmtNum(a.primary_tumors_with_recorded_value) + ')')) : 'none')))))));
  root.append(sec);
  const ic = d && d.interpretation_config;
  if (ic) root.append(h('section', { class: 'card' }, h('h2', {}, 'How wording is read'),
    h('p', { class: 'muted' }, 'Vague words in a claim are turned into thresholds. These are the settings used for this file.'),
    h('div', { class: 'table-wrap' }, h('table', {}, h('tbody', {}, Object.entries(ic).map(([k, v]) => h('tr', {}, h('th', { scope: 'row' }, k), h('td', { class: 'mono' }, String(v)))))))));
  return root;
}

export function notFoundPage() {
  return h('div', { class: 'page empty', 'data-title': 'Not found' }, h('div', { class: 'ic', 'aria-hidden': 'true' }, '\u{1F9ED}'),
    h('h1', {}, 'That page does not exist'), h('p', { class: 'muted' }, 'The link may be old, or the claim is not in the loaded file.'),
    h('a', { class: 'btn primary', href: '#/' }, 'Go to Start'));
}
