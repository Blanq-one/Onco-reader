import { h, store, toast, reduceMotion } from './util.js';
import { state, dataParam, loadData, byId, findings } from './state.js';
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
  top.replaceChildren(
    h('a', { class: 'brand', href: '#/' }, 'Evidence Navigator'),
    h('nav', { 'aria-label': 'Main' }, NAV.map(([href, label]) => h('a', { href, 'data-nav': href }, label))),
    h('button', { class: 'btn', type: 'button', id: 'theme', onclick: toggleTheme }, ''),
    h('button', { class: 'btn', type: 'button', 'aria-label': 'Keyboard shortcuts', onclick: openHelp }, '?'));
  setThemeLabel();
  document.body.append(helpDialog());
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
    'SAMPLE DATA. ' + (d.mock_warning || 'These numbers are invented and are not TCGA-BRCA results.')) : '');
}
function foot() {
  document.getElementById('foot').textContent = state.data
    ? 'Source: ' + state.source + '. Checks data readiness only. No clinical claims.'
    : 'Checks data readiness only. No clinical claims.';
}

function route() {
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
  else if ((m = r.path.match(/^\/claim\/([^/]+)$/)) && byId(decodeURIComponent(m[1]))) ({ view, crumbs } = claimPage(byId(decodeURIComponent(m[1]))));
  else if (r.path === '/compare') ({ view, crumbs } = comparePage(r.q));
  else if (r.path === '/review') ({ view, crumbs } = reviewPage(r.q));
  else if (r.path === '/summary') view = summaryPage();
  else if (r.path === '/about') view = aboutPage();
  else view = notFoundPage();

  current = { path: r.path.startsWith('/claim/') ? '/claim' : r.path, id: m && m[1] };
  banner(); foot();
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
  const tag = (e.target.tagName || '').toLowerCase();
  const typing = ['input', 'textarea', 'select'].includes(tag) || e.target.isContentEditable;
  if (document.querySelector('dialog[open]')) return;
  if (typing) return;
  if (e.key === '?') { e.preventDefault(); openHelp(); return; }
  if (!state.data) return;
  const p = current.path;
  const ids = findings().map((f) => f.id);
  if (p === '/results') resultsShortcut(e);
  else if (p === '/claim') claimShortcut(e, current.id, ids);
  else if (e.key === 'c' && p !== '/compare') go('#/compare');
});

(async function init() {
  buildShell();
  if (dataParam()) await loadData();
  if (!location.hash) history.replaceState(null, '', location.pathname + location.search + '#/');
  route();
})();
