// Several reports, each audited on its own. Nothing is shared between reports: separate requests, separate results.
// File names and sample barcodes never reach the file list or the viewer (reports are "Report 1, 2, ..." and samples are renumbered per report).
import { h, fmtNum, plural, reduceMotion, toast } from '../util.js';
import { state, isBlocked } from '../state.js';
import { checkHealth, auditOnly, pdfText } from '../live.js';
import { verdictBadge, plainResult } from '../ui.js';
import { samplesPanel } from '../samples.js';
import { reportLabel, tally, pseudonymizer } from '../batch_logic.js';

const MAX_REPORTS = 10, MAX_CHARS = 100000;
// The example reports (app/samples). Ten, the most the view takes at once.
export const SAMPLES = [['practice_brief.md', 'Practice brief'], ['report_b.md', 'Data coverage'], ['report_c.md', 'Subtypes and mutations'],
  ['report_d.md', 'Clinical fields'], ['report_e.md', 'Sample types'], ['report_f.md', 'Survival follow-up'], ['report_g.md', 'RNA subtypes'],
  ['report_h.md', 'Mutation data'], ['report_i.md', 'Multi-omics overlap'], ['report_j.md', 'Study feasibility']];
const B = () => (state.batch = state.batch || { reports: [], index: 0, busy: false });

export function batchPage() {
  const root = h('div', { class: 'page', 'data-title': 'Multiple reports' });
  const adder = h('div', { id: 'batch-add' }), results = h('div', { id: 'batch-results' }), live = h('div', { class: 'sr', role: 'status', 'aria-live': 'polite', id: 'batch-live' });
  root.append(h('h1', {}, 'Several reports, one at a time'),
    h('p', { class: 'lead' }, 'Add more than one report. Each is audited separately and shows up as a file; open one to see its results. The reports do not share anything: no totals, no comparisons. File names and sample barcodes are hidden in the viewer.'),
    adder, results, live);
  const draw = () => { drawAdder(adder, draw); drawResults(results, live); };
  root.afterMount = async () => { await checkHealth(); draw(); };
  draw();
  return root;
}

// ---------- adding reports ----------
function drawAdder(slot, redraw) {
  const b = B();
  const status = h('div', { role: 'status', 'aria-live': 'polite' });
  const say = (msg, cls) => status.replaceChildren(msg ? h('div', { class: 'notice ' + (cls || 'info'), role: cls === 'err' ? 'alert' : 'status' }, msg) : '');
  const add = (text, name) => {
    if (b.reports.length >= MAX_REPORTS) { say('You can add up to ' + MAX_REPORTS + ' reports.', 'err'); return false; }
    if (!text.trim()) { say('That report is empty.', 'err'); return false; }
    if (text.length > MAX_CHARS) { say('A report is longer than ' + fmtNum(MAX_CHARS) + ' characters, which is more than the server accepts.', 'err'); return false; }
    b.reports.push({ text, name: name || '', doc: null, error: null, status: 'waiting' }); b.index = 0; return true;
  };
  const file = h('input', { type: 'file', id: 'batch-file', multiple: true, accept: '.md,.txt,.pdf,text/plain,text/markdown,application/pdf' });
  file.addEventListener('change', async () => {
    say('Reading the files...');
    let n = 0, bad = 0;
    for (const f of [...file.files]) {
      const pdf = /\.pdf$/i.test(f.name) || f.type === 'application/pdf';
      const text = pdf ? await pdfText(f) : (/\.(md|txt)$/i.test(f.name) || f.type.startsWith('text/')) ? await f.text() : null;
      if (text != null && add(text, f.name)) n++; else bad++;
    }
    file.value = '';
    redraw();
    if (bad) say(plural(bad, 'file') + ' could not be added (use .md, .txt or .pdf, and keep each under the size limit).', 'err');
    else if (n) say('Added ' + plural(n, 'report') + '.');
  });
  const examples = h('button', { class: 'btn', type: 'button', id: 'batch-examples' }, 'Add the ' + SAMPLES.length + ' example reports');
  examples.onclick = async () => {
    examples.disabled = true; say('Loading the examples...');
    try {
      b.reports = b.reports.filter((r) => !r.example); // adding them again replaces them instead of doubling up
      for (const [f, label] of SAMPLES) {
        const r = await fetch(new URL('../../samples/' + f, import.meta.url).href);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        if (add(await r.text(), label)) b.reports[b.reports.length - 1].example = true;
      }
      redraw();
    } catch (e) { say('The example reports could not be loaded.', 'err'); examples.disabled = false; }
  };
  const ta = h('textarea', { id: 'batch-paste', rows: 4, placeholder: 'Or paste one report here, then press Add.' });
  const paste = h('button', { class: 'btn', type: 'button' }, 'Add the pasted report');
  paste.onclick = () => { if (add(ta.value, 'Pasted text')) { ta.value = ''; redraw(); } };

  const list = h('ol', { class: 'batch-list' }, b.reports.map((r, i) => h('li', {},
    h('span', { class: 'chip' }, reportLabel(i)),
    h('span', { class: 'muted' }, (r.name ? r.name + ', ' : '') + fmtNum(r.text.length) + ' characters'),
    h('button', { class: 'btn', type: 'button', 'aria-label': 'Remove ' + reportLabel(i), disabled: b.busy || null, onclick: () => { b.reports.splice(i, 1); b.index = 0; redraw(); } }, 'Remove'))));
  const run = h('button', { class: 'btn primary', type: 'button', id: 'batch-run', disabled: (!b.reports.length || b.busy || !state.live) || null },
    b.busy ? 'Auditing...' : 'Audit ' + (b.reports.length > 1 ? 'all ' + b.reports.length + ' reports' : 'the report'));
  run.onclick = () => auditAll(redraw);
  // Arriving from Start with "Add the 10 example reports": load them once.
  if (state.batchPreset === 'examples') { state.batchPreset = null; setTimeout(() => examples.click(), 0); }
  slot.replaceChildren(h('section', { class: 'card', 'aria-labelledby': 'batch-h' }, h('h2', { id: 'batch-h' }, 'Add reports'),
    state.live ? null : h('div', { class: 'notice info', role: 'status' }, 'Auditing needs the local server (python server/serve.py). It is not answering right now.'),
    h('div', { class: 'row' }, examples, h('label', { for: 'batch-file', class: 'muted' }, 'or choose files (.md, .txt, .pdf)'), file),
    h('label', { for: 'batch-paste', class: 'muted', style: 'display:block;margin-top:12px' }, 'Paste a report'), ta, h('div', { class: 'row', style: 'margin-top:8px' }, paste),
    b.reports.length ? [h('h3', { class: 'batch-added' }, 'Added'), list, h('p', { class: 'muted' }, 'File names are shown here only so you can tell your files apart. The results use the labels above.')] : null,
    h('div', { class: 'row', style: 'margin-top:12px' }, run), status));
}

async function auditAll(redraw) {
  const b = B();
  b.busy = true; b.index = 0;
  b.reports.forEach((r) => { r.doc = null; r.error = null; r.status = 'waiting'; });
  redraw();
  for (let i = 0; i < b.reports.length; i++) {
    const r = b.reports[i]; r.status = 'working'; redraw();
    try { r.doc = await auditOnly(r.text, reportLabel(i)); r.status = 'done'; } catch (e) { r.error = e.message; r.status = 'failed'; }
    redraw();
  }
  b.busy = false; redraw();
  const live = document.getElementById('batch-live'); if (live) live.textContent = 'All reports audited.';
}

// ---------- audited reports as files, opened one at a time in a viewer ----------
let viewer = null; // { dialog, body, k, shown, opener }

function drawResults(slot, live) {
  const b = B(), shown = b.reports.map((r, i) => ({ r, i })).filter(({ r }) => r.status !== 'waiting');
  if (!shown.length) { slot.replaceChildren(); return; }
  // Closed files: only the number and whether it is ready. The results stay hidden until a file is opened.
  const state_ = (r) => (r.status === 'working' ? 'Auditing...' : r.status === 'failed' ? 'Could not be audited' : 'Ready to open');
  const cards = shown.map(({ r, i }, k) => {
    const card = h('button', { type: 'button', class: 'file-card ' + r.status, disabled: r.status === 'working' || null,
      'aria-label': reportLabel(i) + ', ' + state_(r).toLowerCase() + (r.status === 'done' ? '. Opens the report viewer.' : '') },
      h('span', { class: 'file-sheet', 'aria-hidden': 'true' }, h('span', { class: 'file-num' }, String(i + 1)), h('span', { class: 'file-lines' }, h('i'), h('i'), h('i'))),
      h('span', { class: 'file-name' }, reportLabel(i)),
      h('span', { class: 'file-state' }, state_(r)));
    card.addEventListener('click', () => openViewer(shown, k, card, live));
    return card;
  });
  // A one-row carousel moved by its arrows (no scroll bar): it shows as many files as fit.
  const track = h('div', { class: 'strip-track' }, cards);
  const win = h('div', { class: 'strip-window' }, track);
  const pos = h('span', { class: 'muted strip-pos', 'aria-live': 'polite' });
  const prev = h('button', { class: 'btn', type: 'button', 'aria-label': 'Earlier reports' }, '←');
  const next = h('button', { class: 'btn', type: 'button', 'aria-label': 'Later reports' }, '→');
  b.strip = b.strip || 0;
  const step = () => (cards[1] ? cards[1].offsetLeft - cards[0].offsetLeft : (cards[0] ? cards[0].offsetWidth : 1));
  const perView = () => Math.max(1, Math.floor((win.clientWidth + 12) / step()));
  const move = (to) => {
    const max = Math.max(0, cards.length - perView());
    b.strip = Math.max(0, Math.min(max, to));
    track.style.transform = 'translateX(' + (-b.strip * step()) + 'px)';
    cards.forEach((c, k) => { const vis = k >= b.strip && k < b.strip + perView(); c.tabIndex = vis ? 0 : -1; c.setAttribute('aria-hidden', vis ? 'false' : 'true'); });
    prev.disabled = b.strip === 0; next.disabled = b.strip >= max;
    pos.textContent = cards.length > perView() ? (b.strip + 1) + ' to ' + Math.min(cards.length, b.strip + perView()) + ' of ' + cards.length : cards.length + ' of ' + cards.length;
  };
  prev.onclick = () => move(b.strip - perView());
  next.onclick = () => move(b.strip + perView());
  win.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowRight') { e.preventDefault(); move(b.strip + 1); } else if (e.key === 'ArrowLeft') { e.preventDefault(); move(b.strip - 1); }
  });
  let x0 = null;
  win.addEventListener('pointerdown', (e) => { x0 = e.clientX; });
  win.addEventListener('pointerup', (e) => { if (x0 != null && Math.abs(e.clientX - x0) > 40) move(b.strip + (e.clientX < x0 ? 1 : -1) * perView()); x0 = null; });
  if (reduceMotion()) track.classList.add('still');
  slot.replaceChildren(
    h('div', { class: 'strip-head' }, h('h2', { id: 'car-h', class: 'list-h' }, 'Audited reports'), h('div', { class: 'strip-nav' }, pos, prev, next)),
    h('p', { class: 'muted files-note' }, 'Each report is a closed file. Open one to see its results. File names and sample barcodes stay hidden.'),
    h('section', { class: 'strip', 'aria-roledescription': 'carousel', 'aria-label': 'Audited reports' }, win));
  requestAnimationFrame(() => move(b.strip));
  // After the viewer closes: bring the file that was on show into view and give it focus.
  b.revealCard = (k) => { if (k < b.strip || k >= b.strip + perView()) move(k - Math.floor((perView() - 1) / 2)); return cards[k]; };
  if (!slot._resize) { slot._resize = true; window.addEventListener('resize', () => { const t = slot.querySelector('.strip-track'); if (t) drawResults(slot, live); }); }
  if (viewer && viewer.dialog.open) { viewer.shown = shown; showIn(viewer.k, false); }
}

function openViewer(shown, k, opener, live) {
  if (!viewer) {
    const body = h('div', { class: 'viewer-body' });
    const title = h('h2', { id: 'viewer-h' });
    const pos = h('span', { class: 'muted viewer-pos' });
    const prev = h('button', { class: 'btn', type: 'button', 'aria-label': 'Previous report', onclick: () => showIn(viewer.k - 1, true) }, '←');
    const next = h('button', { class: 'btn', type: 'button', 'aria-label': 'Next report', onclick: () => showIn(viewer.k + 1, true) }, '→');
    const close = h('button', { class: 'btn viewer-close', type: 'button', onclick: () => closeViewer() }, 'Close');
    const dialog = h('dialog', { class: 'viewer', 'aria-labelledby': 'viewer-h' },
      h('header', { class: 'viewer-head' }, h('div', {}, h('span', { class: 'viewer-kicker' }, 'Report viewer'), title), h('div', { class: 'viewer-nav' }, pos, prev, next, close)),
      body);
    dialog.addEventListener('cancel', (e) => { e.preventDefault(); closeViewer(); });
    dialog.addEventListener('click', (e) => { if (e.target === dialog) closeViewer(); }); // click on the backdrop
    dialog.addEventListener('keydown', (e) => {
      if (e.target.closest('textarea,input,select')) return;
      if (e.key === 'ArrowRight') { e.preventDefault(); showIn(viewer.k + 1, true); } else if (e.key === 'ArrowLeft') { e.preventDefault(); showIn(viewer.k - 1, true); }
    });
    document.body.append(dialog);
    viewer = { dialog, body, title, pos, prev, next, close, k: 0, shown: [], opener: null, live: null };
  }
  Object.assign(viewer, { shown, opener, live });
  showIn(k, false);
  viewer.dialog.classList.remove('closing');
  document.documentElement.classList.add('viewer-open'); // the page behind does not scroll while the viewer is open
  viewer.dialog.showModal();
  viewer.close.focus();
}

function showIn(k, animate) {
  const v = viewer, n = v.shown.length;
  v.k = ((k % n) + n) % n;
  const { r, i } = v.shown[v.k];
  const fill = () => {
    v.title.textContent = reportLabel(i);
    v.pos.textContent = (v.k + 1) + ' of ' + n;
    v.body.replaceChildren(...slideBody(r, i).filter(Boolean));
    v.prev.disabled = n < 2; v.next.disabled = n < 2;
    v.body.scrollTop = 0;
    if (animate && v.live) v.live.textContent = reportLabel(i) + ', ' + (v.k + 1) + ' of ' + n;
  };
  if (!animate || reduceMotion()) { fill(); return; }
  v.body.classList.add('swap');
  setTimeout(() => { fill(); v.body.classList.remove('swap'); }, 140);
}

function closeViewer() {
  const v = viewer; if (!v || !v.dialog.open) return;
  const done = () => { v.dialog.close(); v.dialog.classList.remove('closing'); document.documentElement.classList.remove('viewer-open');
    const card = B().revealCard ? B().revealCard(v.k) : v.opener; if (card && card.isConnected) card.focus(); };
  if (reduceMotion()) { done(); return; }
  v.dialog.classList.add('closing');
  setTimeout(done, 180);
}

function slideBody(r, i) {
  const label = reportLabel(i);
  if (r.status === 'working') return [h('h3', {}, label), h('div', { class: 'progress indet', 'aria-hidden': 'true' }, h('i')), h('p', { class: 'muted' }, 'Auditing this report...')];
  if (r.status === 'failed') return [h('h3', {}, label), h('div', { class: 'notice err', role: 'alert' }, 'This report could not be audited. ' + r.error), h('p', { class: 'muted' }, 'The other reports are not affected.')];
  const fs = r.doc.findings, t = tally(fs, isBlocked), pseudo = pseudonymizer();
  const seg = (n, cls, text) => n ? h('span', { class: 'seg ' + cls, style: 'flex-grow:' + n, title: n + ' ' + text }, n) : null;
  return [
    h('div', { class: 'slide-head' }, h('h3', {}, label), h('span', { class: 'muted' }, plural(t.total, 'claim') + ' checked')),
    h('div', { class: 'vbar', role: 'img', 'aria-label': t.supported + ' supported, ' + t.contradicted + ' contradicted, ' + t.insufficient + ' insufficient evidence, ' + t.blocked + ' blocked' },
      seg(t.supported, 'v-supported', 'supported'), seg(t.contradicted, 'v-contradicted', 'contradicted'), seg(t.insufficient, 'v-insufficient_evidence', 'insufficient evidence'), seg(t.blocked, 'v-blocked', 'blocked')),
    h('div', { class: 'scorecard mini', role: 'group', 'aria-label': label + ' figures' },
      [['v-supported', 'Match', t.supported], ['v-contradicted', 'Mismatch', t.contradicted], ['v-insufficient_evidence', 'Cannot settle', t.insufficient], ['v-blocked', 'Stopped', t.blocked], ['review', 'Need review', t.review]]
        .map(([cls, l, v]) => h('div', { class: 'sc-cell ' + cls + (v ? '' : ' zero') }, h('span', { class: 'sc-label' }, l), h('span', { class: 'sc-value' }, String(v))))),
    h('ul', { class: 'rep-claims' }, fs.map((f) => h('li', {},
      verdictBadge(f), h('p', { class: 'claim-text' }, f.claim_text), h('p', { class: 'muted' }, plainResult(f)),
      isBlocked(f) ? null : samplesPanel(f, { mask: pseudo, prefix: 'r' + i })))),
  ];
}
