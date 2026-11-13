// Small DOM helpers. All data is inserted with textContent, never innerHTML.
export function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  add(el, kids);
  return el;
}
export function sv(tag, props, ...kids) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(props || {})) if (v != null) el.setAttribute(k, v);
  add(el, kids);
  return el;
}
function add(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k.nodeType ? k : document.createTextNode(String(k)));
  }
}
export const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
export const pct = (n, d) => (d ? (100 * n / d).toFixed(1) + '%' : 'n/a');
export function fmtNum(n) { return n == null ? 'n/a' : Number(n).toLocaleString('en-US'); }
export function fmtValue(v) {
  if (v == null) return 'no value';
  return Number.isInteger(v) ? fmtNum(v) : (v * 100).toFixed(1) + '%';
}
export function countUp(el, to, ms = 500) {
  el.textContent = fmtNum(to);
  if (reduceMotion() || !Number.isFinite(to) || to < 2) return;
  const t0 = performance.now();
  const tick = (t) => {
    const p = Math.min(1, (t - t0) / ms);
    el.textContent = fmtNum(Math.round(to * (1 - Math.pow(1 - p, 3))));
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
let toastTimer;
export function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 2600);
}
export async function copyText(s) {
  try { await navigator.clipboard.writeText(s); return true; } catch (e) { /* fall through */ }
  const ta = h('textarea', { 'aria-hidden': 'true', style: 'position:fixed;opacity:0' });
  ta.value = s; document.body.append(ta); ta.select();
  let ok = false; try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  ta.remove(); return ok;
}
export function store(key, val) {
  try {
    if (val === undefined) { const r = localStorage.getItem(key); return r == null ? null : JSON.parse(r); }
    localStorage.setItem(key, JSON.stringify(val));
  } catch (e) { /* storage unavailable */ }
  return null;
}
