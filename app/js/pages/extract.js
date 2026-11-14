import { h, fmtNum, plural, toast } from '../util.js';
import { state, extractData } from '../state.js';
import { breadcrumbs, stackTable } from '../ui.js';
import { runAudit } from '../live.js';
import { MAX_CHARS, isWithheld, editClaim, addClaim, checkAnyway, removeAdded } from '../extract_logic.js';

// Small view state that must survive the page being redrawn after each change.
const ui = { editing: null, focus: null, skippedOpen: false, scroll: null, error: '' };
const redraw = (focus) => { ui.focus = focus || null; ui.scroll = window.scrollY; window.dispatchEvent(new Event('hashchange')); };
const originChip = (c) => c.origin ? h('span', { class: 'chip review reviewer-chip' }, c.origin === 'edited' ? 'Edited by reviewer' : 'Added by reviewer') : null;

export function extractPage() {
  const ex = extractData();
  const root = h('div', { class: 'page wide', 'data-title': 'Extraction' });
  const crumbs = breadcrumbs([{ label: 'Start', href: '#/' }, { label: 'Extraction' }]);
  root.append(h('h1', {}, 'Extraction: what will be checked'));
  const claims = ex.claims, skipped = ex.skipped;
  const canRun = state.mode === 'live-extract' && state.live && !!state.reportText;
  const canEdit = canRun && state.extract === ex;   // changes only make sense when an audit can follow
  const say = h('div', { role: 'status', 'aria-live': 'polite', class: 'sr', id: 'ex-say' });
  root.append(h('p', { class: 'muted' }, plural(claims.length, 'claim') + ' found, ' + plural(skipped.length, 'sentence') + ' skipped. Check that each claim matches the sentence it came from before the audit runs.'
    + (canEdit ? ' You can rephrase a claim, check a skipped sentence anyway, or add a claim the tool missed.' : '')));
  if (ui.error) root.append(h('div', { class: 'notice err', role: 'alert' }, ui.error));

  const heads = ['#', 'Claim to check', 'Sentence it came from'].concat(canEdit ? ['Change'] : []);
  const claimRow = (c, i) => {
    const editing = canEdit && ui.editing === i;
    const cell = h('td', {});
    if (editing) {
      const ta = h('textarea', { id: 'ed-' + i, rows: 3, maxlength: String(MAX_CHARS), 'aria-label': 'Edit claim ' + (i + 1) }); ta.value = c.text;
      const save = () => { const r = editClaim(claims, i, ta.value); ui.error = r.ok ? '' : r.error; if (r.ok) ui.editing = null; redraw(r.ok ? 'edit-' + i : 'ed-' + i); };
      ta.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { e.preventDefault(); ui.editing = null; ui.error = ''; redraw('edit-' + i); }
        else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); save(); }
      });
      cell.append(ta, h('div', { class: 'row', style: 'margin-top:6px' },
        h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Save'),
        h('button', { class: 'btn', type: 'button', onclick: () => { ui.editing = null; ui.error = ''; redraw('edit-' + i); } }, 'Cancel'),
        h('span', { class: 'muted' }, 'Esc cancels. Ctrl or Cmd with Enter saves.')));
    } else {
      cell.append(c.text);
      const chip = originChip(c);
      if (chip) cell.append(' ', chip);
    }
    const src = c.source === c.text ? h('td', { class: 'muted' }, c.origin ? 'Your wording' : 'Same sentence') : h('td', {}, c.source);
    const tds = [h('td', {}, String(i + 1)), cell, src];
    if (canEdit) {
      const actions = h('td', {});
      if (!editing) {
        actions.append(h('button', { class: 'btn', type: 'button', id: 'edit-' + i, 'aria-label': 'Edit claim ' + (i + 1), onclick: () => { ui.editing = i; ui.error = ''; redraw('ed-' + i); } }, 'Edit'));
        if (c.edit && c.edit.kind !== 'edited') actions.append(' ', h('button', { class: 'btn', type: 'button', 'aria-label': 'Remove claim ' + (i + 1), onclick: () => { removeAdded(claims, i); ui.editing = null; redraw('add-text'); } }, 'Remove'));
      }
      tds.push(actions);
    }
    return h('tr', {}, tds);
  };
  root.append(h('section', { class: 'card', 'aria-labelledby': 'cl-h' }, h('h2', { id: 'cl-h' }, 'Claims and their source sentences'),
    claims.length ? h('div', { class: 'table-wrap' }, stackTable(h('table', { class: 'ex' },
      h('thead', {}, h('tr', {}, heads.map((t) => h('th', { scope: 'col' }, t)))), h('tbody', {}, claims.map(claimRow)))))
      : h('p', { class: 'muted' }, 'No checkable claims were found in this report.' + (canEdit ? ' You can add one below.' : ''))));

  if (canEdit) {
    const ta = h('textarea', { id: 'add-text', rows: 3, maxlength: String(MAX_CHARS), placeholder: 'For example: Protein data covers over 90 percent of primary tumors.' });
    const add = () => {
      const r = addClaim(ex, ta.value);
      ui.error = r.ok ? '' : r.error;
      if (r.ok) { ui.editing = null; toast('Added as claim ' + (r.index + 1)); redraw('edit-' + r.index); } else { ui.focus = 'add-text'; redraw('add-text'); }
    };
    root.append(h('section', { class: 'card', 'aria-labelledby': 'add-h' }, h('h2', { id: 'add-h' }, 'Add a claim'),
      h('p', { class: 'muted' }, 'Write a claim the tool missed, in a full sentence with its number. It is checked like the others and marked "Added by reviewer".'),
      h('label', { for: 'add-text', class: 'muted' }, 'Claim'), ta,
      h('div', { class: 'row', style: 'margin-top:8px' }, h('button', { class: 'btn', type: 'button', id: 'add-btn', onclick: add }, 'Add claim'))));
  }

  const skipList = skipped.map((s, j) => h('li', {},
    h('span', {}, s.text), h('span', { class: 'chip' }, 'Skipped: ' + (s.reason || 'no reason given')),
    canEdit && !isWithheld(s.text) ? h('button', { class: 'btn', type: 'button', id: 'anyway-' + j, onclick: () => {
      const r = checkAnyway(ex, j); ui.error = r.ok ? '' : r.error; ui.skippedOpen = true;
      if (r.ok) toast('Added as claim ' + (r.index + 1)); redraw(r.ok ? (skipped.length ? 'anyway-' + Math.min(j, skipped.length - 1) : 'edit-' + r.index) : 'anyway-' + j);
    } }, 'Check this anyway') : (canEdit ? h('span', { class: 'muted' }, 'Withheld: personal details') : null)));
  const det = h('details', { class: 'card', id: 'skipped' }, h('summary', {}, 'Skipped sentences (' + fmtNum(skipped.length) + ')'),
    skipped.length ? h('ul', { class: 'skips' }, skipList) : h('p', { class: 'muted' }, 'Nothing was skipped.'));
  if (ui.skippedOpen) det.setAttribute('open', '');
  det.addEventListener('toggle', () => { ui.skippedOpen = det.open; });
  root.append(det);

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
      const msg = h('span', {}, 'Checking ' + plural(claims.length, 'claim') + ' against the data...');
      status.replaceChildren(h('div', { class: 'progress indet', 'aria-hidden': 'true' }, h('i')), msg);
      timer = setInterval(() => { msg.textContent = 'Checking ' + plural(claims.length, 'claim') + ' against the data... ' + Math.round((Date.now() - t0) / 1000) + ' s'; }, 1000);
      try {
        await runAudit(ctl.signal);
        ui.editing = null; ui.error = '';
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
  root.append(row, status, say);
  // after a change the page is drawn again: put the scroll and the keyboard focus back where they were
  root.afterMount = () => {
    if (ui.scroll != null) { window.scrollTo(0, ui.scroll); ui.scroll = null; }
    if (ui.focus) { const el = document.getElementById(ui.focus); if (el) el.focus({ preventScroll: false }); ui.focus = null; }
  };
  return { view: root, crumbs };
}
