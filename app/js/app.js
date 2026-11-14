import { h, store, toast, reduceMotion } from './util.js';
import { verificationBar } from './ui.js';
import { state, dataParam, loadData, byId, findings, ROLES, getRole, setRole } from './state.js';
import { startPage, aboutPage, notFoundPage } from './pages/start.js';
import { resultsPage, resultsShortcut } from './pages/results.js';
import { claimPage, claimShortcut } from './pages/claim.js';
import { extractPage } from './pages/extract.js';
import { comparePage, reviewPage, summaryPage } from './pages/more.js';

const NAV = [['#/', 'Start'], ['#/extract', 'Extraction'], ['#/results', 'Results'], ['#/review', 'Review'], ['#/compare', 'Compare'], ['#/summary', 'Summary'], ['#/about', 'About']];
const OPEN = ['/', '/about'];
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
      h('button', { class: 'btn', type: 'button', id: 'theme', onclick: toggleTheme }, ''),
      h('button', { class: 'btn', type: 'button', 'aria-label': 'Keyboard shortcuts', onclick: openHelp }, '?', h('span', { class: 'phone-only', 'aria-hidden': 'true' }, ' Keyboard shortcuts'))));
  setThemeLabel();
  document.body.append(helpDialog());
}
// Same findings, different detail: see ROLES in state.js. The choice is remembered in this browser.
function roleSwitcher() {
  const sel = h('select', { id: 'role-select', 'aria-describedby': 'role-help' },
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
  if (b) { b.textContent = light ? 'Dark theme' : 'Light theme'; }
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
  main.replaceChildren(view);
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

(async function init() {
  setRole(getRole());
  buildShell();
  if (dataParam()) await loadData();
  if (!location.hash) history.replaceState(null, '', location.pathname + location.search + '#/');
  route();
})();
