// "Show the samples behind this number": the sample barcodes the engine counted (evidence.examples).
// Collapsed by default. Barcodes are shown as plain text, copied from the screen, or written to a CSV in this browser; nothing is sent anywhere.
import { h, copyText, toast, fmtNum } from './util.js';
import { forRoles } from './ui.js';

// One list of groups for a finding: its own examples, or the examples of each part of a sentence that has several numbers.
export function exampleGroups(f) {
  const e = f.evidence || {};
  const own = Array.isArray(e.examples) ? e.examples : [];
  if (own.length) return own.map((g) => ({ ...g, part: '' }));
  const out = [];
  for (const s of e.sub_checks || []) for (const g of s.examples || []) out.push({ ...g, part: s.claim || '' });
  return out;
}

export const csvCell = (v) => {
  const s = String(v == null ? '' : v);
  return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
};
export function toCsv(groups) {
  const rows = [['group', 'kind', 'sample_id']];
  for (const g of groups) for (const id of g.ids || []) rows.push([(g.part ? g.part.replace(/[.\s]+$/, '') + ': ' : '') + g.label, g.kind, id]);
  return rows.map((r) => r.map(csvCell).join(',')).join('\r\n') + '\r\n';
}
const allIds = (groups) => [...new Set(groups.flatMap((g) => g.ids || []))];
export const shownText = (g) => {
  const n = (g.ids || []).length;
  return n < g.total ? 'Showing the first ' + fmtNum(n) + ' of ' + fmtNum(g.total) : 'Showing all ' + fmtNum(g.total);
};

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  const a = h('a', { href: url, download: name, style: 'display:none' });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// opts.mask: a function that turns a barcode into a pseudonym (the multiple-reports view); opts.prefix keeps element ids unique.
export function samplesPanel(f, opts = {}) {
  let groups = exampleGroups(f);
  if (opts.mask) groups = groups.map((g) => ({ ...g, ids: (g.ids || []).map(opts.mask) }));
  if (!groups.length) return null;
  const pid = 'samples-' + (opts.prefix ? opts.prefix + '-' : '') + String(f.id).replace(/\W+/g, '-');
  const body = h('div', { class: 'calc', id: pid, hidden: true },
    groups.map((g, i) => h('div', { class: 'ex-group' },
      h('h3', { id: pid + '-h' + i }, (g.part ? g.part.replace(/[.\s]+$/, '') + ': ' : '') + g.label,
        h('span', { class: 'chip ' + (g.kind === 'fall_short' ? 'warn' : 'ok') }, g.kind === 'fall_short' ? 'Fall short' : 'Included')),
      h('p', { class: 'muted' }, shownText(g) + (g.total === 0 ? '. Nothing to list.' : '.')),
      (g.ids || []).length ? h('ul', { class: 'ids mono', tabindex: '0', role: 'region', 'aria-labelledby': pid + '-h' + i },
        g.ids.map((id) => h('li', {}, id))) : null)),
    h('p', { class: 'muted' }, opts.mask ? 'Sample names here are made up for this view and are numbered separately for each report. They do not match the manifest.' : 'These are de-identified research barcodes from the organizers\' manifest. They are not linked to anything else here.'),
    h('div', { class: 'row' },
      h('button', { class: 'btn', type: 'button', onclick: async () => {
        const ids = allIds(groups);
        toast((await copyText(ids.join('\n'))) ? 'Copied ' + fmtNum(ids.length) + ' IDs' : 'Copy failed. Select the text instead.');
      } }, 'Copy IDs'),
      h('button', { class: 'btn', type: 'button', onclick: () => download(f.id + '-samples.csv', toCsv(groups)) }, 'Download CSV')));
  const btn = h('button', { class: 'btn', type: 'button', 'aria-expanded': 'false', 'aria-controls': pid }, 'Show the samples behind this number');
  btn.addEventListener('click', () => {
    const open = body.hidden; body.hidden = !open;
    btn.setAttribute('aria-expanded', String(open)); btn.textContent = open ? 'Hide the samples' : 'Show the samples behind this number';
  });
  return h('section', { class: 'card', 'aria-labelledby': pid + '-t', 'data-for': forRoles('researcher', 'engineer') },
    h('h2', { id: pid + '-t' }, 'Samples behind this number'), btn, body);
}
