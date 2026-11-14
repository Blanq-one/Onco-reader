import { h, store, toast, reduceMotion } from './util.js';
import { verificationBar } from './ui.js';
import { state, dataParam, loadData, byId, findings, ROLES, getRole, setRole } from './state.js';
import { startPage, aboutPage, notFoundPage } from './pages/start.js';
import { resultsPage, resultsShortcut } from './pages/results.js';
import { claimPage, claimShortcut } from './pages/claim.js';
import { extractPage } from './pages/extract.js';
import { comparePage, reviewPage, summaryPage } from './pages/more.js';
import { batchPage } from './pages/batch.js';

// The four symbol controls (Sound, Motion, Effects, Quiet everything). Static SVG markup from the kit; js/fx/controls.js binds it.
const CONTROLS = `<div class="dw-controls" role="group" aria-label="Sound, motion, effects and quiet">
  <button class="dw-ico" type="button" id="dw-sound" data-snd="none" aria-pressed="true" aria-label="Sound on" title="Sound on. Press to turn off.">
    <svg class="i" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z"/><g class="on-only"><path d="M15.5 9a4 4 0 0 1 0 6"/><path d="M18 6.5a8 8 0 0 1 0 11"/></g><path class="off-only" d="M4 20 20 4"/></svg>
  </button>
  <button class="dw-ico" type="button" id="dw-motion" data-snd="none" aria-pressed="true" aria-label="Motion on" title="Motion on. Press to turn off.">
    <svg class="i" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path class="on-only" d="M2.5 9c2-2.6 3.5-2.6 5.5 0s3.5 2.6 5.5 0 3.5-2.6 5.5 0M2.5 15c2-2.6 3.5-2.6 5.5 0s3.5 2.6 5.5 0 3.5-2.6 5.5 0"/><g class="off-only"><path d="M8.5 6.5v11M15.5 6.5v11"/></g></svg>
  </button>
  <button class="dw-ico" type="button" id="dw-fx" data-snd="none" aria-pressed="true" aria-label="Effects on" title="Effects on (ambient particles, light that follows the pointer, parallax). Press to turn off.">
    <svg class="i" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 3.500l1.800 5.100L18 10.400l-5.200 1.800L11 17.300l-1.800-5.100L4 10.400l5.200-1.800z"/><g class="on-only"><path d="M18.500 15.500v4M16.500 17.500h4"/><path d="M19 3.500v2.500M17.750 4.750h2.500"/></g><path class="off-only" d="M4 20 20 4"/></svg>
  </button>
  <button class="dw-ico" type="button" id="dw-quiet" data-snd="none" aria-pressed="false" aria-label="Quiet everything" title="Quiet everything: sound, motion and effects off. Press again to bring them back.">
    <svg class="i" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.500"/><path d="M8 12h8"/></svg>
  </button>
</div>
`;
const NAV = [['#/', 'Start'], ['#/extract', 'Extraction'], ['#/reports', 'Reports'], ['#/results', 'Results'], ['#/review', 'Review'], ['#/compare', 'Compare'], ['#/summary', 'Summary'], ['#/about', 'About']];
const OPEN = ['/', '/about', '/reports'];
let current = { path: null };

export function parseHash() {
  const raw = location.hash.slice(1) || '/';
  const [path, qs] = raw.split('?');
  return { path: path || '/', q: new URLSearchParams(qs || ''), raw };
}
export const go = (hash) => { location.hash = hash; };

function buildShell() {
  const top = document.getElementById('topbar');
  // On a phone the menu collapses behind one small button (see .menu-btn in app.css); on wider screens it is always shown.
  const menuBtn = h('button', { class: 'btn menu-btn', type: 'button', id: 'menu-btn', 'aria-expanded': 'false', 'aria-controls': 'top-menu', onclick: () => setMenu(!top.classList.contains('open')) }, 'Menu');
  top.replaceChildren(
    h('a', { class: 'brand', href: '#/' }, 'Evidence Navigator'),
    menuBtn,
    h('div', { class: 'top-menu', id: 'top-menu' },
      h('nav', { 'aria-label': 'Main' }, NAV.map(([href, label]) => h('a', { href, 'data-nav': href }, label))),
      roleSwitcher(),
      h('button', { class: 'dw-ico theme-ico', type: 'button', id: 'theme', onclick: toggleTheme }, ''),
      h('button', { class: 'btn', type: 'button', 'aria-label': 'Keyboard shortcuts', onclick: openHelp }, '?', h('span', { class: 'phone-only', 'aria-hidden': 'true' }, ' Keyboard shortcuts'))));
  const fx = document.createElement('div'); fx.innerHTML = CONTROLS; document.getElementById('top-menu').append(fx.firstElementChild);
  setThemeLabel();
  document.body.append(helpDialog());
}
// Same findings, different detail: see ROLES in state.js. The choice is remembered in this browser.
function roleSwitcher() {
  const sel = h('select', { id: 'role-select', 'aria-describedby': 'role-help', title: 'View as' },
    Object.entries(ROLES).map(([k, r]) => h('option', Object.assign({ value: k }, k === getRole() ? { selected: true } : {}), r.label)));
  sel.addEventListener('change', () => {
    const r = setRole(sel.value);
    document.getElementById('role-help').textContent = ROLES[r].sees;
    toast('Showing the ' + ROLES[r].label.toLowerCase() + ' view: ' + ROLES[r].sees + '.');
    // On a phone the menu covers the page: close it so the new view shows, and keep focus on the Menu button.
    if (document.getElementById('topbar').classList.contains('open')) setMenu(false, true);
  });
  return h('div', { class: 'role-switch' }, h('label', { for: 'role-select' }, 'View as'), sel,
    h('span', { id: 'role-help', class: 'sr' }, ROLES[getRole()].sees));
}
function setMenu(open, refocus) {
  const top = document.getElementById('topbar'), b = document.getElementById('menu-btn');
  if (!top || !b) return;
  top.classList.toggle('open', open);
  b.setAttribute('aria-expanded', String(open));
  b.textContent = open ? 'Close menu' : 'Menu';
  if (refocus) b.focus();
}
function setThemeLabel() {
  const light = document.documentElement.dataset.theme === 'light';
  const b = document.getElementById('theme');
  if (!b) return;
  // An icon button like the other controls: a moon offers dark, a sun offers light.
  const label = light ? 'Switch to dark theme' : 'Switch to light theme';
  b.setAttribute('aria-label', label); b.title = label;
  b.innerHTML = light
    ? '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/></svg>'
    : '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6"/></svg>';
}
function toggleTheme() {
  const t = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.theme = t; store('en.theme', t); setThemeLabel();
}
function helpDialog() {
  const d = h('dialog', { id: 'help', 'aria-labelledby': 'help-t' },
    h('h2', { id: 'help-t' }, 'Keyboard shortcuts'),
    h('dl', { class: 'keys' },
      ...[['j / k, arrows', 'Next or previous claim'], ['/', 'Focus search on Results'], ['c', 'Compare'], ['?', 'Open this help'], ['Esc', 'Close dialogs']]
        .flatMap(([k, t]) => [h('dt', {}, h('kbd', {}, k)), h('dd', {}, t)])),
    h('button', { class: 'btn primary', type: 'button', onclick: () => d.close() }, 'Close'));
  return d;
}
function openHelp() { const d = document.getElementById('help'); if (d && !d.open) d.showModal(); }

function banner() {
  const slot = document.getElementById('banner-slot');
  const d = state.data;
  slot.replaceChildren(d && d.is_mock ? h('div', { class: 'banner', role: 'alert' },
    'Synthetic sample data. These numbers are not real results.') : '');
}
// The sticky human-in-the-loop bar: shown on the report views once findings are loaded.
const BAR_ON = ['/results', '/claim', '/review', '/summary', '/compare'];
function verifyBar() {
  const slot = document.getElementById('verify-slot');
  const on = state.data && BAR_ON.includes(current.path);
  slot.hidden = !on;
  slot.replaceChildren(on ? verificationBar() : '');
  const top = document.getElementById('topbar');
  document.documentElement.style.setProperty('--tb-h', (getComputedStyle(top).position === 'sticky' ? top.offsetHeight : 0) + 'px');
}
window.addEventListener('en:decided', verifyBar);
// On resize only the sticky offset changes; rebuilding the bar here would drop keyboard focus.
window.addEventListener('resize', () => {
  const top = document.getElementById('topbar');
  document.documentElement.style.setProperty('--tb-h', (getComputedStyle(top).position === 'sticky' ? top.offsetHeight : 0) + 'px');
});
// Print the folded decision panel too.
window.addEventListener('beforeprint', () => document.querySelectorAll('details.dp-wrap').forEach((d) => { d.open = true; }));
function foot() {
  // A pasted report that is extracted but not yet audited is not the loaded findings: say which is which.
  const src = state.mode === 'live-extract' ? 'Report: ' + (state.reportTitle || 'your pasted text') + ' (extracted, not audited yet)'
    : state.data && state.data.data_release ? 'Data release: ' + state.data.data_release.name : '';
  document.getElementById('foot').textContent = (src ? src + '. ' : '') + 'Checks data readiness only. No clinical claims.';
}

function route() {
  setMenu(false);
  const r = parseHash();
  if (current.path === '/results') state.scroll = window.scrollY;
  const prev = current.path;
  if (!state.data && !state.extract && r.path === '/extract') { /* handled below */ }
  if (!state.data && !(r.path === '/extract' && state.extract) && !OPEN.includes(r.path)) {
    store('en.intended', r.raw);
    state.notice = 'Load findings first. You will be taken to the page you asked for afterwards.';
    location.hash = '#/'; return;
  }
  let view, crumbs = null, m;
  if (r.path === '/') view = startPage();
  else if (r.path === '/extract') ({ view, crumbs } = extractPage());
  else if (r.path === '/results') view = resultsPage();
  else if ((m = r.path.match(/^\/claim\/([^/]+)$/)) && byId(decodeURIComponent(m[1]))) ({ view, crumbs } = claimPage(byId(decodeURIComponent(m[1])), r.q));
  else if (r.path === '/compare') ({ view, crumbs } = comparePage(r.q));
  else if (r.path === '/review') ({ view, crumbs } = reviewPage(r.q));
  else if (r.path === '/summary') view = summaryPage(r.q);
  else if (r.path === '/reports') view = batchPage();
  else if (r.path === '/about') view = aboutPage();
  else view = notFoundPage();

  current = { path: r.path.startsWith('/claim/') ? '/claim' : r.path, id: m && m[1] };
  banner(); foot(); verifyBar();
  document.querySelectorAll('[data-nav]').forEach((a) => {
    const on = a.dataset.nav === '#' + (current.path === '/claim' ? '/results' : current.path);
    on ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current');
  });
  document.getElementById('crumbs-slot').replaceChildren(crumbs || '');
  const main = document.getElementById('main');
  if (!reduceMotion()) view.classList.add('page-enter');
  // Soft choreography: the page's blocks rise in one after another as they come into view.
  // The limitation is never held back, even for a moment.
  [...view.children].forEach((c) => { if (!c.classList.contains('limit')) c.setAttribute('data-reveal', ''); });
  main.replaceChildren(view);
  if (window.DW && DW.motion) DW.motion.reveal(view);
  if (prev && prev !== current.path && window.DW && DW.sound) DW.sound.play('whoosh');
  document.title = (view.dataset.title ? view.dataset.title + ' | ' : '') + 'Evidence Navigator';
  window.scrollTo(0, current.path === '/results' && prev !== '/results' ? state.scroll : 0);
  main.focus({ preventScroll: true });
  if (view.afterMount) view.afterMount();
}
window.addEventListener('hashchange', route);

document.addEventListener('keydown', (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === 'Escape' && document.getElementById('topbar').classList.contains('open')) { setMenu(false, true); return; }
  const tag = (e.target.tagName || '').toLowerCase();
  const typing = ['input', 'textarea', 'select'].includes(tag) || e.target.isContentEditable;
  if (document.querySelector('dialog[open]')) return;
  if (typing) return;
  if (e.key === '?') { e.preventDefault(); openHelp(); return; }
  if (!state.data) return;
  const p = current.path;
  const ids = findings().map((f) => f.id);
  if (p === '/results') resultsShortcut(e);
  else if (p === '/claim') claimShortcut(e, current.id, ids, parseHash().q.get('from'));
  else if (e.key === 'c' && p !== '/compare') go('#/compare');
});

function initFx() {
  if (!window.DW || !DW.controls) return;
  try { DW.motion.init(); DW.controls.init(); DW.sound.autowire(); } catch (e) { /* effects are never essential */ }
}
window.addEventListener('en:decided', () => window.DW && DW.sound && DW.sound.play('success'));

(async function init() {
  setRole(getRole());
  buildShell();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initFx); else initFx();
  if (dataParam()) await loadData();
  if (!location.hash) history.replaceState(null, '', location.pathname + location.search + '#/');
  route();
})();
