/* DW.motion: the one requestAnimationFrame loop, the motion gate, easing and tween helpers, scroll-reveal choreography,
   pointer field (parallax, magnet, lantern) and a capped particle field.
   Rules: one loop (the only rAF call is schedule()); the loop sleeps when nothing is active, the tab is hidden, or the
   gate is closed; tickers tied to an element pause while it is off screen; only transform and opacity are animated.
   Pure helpers are exported for node tests (module.exports). Plain script, no modules, so it also works from file://. */
(function (root) {
  'use strict';

  /* ---------------- pure helpers ---------------- */
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function lerp(a, b, t) { return a + (b - a) * t; }
  /* Frame-rate independent ease toward a target (k about 3 slow, 8 snappy). */
  function smooth(cur, target, dt, k) { return target + (cur - target) * Math.exp(-k * dt); }
  /* 0..1..0 once per period. */
  function breath(t, period) { return 0.5 - 0.5 * Math.cos(2 * Math.PI * t / period); }
  var EASE = {
    linear: function (t) { return t; },
    inQuad: function (t) { return t * t; },
    outQuad: function (t) { return 1 - (1 - t) * (1 - t); },
    outCubic: function (t) { return 1 - Math.pow(1 - t, 3); },
    inOutCubic: function (t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; },
    outExpo: function (t) { return t >= 1 ? 1 : 1 - Math.pow(2, -10 * t); },
    outBack: function (t) { var c = 1.70158; return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2); },
    steps5: function (t) { return Math.floor(t * 5) / 5; }
  };
  function ease(name, t) { return (EASE[name] || EASE.outCubic)(clamp(t, 0, 1)); }
  /* The single gate: motion runs only when the control is on, the system has not asked for reduced motion, and the tab is visible. */
  function motionAllowed(s) { return !!(s && s.enabled && !s.reduced && !s.hidden); }
  function rng(seed) { var s = (seed || 1) >>> 0; return function () { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; }; }
  function staggerIndex(i, max) { return Math.min(i, max || 8); }

  /* Particle kinds: vy px/s (negative rises), drift px/s sideways wobble, r radius range, life seconds range, glow 0..1. */
  var KINDS = {
    motes:  { vy: -7,  drift: 10, r: [1.2, 3],   life: [7, 12], color: '--accent',   alpha: 0.5 },
    embers: { vy: -38, drift: 22, r: [1, 2.4],   life: [2, 5],  color: '--accent-2', alpha: 0.7 },
    dust:   { vy: -3,  drift: 6,  r: [0.6, 1.6], life: [9, 16], color: '--muted',    alpha: 0.35 },
    snow:   { vy: 20,  drift: 14, r: [1, 2.6],   life: [8, 14], color: '--ink',      alpha: 0.3 },
    stars:  { vy: 0,   drift: 0,  r: [0.6, 1.8], life: [3, 7],  color: '--ink',      alpha: 0.6 }
  };
  /* A pure, capped particle field. step() never grows the list past cap. */
  function createField(opts) {
    opts = opts || {};
    var kind = KINDS[opts.kind] ? opts.kind : 'motes', K = KINDS[kind], cap = Math.max(1, opts.cap || 48), rnd = rng(opts.seed || 7), list = [], t = 0;
    function make(w, h, spawnAnywhere) {
      var y = spawnAnywhere || K.vy === 0 ? rnd() * h : (K.vy < 0 ? h + 6 : -6);
      return { x: rnd() * w, y: y, vx: 0, vy: K.vy * (0.7 + rnd() * 0.6), r: lerp(K.r[0], K.r[1], rnd()), age: 0, life: lerp(K.life[0], K.life[1], rnd()), ph: rnd() * 6.28 };
    }
    return {
      kind: kind, cap: cap, list: list, K: K,
      fill: function (w, h, n) { n = Math.min(n || cap, cap); while (list.length < n) { var p = make(w, h, true); p.age = rnd() * p.life; list.push(p); } if (list.length > n) list.length = n; },
      /* ptr: {x, y, on} in canvas units. Particles part around the pointer and drift back. */
      step: function (dt, w, h, ptr) {
        t += dt;
        for (var i = list.length - 1; i >= 0; i--) {
          var p = list[i]; p.age += dt;
          p.vx += Math.sin(t * 0.4 + p.ph) * K.drift * dt;
          if (ptr && ptr.on) {
            var dx = p.x - ptr.x, dy = p.y - ptr.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
            if (d < 110) { var f = Math.pow(1 - d / 110, 2) * 300; p.vx += dx / d * f * dt; p.vy += dy / d * f * dt; }
          }
          p.vx *= Math.exp(-1.4 * dt);
          p.x += p.vx * dt; p.y += (p.vy + 0) * dt;
          if (p.age >= p.life || p.y < -10 || p.y > h + 10 || p.x < -10 || p.x > w + 10) { list[i] = make(w, h, false); if (K.vy === 0) list[i].y = rnd() * h; }
        }
        if (list.length > cap) list.length = cap;
      },
      alpha: function (p) { return clamp(Math.sin(Math.PI * p.age / p.life), 0, 1) * K.alpha; }
    };
  }

  var pure = { clamp: clamp, lerp: lerp, smooth: smooth, breath: breath, EASE: EASE, ease: ease, motionAllowed: motionAllowed, rng: rng, staggerIndex: staggerIndex, KINDS: KINDS, createField: createField };
  if (typeof module !== 'undefined' && module.exports) { module.exports = pure; return; }

  /* ---------------- browser engine ---------------- */
  var DW = root.DW = root.DW || {};
  var html = document.documentElement;
  var mq = root.matchMedia ? root.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
  var gate = { enabled: true, fx: true, reduced: mq.matches, hidden: document.hidden };
  var tickers = [], listeners = [], raf = 0, last = 0, now = 0;
  var ptr = { x: 0, y: 0, nx: 0, ny: 0, on: false, sx: 0, sy: 0 };

  function allowed() { return motionAllowed(gate); }
  function fxAllowed() { return allowed() && gate.fx; }
  function applyGate() {
    var on = allowed();
    html.classList.toggle('fx', on);
    html.setAttribute('data-motion', gate.enabled && !gate.reduced ? 'on' : 'off');
    html.setAttribute('data-fx', gate.fx ? 'on' : 'off');
    if (!on) { root.cancelAnimationFrame(raf); raf = 0; revealAll(); }
    listeners.forEach(function (fn) { try { fn(on, fxAllowed()); } catch (e) { /* a listener must not break the gate */ } });
    if (on) wake();
  }

  /* The only requestAnimationFrame call in the page. */
  function schedule() { if (!raf) raf = root.requestAnimationFrame(frame); }
  function frame(ts) {
    raf = 0;
    if (!allowed()) return;
    var dt = Math.min(0.05, (ts - last) / 1000); last = ts; now += dt;
    var busy = false;
    for (var i = tickers.length - 1; i >= 0; i--) {
      var k = tickers[i];
      if (k.fx && !fxAllowed()) continue;
      if (k.el && k.visible === false) continue;
      if (k.active && !k.active()) continue;
      busy = true;
      if (k.fn(dt, now) === false) tickers.splice(i, 1);
    }
    if (busy) { schedule(); }
  }
  function wake() { if (allowed()) { if (!raf) last = performance.now(); schedule(); } }

  /* ticker(opts): {name, fn(dt, now), active(): bool, el, fx}. Returns remove(). Idle tickers cost nothing. */
  var io = root.IntersectionObserver ? new IntersectionObserver(function (es) {
    es.forEach(function (e) { tickers.forEach(function (k) { if (k.el === e.target) { k.visible = e.isIntersecting; if (k.visible) wake(); } }); });
  }) : null;
  function ticker(o) {
    var k = { name: o.name, fn: o.fn, active: o.active, el: o.el || null, fx: !!o.fx, visible: true };
    tickers.push(k);
    if (k.el && io) io.observe(k.el);
    wake();
    return function () { var i = tickers.indexOf(k); if (i >= 0) tickers.splice(i, 1); if (k.el && io) io.unobserve(k.el); };
  }

  /* tween({from,to,dur,ease,update,done}): runs on the shared loop; with motion off it jumps to the end. */
  function tween(o) {
    var from = o.from == null ? 0 : o.from, to = o.to == null ? 1 : o.to, dur = o.dur || 400, el = 0, stop, done;
    var p = new Promise(function (res) { done = res; });
    if (!allowed()) { o.update && o.update(to, 1); done(); return { cancel: function () {}, finished: p }; }
    stop = ticker({ name: 'tween', fn: function (dt) {
      el += dt * 1000; var t = clamp(el / dur, 0, 1);
      o.update && o.update(lerp(from, to, ease(o.ease, t)), t);
      if (t >= 1) { done(); return false; }
    } });
    return { cancel: function () { stop(); done(); }, finished: p };
  }

  /* ---- scroll reveal ---- */
  var revealIO = null;
  function revealAll() { [].forEach.call(document.querySelectorAll('[data-reveal]:not(.is-in)'), function (e) { e.classList.add('is-in'); }); }
  function reveal(scope) {
    var els = [].slice.call((scope || document).querySelectorAll('[data-reveal]'));
    var seen = new Map();
    els.forEach(function (e) {
      var n = seen.get(e.parentNode) || 0; seen.set(e.parentNode, n + 1);
      e.style.setProperty('--i', staggerIndex(n));
    });
    if (!allowed() || !root.IntersectionObserver) { revealAll(); return; }
    revealIO = revealIO || new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        e.target.classList.add('is-in'); revealIO.unobserve(e.target);
        if (DW.sound && e.target.hasAttribute('data-reveal-snd')) DW.sound.play('reveal');
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
    els.forEach(function (e) { if (!e.classList.contains('is-in')) revealIO.observe(e); });
  }

  /* ---- scroll: progress hairline, header state, parallax ---- */
  var scrollDirty = true, parallaxEls = [];
  function onScroll() {
    var h = document.documentElement, max = Math.max(1, h.scrollHeight - h.clientHeight);
    html.style.setProperty('--scroll', (clamp(root.scrollY / max, 0, 1)).toFixed(4));
    html.toggleAttribute('data-scrolled', root.scrollY > 8);
    scrollDirty = true; wake();
  }
  function initScroll() {
    root.addEventListener('scroll', onScroll, { passive: true });
    root.addEventListener('resize', function () { scrollDirty = true; wake(); }, { passive: true });
    parallaxEls = [].slice.call(document.querySelectorAll('[data-depth]')).slice(0, 12);
    ticker({ name: 'parallax', fx: true, active: function () { return scrollDirty; }, fn: function () {
      scrollDirty = false; var vh = root.innerHeight;
      parallaxEls.forEach(function (e) {
        var r = e.getBoundingClientRect(), off = clamp((r.top + r.height / 2 - vh / 2) * -parseFloat(e.getAttribute('data-depth') || '0.1'), -24, 24);
        e.style.transform = 'translate3d(0,' + off.toFixed(1) + 'px,0)';
      });
    } });
    onScroll();
  }

  /* ---- pointer field: --px/--py (-1..1) for depth layers, --mx/--my for the lantern, magnet targets ---- */
  var magnets = [];
  function initPointer() {
    if (!root.matchMedia || !root.matchMedia('(pointer: fine)').matches) return;
    root.addEventListener('pointermove', function (e) { ptr.x = e.clientX; ptr.y = e.clientY; ptr.nx = e.clientX / root.innerWidth * 2 - 1; ptr.ny = e.clientY / root.innerHeight * 2 - 1; ptr.on = true; html.setAttribute('data-pointer', ''); wake(); }, { passive: true });
    document.addEventListener('pointerleave', function () { ptr.on = false; wake(); });
    magnets = [].slice.call(document.querySelectorAll('[data-magnet]')).slice(0, 12);
    ticker({ name: 'pointer', fx: true,
      active: function () { return ptr.on || Math.abs(ptr.sx - ptr.nx) > 0.002 || Math.abs(ptr.sy - ptr.ny) > 0.002; },
      fn: function (dt) {
        ptr.sx = smooth(ptr.sx, ptr.on ? ptr.nx : 0, dt, 5); ptr.sy = smooth(ptr.sy, ptr.on ? ptr.ny : 0, dt, 5);
        html.style.setProperty('--px', ptr.sx.toFixed(3)); html.style.setProperty('--py', ptr.sy.toFixed(3));
        html.style.setProperty('--mx', ptr.x + 'px'); html.style.setProperty('--my', ptr.y + 'px');
        magnets.forEach(function (e) {
          var r = e.getBoundingClientRect(), dx = ptr.x - (r.left + r.width / 2), dy = ptr.y - (r.top + r.height / 2), d = Math.sqrt(dx * dx + dy * dy), pull = ptr.on && d < 90 ? (1 - d / 90) * 0.18 : 0;
          e.style.transform = pull ? 'translate3d(' + (dx * pull).toFixed(1) + 'px,' + (dy * pull).toFixed(1) + 'px,0)' : '';
        });
      } });
  }

  /* ---- ambient particle field on a canvas ---- */
  function field(canvas, o) {
    o = o || {};
    var kind = o.kind || html.getAttribute('data-ambient') || 'motes';
    if (kind === 'none' || !canvas.getContext) return null;
    var ctx = canvas.getContext('2d'), size = { w: 0, h: 0 }, color = '#888';
    var small = root.innerWidth < 700, F = createField({ kind: kind, cap: o.cap || (small ? 28 : 56), seed: o.seed || 7 });
    function paint() { var v = getComputedStyle(html).getPropertyValue(F.K.color).trim(); if (v) color = v; }
    function resize() {
      var dpr = Math.min(root.devicePixelRatio || 1, 1.5);
      size.w = canvas.clientWidth; size.h = canvas.clientHeight; canvas.width = Math.round(size.w * dpr); canvas.height = Math.round(size.h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); F.fill(size.w, size.h);
    }
    resize(); paint();
    root.addEventListener('resize', resize, { passive: true });
    root.addEventListener('themechange', paint);   /* re-read the token when light/dark changes */
    onGate(function (on, fx) { if (!fx) ctx.clearRect(0, 0, size.w, size.h); });
    ticker({ name: 'field', el: canvas, fx: true, fn: function (dt) {
      F.step(dt, size.w, size.h, ptr.on ? { x: ptr.x, y: ptr.y, on: true } : null);
      ctx.clearRect(0, 0, size.w, size.h); ctx.fillStyle = color;
      for (var i = 0; i < F.list.length; i++) { var p = F.list[i]; ctx.globalAlpha = F.alpha(p); ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.2832); ctx.fill(); }
      ctx.globalAlpha = 1;
    } });
    return F;
  }

  function onGate(fn) { listeners.push(fn); }
  function setEnabled(v) { gate.enabled = !!v; applyGate(); }
  function setFx(v) { gate.fx = !!v; applyGate(); }

  function init() {
    mq.addEventListener && mq.addEventListener('change', function () { gate.reduced = mq.matches; applyGate(); });
    document.addEventListener('visibilitychange', function () { gate.hidden = document.hidden; applyGate(); });
    applyGate(); initScroll(); initPointer(); reveal();
    var cv = document.querySelector('.dw-field'); if (cv) field(cv);
  }

  DW.motion = { pure: pure, init: init, allowed: allowed, fxAllowed: fxAllowed, setEnabled: setEnabled, setFx: setFx, onGate: onGate, wake: wake,
    ticker: ticker, tween: tween, reveal: reveal, field: field, ease: ease, get state() { return { enabled: gate.enabled, fx: gate.fx, reduced: gate.reduced }; } };
})(typeof window !== 'undefined' ? window : globalThis);
