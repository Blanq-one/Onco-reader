import { h, store, fmtNum, toast } from '../util.js';
import { state, loadData, findings, dataParam, DEMO_FILE } from '../state.js';
import { checkHealth, extractReport, pdfText } from '../live.js';

const rerender = () => window.dispatchEvent(new Event('hashchange'));
const MAX_CHARS = 100000;

function enter(dest) {
  const to = store('en.intended');
  store('en.intended', '');
  location.hash = to && to.startsWith('/') ? '#' + to : dest;
  if (location.hash === '#' + (to || '')) rerender();
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
    h('h1', {}, 'Audit the numbers in a research report'),
    h('p', { class: 'lead' }, 'Paste or upload a report. Each claim is pulled out, checked against the TCGA-BRCA data, and given a verdict with the calculation and the limit of what the data can say. A person reviews every verdict. This tool checks data readiness only. It makes no clinical claims.')));
  if (notice) root.append(h('div', { class: 'notice info', role: 'status' }, notice));
  if (state.error && !d) root.append(h('div', { class: 'notice err', role: 'alert' }, h('b', {}, 'Data could not be loaded. '), state.error));
  const liveSlot = h('div', { id: 'live-slot' });
  root.append(liveSlot);

  const demoMsg = h('div', { role: 'status', 'aria-live': 'polite' });
  const demoBtn = h('button', { class: 'btn big', type: 'button', id: 'demo-btn' }, 'Demo mode');
  demoBtn.onclick = async () => {
    demoBtn.disabled = true; demoMsg.replaceChildren(h('span', { class: 'muted' }, 'Loading the precomputed audit...'));
    const ok = await loadData(DEMO_FILE);
    if (ok) { state.mode = 'demo'; enter('#/extract'); } else { demoMsg.replaceChildren(h('div', { class: 'notice err', role: 'alert' }, state.error || 'The demo file could not be loaded.')); demoBtn.disabled = false; }
  };
  const demo = h('section', { class: 'card', 'aria-labelledby': 'demo-h' }, h('h2', { id: 'demo-h' }, 'Demo mode'),
    h('p', { class: 'muted' }, 'Works without a server. Shows the precomputed audit of the practice report from ' + DEMO_FILE.replace('out/', 'out/') + '.'),
    h('div', { class: 'row' }, demoBtn,
      d ? h('a', { class: 'btn', href: '#/results' }, 'Open the loaded results (' + fmtNum(findings().length) + ' claims)') : null,
      h('a', { class: 'btn', href: '#/about' }, 'How this works and what it will not do')), demoMsg);
  if (d) demo.append(h('div', { class: 'checks' }, h('span', { class: 'chip' }, 'Release: ' + ((d.data_release && d.data_release.name) || 'unknown')), checksumBadge(d),
    h('span', { class: 'chip' }, 'Report: ' + (d.report_title || 'untitled')), dataParam() ? h('span', { class: 'chip' }, 'Loaded from ?data=' + dataParam()) : null));
  root.append(demo);
  root.afterMount = () => liveBox(liveSlot);
  return root;
}

async function liveBox(slot) {
  if (!(await checkHealth()) || !slot.isConnected) return;
  const status = h('div', { role: 'status', 'aria-live': 'polite' });
  const ta = h('textarea', { id: 'report-text', rows: 10, placeholder: 'Paste the report text here.' });
  ta.value = state.reportText || '';
  const say = (cls, msg) => status.replaceChildren(msg ? h('div', { class: 'notice ' + cls, role: cls === 'err' ? 'alert' : 'status' }, msg) : '');
  const file = h('input', { type: 'file', id: 'report-file', accept: '.md,.txt,.pdf,text/plain,text/markdown,application/pdf' });
  file.addEventListener('change', async () => {
    const f = file.files[0]; if (!f) return;
    const isPdf = /\.pdf$/i.test(f.name) || f.type === 'application/pdf';
    if (isPdf) {
      say('info', 'Reading the PDF...');
      const t = await pdfText(f);
      if (t == null) { say('err', 'This server cannot read PDF files. Open the PDF yourself, copy the text, and paste it into the box below.'); return; }
      ta.value = t; state.reportTitle = f.name; say('info', 'PDF text loaded. Check it before you continue.');
    } else if (/\.(md|txt)$/i.test(f.name) || f.type.startsWith('text/')) {
      ta.value = await f.text(); state.reportTitle = f.name; say('', '');
    } else { say('err', 'Use a .md, .txt or .pdf file, or paste the text.'); }
  });
  const practice = h('button', { class: 'btn', type: 'button', id: 'practice-btn' }, 'Use the practice report');
  practice.onclick = async () => {
    try {
      const r = await fetch(new URL('../../samples/practice_brief.md', import.meta.url).href);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      ta.value = await r.text(); state.reportTitle = 'practice_brief.md'; say('', ''); ta.focus();
    } catch (e) { say('err', 'The practice report could not be loaded.'); }
  };
  const go = h('button', { class: 'btn primary', type: 'button', id: 'extract-btn' }, 'Extract claims');
  const cancel = h('button', { class: 'btn', type: 'button', hidden: true }, 'Cancel');
  let ctl; cancel.onclick = () => ctl && ctl.abort();
  go.onclick = async () => {
    const text = ta.value.trim();
    if (!text) { say('err', 'Paste a report or choose a file first.'); return; }
    if (text.length > MAX_CHARS) { say('err', 'This report is longer than ' + fmtNum(MAX_CHARS) + ' characters, which is more than the server accepts. Paste a shorter part.'); return; }
    ctl = new AbortController(); go.disabled = true; cancel.hidden = false;
    status.replaceChildren(h('div', { class: 'progress indet', 'aria-hidden': 'true' }, h('i')), h('span', {}, 'Finding the checkable claims...'));
    try {
      await extractReport(text, state.reportTitle, ctl.signal);
      state.mode = 'live-extract'; location.hash = '#/extract'; rerender();
    } catch (e) { say('err', e.name === 'AbortError' ? 'Cancelled.' : e.message); } finally { go.disabled = false; cancel.hidden = true; }
  };
  slot.replaceChildren(h('section', { class: 'card', 'aria-labelledby': 'live-h' }, h('h2', { id: 'live-h' }, 'Audit your own report'),
    h('p', { class: 'muted' }, 'Runs on this computer against the local data. Clinical or individual-patient requests are blocked.'),
    h('div', { class: 'row' }, practice, h('label', { for: 'report-file', class: 'muted' }, 'or upload a file (.md, .txt, .pdf)'), file),
    h('label', { for: 'report-text', class: 'muted', style: 'display:block;margin-top:12px' }, 'Report text'), ta,
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
