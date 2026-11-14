/* DW.controls: the global symbol controls (Sound, Motion, Effects, Quiet everything).
   DEFAULTS ON. Motion starts off only when the system asks for reduced motion (and then stays off: the system wins).
   State is kept in localStorage under fresh, versioned keys (<prefix>-sound / -motion / -fx, prefix like "myapp1") and the page
   renders correctly when storage is blocked. Pure decision logic is exported for node tests. */
(function (root) {
  'use strict';
  /* stored: {sound, motion, fx} as 'on' | 'off' | null.  Returns booleans. */
  function resolveDefaults(stored, reduced) {
    stored = stored || {};
    return { sound: stored.sound !== 'off', motion: reduced ? false : stored.motion !== 'off', fx: stored.fx !== 'off' };
  }
  /* Quiet everything: if anything is on, remember the state and turn all off; if all are off, restore (or defaults). */
  function quietStep(cur, prev, reduced) {
    var allOff = !cur.sound && !cur.motion && !cur.fx;
    if (!allOff) return { next: { sound: false, motion: false, fx: false }, prev: { sound: cur.sound, motion: cur.motion, fx: cur.fx } };
    var p = prev && (prev.sound || prev.motion || prev.fx) ? prev : { sound: true, motion: true, fx: true };
    return { next: { sound: p.sound, motion: reduced ? false : p.motion, fx: p.fx }, prev: null };
  }
  var pure = { resolveDefaults: resolveDefaults, quietStep: quietStep };
  if (typeof module !== 'undefined' && module.exports) { module.exports = pure; return; }

  var DW = root.DW = root.DW || {};
  var cfg = root.DW_CONFIG || {}, P = cfg.keyPrefix || 'dw1', reduced = !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var state, prev = null, els = {};
  function load(n) { try { return localStorage.getItem(P + '-' + n); } catch (e) { return null; } }
  function save(n, v) { try { localStorage.setItem(P + '-' + n, v ? 'on' : 'off'); } catch (e) { /* storage blocked: fine */ } }
  function say(msg) { var l = document.getElementById('dw-live'); if (l) l.textContent = msg; }

  function paintBtn(b, on, name, extra) {
    if (!b) return;
    b.setAttribute('aria-pressed', String(on));
    b.setAttribute('aria-label', name + (on ? ' on' : ' off'));
    b.title = name + (on ? ' on. Press to turn off.' : ' off. Press to turn on.') + (extra || '');
  }
  function paint() {
    paintBtn(els.sound, state.sound, 'Sound');
    paintBtn(els.motion, state.motion, 'Motion', reduced ? ' Your system asks for reduced motion, so motion stays off.' : '');
    paintBtn(els.fx, state.fx, 'Effects');
    if (els.quiet) els.quiet.setAttribute('aria-pressed', String(!state.sound && !state.motion && !state.fx));
  }
  function apply(next, persist) {
    state = { sound: next.sound, motion: next.motion, fx: next.fx };
    if (DW.sound) DW.sound.setEnabled(state.sound);
    if (DW.motion) { DW.motion.setEnabled(state.motion); DW.motion.setFx(state.fx); }
    if (persist) { save('sound', state.sound); save('motion', state.motion); save('fx', state.fx); }
    paint();
  }
  function init() {
    ['sound', 'motion', 'fx', 'quiet'].forEach(function (n) { els[n] = document.getElementById('dw-' + n); });
    apply(resolveDefaults({ sound: load('sound'), motion: load('motion'), fx: load('fx') }, reduced), false);
    function flip(k, label) {
      var next = { sound: state.sound, motion: state.motion, fx: state.fx };
      if (k === 'motion' && reduced) { say('Your system asks for reduced motion, so motion stays off.'); return; }
      next[k] = !next[k]; apply(next, true);
      if (DW.sound && k === 'sound' && next.sound) DW.sound.play('on');
      else if (DW.sound && next.sound) DW.sound.play(next[k] ? 'on' : 'off');
      say(label + (next[k] ? ' on.' : ' off.'));
    }
    if (els.sound) els.sound.addEventListener('click', function () { flip('sound', 'Sound'); });
    if (els.motion) els.motion.addEventListener('click', function () { flip('motion', 'Motion'); });
    if (els.fx) els.fx.addEventListener('click', function () { flip('fx', 'Effects'); });
    if (els.quiet) els.quiet.addEventListener('click', function () {
      var r = quietStep(state, prev, reduced); prev = r.prev; apply(r.next, true);
      say(r.next.sound || r.next.motion || r.next.fx ? 'Sound, motion and effects are back.' : 'Everything is quiet: sound, motion and effects are off.');
    });
  }
  DW.controls = { pure: pure, init: init, get state() { return state; } };
})(typeof window !== 'undefined' ? window : globalThis);
