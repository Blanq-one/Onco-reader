// Several reports, each audited on its own. Nothing is shared between reports: separate requests, separate results.
// File names and sample barcodes never reach the carousel (reports are "Report A, B, ..." and samples are renumbered per report).
import { h, fmtNum, plural, reduceMotion, toast } from '../util.js';
import { state, isBlocked } from '../state.js';
import { checkHealth, auditOnly, pdfText } from '../live.js';
import { verdictBadge, plainResult } from '../ui.js';
import { samplesPanel } from '../samples.js';
import { reportLabel, tally, pseudonymizer } from '../batch_logic.js';

const MAX_REPORTS = 10, MAX_CHARS = 100000;
const SAMPLES = [['practice_brief.md', 'Practice brief'], ['report_b.md', 'Report B'], ['report_c.md', 'Report C']];
const B = () => (state.batch = state.batch || { reports: [], index: 0, busy: false });

export function batchPage() {
  const root = h('div', { class: 'page', 'data-title': 'Multiple reports' });
  const adder = h('div', { id: 'batch-add' }), results = h('div', { id: 'batch-results' }), live = h('div', { class: 'sr', role: 'status', 'aria-live': 'polite', id: 'batch-live' });
  root.append(h('h1', {}, 'Several reports, one at a time'),
    h('p', { class: 'lead' }, 'Add more than one report. Each is audited separately, and the results appear as slides. The reports do not share anything: no totals, no comparisons. File names and sample barcodes are hidden in the slides.'),
    adder, results, live);
  const draw = () => { drawAdder(adder, draw); drawResults(results, live, draw); };
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
  const examples = h('button', { class: 'btn', type: 'button', id: 'batch-examples' }, 'Add the three example reports');
  examples.onclick = async () => {
    examples.disabled = true; say('Loading the examples...');
    try {
      for (const [f, label] of SAMPLES) {
        const r = await fetch(new URL('../../samples/' + f, import.meta.url).href);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        add(await r.text(), label);
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
  slot.replaceChildren(h('section', { class: 'card', 'aria-labelledby': 'batch-h' }, h('h2', { id: 'batch-h' }, 'Add reports'),
    state.live ? null : h('div', { class: 'notice info', role: 'status' }, 'Auditing needs the local server (python server/serve.py). It is not answering right now.'),
    h('div', { class: 'row' }, examples, h('label', { for: 'batch-file', class: 'muted' }, 'or choose files (.md, .txt, .pdf)'), file),
    h('label', { for: 'batch-paste', class: 'muted', style: 'display:block;margin-top:12px' }, 'Paste a report'), ta, h('div', { class: 'row', style: 'margin-top:8px' }, paste),
    b.reports.length ? [h('h3', {}, 'Added'), list, h('p', { class: 'muted' }, 'File names are shown here only so you can tell your files apart. The slides use the labels above.')] : null,
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

// ---------- the carousel ----------
function drawResults(slot, live, redraw) {
  const b = B(), shown = b.reports.map((r, i) => ({ r, i })).filter(({ r }) => r.status !== 'waiting');
  if (!shown.length) { slot.replaceChildren(); return; }
  const n = shown.length;
  b.index = Math.min(b.index, n - 1);
  const track = h('div', { class: 'car-track' });
  const slides = shown.map(({ r, i }, k) => {
    const s = h('article', { class: 'car-slide', role: 'group', 'aria-roledescription': 'slide', 'aria-label': reportLabel(i) + ', slide ' + (k + 1) + ' of ' + n }, slideBody(r, i));
    track.append(s); return s;
  });
  const dots = h('div', { class: 'car-dots' });
  const go = (to, speak) => {
    b.index = (to + n) % n;
    track.style.transform = 'translateX(' + (-100 * b.index) + '%)';
    slides.forEach((s, k) => { if (k === b.index) s.removeAttribute('inert'); else s.setAttribute('inert', ''); });
    [...dots.children].forEach((d, k) => d.setAttribute('aria-current', String(k === b.index)));
    prevBtn.disabled = n < 2; nextBtn.disabled = n < 2;
    if (speak) live.textContent = reportLabel(shown[b.index].i) + ', slide ' + (b.index + 1) + ' of ' + n;
  };
  const prevBtn = h('button', { class: 'btn', type: 'button', 'aria-label': 'Previous report', onclick: () => go(b.index - 1, true) }, '← Previous');
  const nextBtn = h('button', { class: 'btn', type: 'button', 'aria-label': 'Next report', onclick: () => go(b.index + 1, true) }, 'Next →');
  shown.forEach(({ i }, k) => dots.append(h('button', { class: 'dot', type: 'button', 'aria-label': 'Show ' + reportLabel(i), onclick: () => go(k, true) })));
  const view = h('section', { class: 'carousel', 'aria-roledescription': 'carousel', 'aria-label': 'Results for each report', tabindex: '-1' },
    h('div', { class: 'car-viewport' }, track),
    h('div', { class: 'car-controls no-print' }, prevBtn, dots, nextBtn));
  view.addEventListener('keydown', (e) => {
    if (e.target.closest('textarea,input,select')) return;
    if (e.key === 'ArrowRight') { e.preventDefault(); go(b.index + 1, true); } else if (e.key === 'ArrowLeft') { e.preventDefault(); go(b.index - 1, true); }
  });
  // swipe, ignoring drags that start on the sample lists or buttons
  let x0 = null;
  view.addEventListener('pointerdown', (e) => { x0 = e.target.closest('button,.ids,a,input') ? null : e.clientX; });
  view.addEventListener('pointerup', (e) => { if (x0 != null && Math.abs(e.clientX - x0) > 50) go(b.index + (e.clientX < x0 ? 1 : -1), true); x0 = null; });
  if (reduceMotion()) track.classList.add('still');
  slot.replaceChildren(h('h2', { id: 'car-h' }, 'Results'), view);
  go(b.index, false);
}

function slideBody(r, i) {
  const label = reportLabel(i);
  if (r.status === 'working') return [h('h3', {}, label), h('div', { class: 'progress indet', 'aria-hidden': 'true' }, h('i')), h('p', { class: 'muted' }, 'Auditing this report...')];
  if (r.status === 'failed') return [h('h3', {}, label), h('div', { class: 'notice err', role: 'alert' }, 'This report could not be audited. ' + r.error), h('p', { class: 'muted' }, 'The other reports are not affected.')];
  const fs = r.doc.findings, t = tally(fs, isBlocked), pseudo = pseudonymizer();
  const seg = (n, cls, text) => n ? h('span', { class: 'seg ' + cls, style: 'flex-grow:' + n, title: n + ' ' + text }, n) : null;
  return [
    h('h3', {}, label, h('span', { class: 'muted' }, '  ' + plural(t.total, 'claim'))),
    h('div', { class: 'vbar', role: 'img', 'aria-label': t.supported + ' supported, ' + t.contradicted + ' contradicted, ' + t.insufficient + ' insufficient evidence, ' + t.blocked + ' blocked' },
      seg(t.supported, 'v-supported', 'supported'), seg(t.contradicted, 'v-contradicted', 'contradicted'), seg(t.insufficient, 'v-insufficient_evidence', 'insufficient evidence'), seg(t.blocked, 'v-blocked', 'blocked')),
    h('p', { class: 'row' },
      h('span', { class: 'badge v-supported' }, '✓ ' + t.supported + ' supported'), h('span', { class: 'badge v-contradicted' }, '✕ ' + t.contradicted + ' contradicted'),
      h('span', { class: 'badge v-insufficient_evidence' }, '? ' + t.insufficient + ' insufficient'), t.blocked ? h('span', { class: 'badge v-blocked' }, '⛔ ' + t.blocked + ' blocked') : null,
      t.review ? h('span', { class: 'chip review' }, t.review + ' need review') : null),
    h('ul', { class: 'car-claims' }, fs.map((f) => h('li', {},
      h('div', {}, verdictBadge(f)), h('p', { class: 'claim-text' }, f.claim_text), h('p', { class: 'muted' }, plainResult(f)),
      isBlocked(f) ? null : samplesPanel(f, { mask: pseudo, prefix: 'r' + i })))),
    h('p', { class: 'muted' }, 'Data readiness only. No clinical claims. Sample names are made up for this view.'),
  ];
}
