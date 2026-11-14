/* DW.sound: a small Web Audio engine with sound palettes. Everything is synthesized (oscillators and filtered noise):
   no audio files, no requests. Safeguards: AudioContext is only created at the first pointer/key/touch (so there is never an
   autoplay warning), master gain plus a compressor set the loudness ceiling, a voice cap and per-cue rate limits stop spam,
   nothing plays while the tab is hidden, and a cue that throws never breaks the page.
   Every palette defines the same cue names (CUES) so any component can call DW.sound.play('click') whatever the theme.
   Loudness rule: single partial gain <= 0.08, typical 0.01-0.05; master 0.3. */
(function (root) {
  'use strict';
  var CUES = ['click', 'hover', 'open', 'close', 'success', 'error', 'whoosh', 'reveal', 'on', 'off'];
  /* Minimum gap between plays of the same cue, in ms. */
  var GAP = { click: 40, hover: 70, reveal: 350, whoosh: 300, open: 120, close: 120, success: 250, error: 250, on: 120, off: 120 };

  /* Derived voices built from the two primitives tone() and hiss(). */
  function derive(S) {
    S.clink = function (at, f, gain) {               /* a struck piece of steel: inharmonic partials and the tick of the hit */
      S.tone({ at: at, f: f, dur: 0.28, gain: gain, attack: 0.001 });
      S.tone({ at: at, f: f * 2.76, dur: 0.14, gain: gain * 0.5, attack: 0.001 });
      S.hiss({ at: at, type: 'highpass', f: 5000, dur: 0.012, gain: gain * 0.6, attack: 0.001 });
    };
    S.thump = function (at, gain, f) {
      S.hiss({ at: at, type: 'lowpass', f: 300, q: 0.7, dur: 0.08, gain: gain, attack: 0.002 });
      S.tone({ at: at, f: f || 100, to: (f || 100) * 0.6, dur: 0.12, gain: gain * 0.6, attack: 0.002 });
    };
    S.beep = function (at, f, dur, gain, type) { S.tone({ at: at, f: f, dur: dur, gain: gain, type: type || 'square', attack: 0.002 }); };
    return S;
  }

  /* Palettes. pad = optional quiet ambient bed {f: [Hz...], type, gain}. */
  var PALETTES = {
    paper: { label: 'Paper', pad: { f: [98, 147], type: 'sine', gain: 0.004 }, cues: {
      click: function (S) { S.hiss({ type: 'bandpass', f: 2400, q: 1.2, dur: 0.03, gain: 0.05 }); S.thump(0, 0.025, 170); },
      hover: function (S) { S.hiss({ type: 'highpass', f: 6000, dur: 0.012, gain: 0.012 }); },
      open: function (S) { S.hiss({ type: 'bandpass', f: 1300, to: 4800, q: 0.5, dur: 0.15, gain: 0.06, attack: 0.025 }); for (var i = 0; i < 5; i++) S.hiss({ at: S.R(0.02, 0.15), type: 'highpass', f: S.R(2600, 7000), dur: 0.01, gain: 0.02 }); },
      close: function (S) { S.hiss({ type: 'bandpass', f: 4000, to: 1300, q: 0.5, dur: 0.12, gain: 0.05, attack: 0.02 }); S.thump(0.1, 0.03, 150); },
      success: function (S) { S.thump(0, 0.07, 120); S.tone({ at: 0.03, f: 440, dur: 0.25, gain: 0.02 }); },
      error: function (S) { S.thump(0, 0.05, 90); S.tone({ f: 150, type: 'triangle', dur: 0.2, gain: 0.03 }); },
      whoosh: function (S) { S.hiss({ type: 'bandpass', f: 900, to: 3500, q: 0.6, dur: 0.3, gain: 0.05, attack: 0.08 }); },
      reveal: function (S) { S.hiss({ type: 'bandpass', f: 2000, to: 3200, q: 0.6, dur: 0.1, gain: 0.02, attack: 0.02 }); },
      on: function (S) { S.tone({ f: 520, dur: 0.08, gain: 0.03 }); S.tone({ at: 0.06, f: 700, dur: 0.1, gain: 0.025 }); },
      off: function (S) { S.tone({ f: 420, dur: 0.1, gain: 0.025 }); }
    } },
    metal: { label: 'Metal and workshop', pad: null, cues: {
      click: function (S) { S.thump(0, 0.05, 150); S.clink(0.005, 2200, 0.02); },
      hover: function (S) { S.clink(0, 3400, 0.01); },
      open: function (S) { S.hiss({ type: 'lowpass', f: 900, to: 300, q: 0.6, dur: 0.3, gain: 0.07, attack: 0.04 }); for (var i = 0; i < 4; i++) S.clink(S.R(0, 0.28), S.R(900, 1500), 0.012); S.thump(0.3, 0.08, 110); },
      close: function (S) { S.hiss({ type: 'lowpass', f: 300, to: 900, q: 0.6, dur: 0.25, gain: 0.07, attack: 0.03 }); S.thump(0.25, 0.07, 90); },
      success: function (S) { S.clink(0, 2400, 0.05); S.clink(0.09, 3200, 0.05); },
      error: function (S) { S.clink(0, 700, 0.05); S.clink(0.02, 760, 0.04); S.thump(0.02, 0.06, 80); },
      whoosh: function (S) { S.tone({ f: 55, to: 98, type: 'sawtooth', dur: 0.6, gain: 0.02, attack: 0.15 }); S.hiss({ type: 'lowpass', f: 180, to: 400, q: 0.7, dur: 0.6, gain: 0.07, attack: 0.15 }); },
      reveal: function (S) { S.clink(0, S.R(2600, 3200), 0.015); },
      on: function (S) { S.clink(0, 2400, 0.05); S.clink(0.09, 3200, 0.05); },
      off: function (S) { S.thump(0, 0.05, 130); }
    } },
    nature: { label: 'Nature and zen', pad: { f: [130.8, 196, 261.6], type: 'sine', gain: 0.005 }, cues: {
      click: function (S) { S.tone({ f: 520, dur: 0.12, gain: 0.045, attack: 0.012 }); },
      hover: function (S) { S.tone({ f: 1250, dur: 0.05, gain: 0.01, attack: 0.01 }); },
      open: function (S) { S.tone({ f: 480, dur: 0.1, gain: 0.03, attack: 0.02 }); S.tone({ at: 0.06, f: 640, dur: 0.12, gain: 0.025, attack: 0.02 }); },
      close: function (S) { S.tone({ f: 420, dur: 0.1, gain: 0.025, attack: 0.02 }); },
      success: function (S) { S.tone({ f: 784, dur: 1.1, gain: 0.025, attack: 0.03 }); S.tone({ at: 0.18, f: 988, dur: 1.1, gain: 0.02, attack: 0.03 }); S.tone({ at: 0.36, f: 1175, dur: 1.3, gain: 0.018, attack: 0.03 }); },
      error: function (S) { S.tone({ f: 294, type: 'triangle', dur: 0.35, gain: 0.05, attack: 0.02 }); },
      whoosh: function (S) { S.tone({ f: 700, to: 180, dur: 0.5, gain: 0.03, attack: 0.1 }); },
      reveal: function (S) { S.tone({ f: 260, to: 520, dur: 0.6, gain: 0.025, attack: 0.15 }); },
      on: function (S) { S.tone({ f: 660, dur: 0.12, gain: 0.03, attack: 0.02 }); S.tone({ at: 0.1, f: 880, dur: 0.16, gain: 0.025, attack: 0.02 }); },
      off: function (S) { S.tone({ f: 880, dur: 0.12, gain: 0.025, attack: 0.02 }); S.tone({ at: 0.1, f: 660, dur: 0.16, gain: 0.02, attack: 0.02 }); }
    } },
    digital: { label: 'Digital and lab', pad: { f: [55, 82.4], type: 'sawtooth', gain: 0.003 }, cues: {
      click: function (S) { S.tone({ f: 880, type: 'square', dur: 0.04, gain: 0.02 }); },
      hover: function (S) { S.tone({ f: 1760, type: 'triangle', dur: 0.02, gain: 0.008 }); },
      open: function (S) { S.tone({ f: 660, type: 'triangle', dur: 0.06, gain: 0.03 }); S.tone({ at: 0.05, f: 990, type: 'triangle', dur: 0.08, gain: 0.03 }); },
      close: function (S) { S.tone({ f: 990, type: 'triangle', dur: 0.06, gain: 0.03 }); S.tone({ at: 0.05, f: 660, type: 'triangle', dur: 0.08, gain: 0.03 }); },
      success: function (S) { [523, 659, 784].forEach(function (f, i) { S.tone({ at: i * 0.07, f: f, type: 'triangle', dur: 0.12, gain: 0.035 }); }); },
      error: function (S) { S.tone({ f: 180, type: 'sawtooth', dur: 0.12, gain: 0.03 }); S.tone({ at: 0.1, f: 150, type: 'sawtooth', dur: 0.16, gain: 0.03 }); },
      whoosh: function (S) { S.tone({ f: 200, to: 1600, type: 'triangle', dur: 0.25, gain: 0.02 }); S.hiss({ type: 'highpass', f: 4000, dur: 0.2, gain: 0.012 }); },
      reveal: function (S) { S.tone({ f: 1200, to: 1800, type: 'sine', dur: 0.08, gain: 0.015 }); },
      on: function (S) { S.tone({ f: 600, type: 'triangle', dur: 0.05, gain: 0.03 }); S.tone({ at: 0.05, f: 900, type: 'triangle', dur: 0.07, gain: 0.03 }); },
      off: function (S) { S.tone({ f: 900, type: 'triangle', dur: 0.05, gain: 0.03 }); S.tone({ at: 0.05, f: 600, type: 'triangle', dur: 0.07, gain: 0.03 }); }
    } },
    retro: { label: 'Retro and one-bit', pad: null, cues: {
      click: function (S) { S.beep(0, 440, 0.03, 0.025); },
      hover: function (S) { S.beep(0, 880, 0.015, 0.008); },
      open: function (S) { [330, 440, 660].forEach(function (f, i) { S.beep(i * 0.05, f, 0.05, 0.025); }); },
      close: function (S) { [660, 440, 330].forEach(function (f, i) { S.beep(i * 0.05, f, 0.05, 0.025); }); },
      success: function (S) { [523, 659, 784, 1047].forEach(function (f, i) { S.beep(i * 0.07, f, 0.07, 0.03); }); },
      error: function (S) { S.beep(0, 110, 0.15, 0.03); S.beep(0.16, 98, 0.2, 0.03); },
      whoosh: function (S) { for (var i = 0; i < 8; i++) S.beep(i * 0.03, 900 - i * 90, 0.03, 0.015); },
      reveal: function (S) { S.beep(0, 1320, 0.03, 0.015); S.beep(0.05, 1760, 0.03, 0.015); },
      on: function (S) { S.beep(0, 523, 0.05, 0.03); S.beep(0.06, 784, 0.07, 0.03); },
      off: function (S) { S.beep(0, 784, 0.05, 0.03); S.beep(0.06, 523, 0.07, 0.03); }
    } },
    soft: { label: 'Soft UI', pad: { f: [174, 261], type: 'sine', gain: 0.004 }, cues: {
      click: function (S) { S.tone({ f: 600, dur: 0.08, gain: 0.03, attack: 0.01 }); },
      hover: function (S) { S.tone({ f: 900, dur: 0.04, gain: 0.008, attack: 0.01 }); },
      open: function (S) { S.tone({ f: 500, to: 700, dur: 0.14, gain: 0.03, attack: 0.02 }); },
      close: function (S) { S.tone({ f: 700, to: 500, dur: 0.14, gain: 0.03, attack: 0.02 }); },
      success: function (S) { S.tone({ f: 660, dur: 0.3, gain: 0.03, attack: 0.02 }); S.tone({ at: 0.09, f: 880, dur: 0.35, gain: 0.025, attack: 0.02 }); },
      error: function (S) { S.tone({ f: 220, type: 'triangle', dur: 0.22, gain: 0.04, attack: 0.02 }); },
      whoosh: function (S) { S.tone({ f: 300, to: 600, dur: 0.4, gain: 0.012, attack: 0.1 }); S.hiss({ type: 'lowpass', f: 600, dur: 0.4, gain: 0.02, attack: 0.12 }); },
      reveal: function (S) { S.tone({ f: 720, dur: 0.12, gain: 0.01, attack: 0.03 }); },
      on: function (S) { S.tone({ f: 600, dur: 0.1, gain: 0.03, attack: 0.01 }); S.tone({ at: 0.07, f: 800, dur: 0.12, gain: 0.025, attack: 0.01 }); },
      off: function (S) { S.tone({ f: 800, dur: 0.1, gain: 0.025, attack: 0.01 }); S.tone({ at: 0.07, f: 600, dur: 0.12, gain: 0.02, attack: 0.01 }); }
    } }
  };

  var api = { CUES: CUES, GAP: GAP, PALETTES: PALETTES, derive: derive };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

  /* ---------------- browser engine ---------------- */
  var DW = root.DW = root.DW || {};
  var MAX_VOICES = 24, PER_SECOND = 14;
  var ctx = null, master = null, noise = null, voices = 0, enabled = true, volume = 1, palette = 'soft', last = {}, recent = [], padNodes = null, padWanted = false, unlocked = false;
  function R(a, b) { return a + Math.random() * (b - a); }

  function ensure() {
    if (ctx) return true;
    var AC = root.AudioContext || root.webkitAudioContext;
    if (!AC) return false;
    try {
      ctx = new AC();
      var comp = ctx.createDynamicsCompressor();
      master = ctx.createGain(); master.gain.value = 0.3 * volume;
      master.connect(comp); comp.connect(ctx.destination);
      noise = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
      var d = noise.getChannelData(0); for (var i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    } catch (e) { ctx = null; return false; }
    return true;
  }
  function ready() { return enabled && ctx && ctx.state === 'running' && !document.hidden; }
  function env(g, t0, peak, attack, dur) { g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(Math.max(peak, 0.0002), t0 + (attack || 0.004)); g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur); }

  var S = derive({
    R: R,
    tone: function (o) {                               /* {f, to, type, gain, dur, at, attack} */
      if (voices >= MAX_VOICES) return;
      var t0 = ctx.currentTime + (o.at || 0), dur = o.dur || 0.1, osc = ctx.createOscillator(), g = ctx.createGain();
      osc.type = o.type || 'sine'; osc.frequency.setValueAtTime(o.f, t0);
      if (o.to) osc.frequency.exponentialRampToValueAtTime(o.to, t0 + dur);
      env(g, t0, o.gain || 0.04, o.attack, dur);
      osc.connect(g); g.connect(master); voices++; osc.onended = function () { voices--; };
      osc.start(t0); osc.stop(t0 + dur + 0.05);
    },
    hiss: function (o) {                               /* filtered noise: {type, f, to, q, gain, dur, at, attack} */
      if (voices >= MAX_VOICES) return;
      var t0 = ctx.currentTime + (o.at || 0), dur = o.dur || 0.1, src = ctx.createBufferSource(), fl = ctx.createBiquadFilter(), g = ctx.createGain();
      src.buffer = noise; fl.type = o.type || 'bandpass'; fl.Q.value = o.q || 1; fl.frequency.setValueAtTime(o.f || 2000, t0);
      if (o.to) fl.frequency.exponentialRampToValueAtTime(o.to, t0 + dur);
      env(g, t0, o.gain || 0.04, o.attack || 0.003, dur);
      src.connect(fl); fl.connect(g); g.connect(master); voices++; src.onended = function () { voices--; };
      src.start(t0, Math.random() * 0.5); src.stop(t0 + dur + 0.05);
    }
  });

  function gap(name) {
    var n = performance.now();
    if (n - (last[name] || 0) < (GAP[name] || 40)) return true;
    last[name] = n;
    recent = recent.filter(function (t) { return n - t < 1000; });
    if (recent.length >= PER_SECOND) return true;
    recent.push(n); return false;
  }
  function play(name) {
    var P = PALETTES[palette], fn = P && P.cues[name];
    if (!fn || !ready() || gap(name)) return;
    try { fn(S); } catch (e) { /* sound is never essential */ }
  }

  /* Ambient pad: a few very quiet sustained tones, faded in after unlock and out on mute or hide. */
  function padStart() {
    var P = PALETTES[palette].pad;
    if (padNodes || !P || !ready() || !padWanted) return;
    var g = ctx.createGain(), t = ctx.currentTime, os = P.f.map(function (f, i) { var o = ctx.createOscillator(); o.type = P.type; o.frequency.value = f; o.detune.value = (i - 1) * 4; o.connect(g); o.start(); return o; });
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(P.gain, t + 3); g.connect(master);
    padNodes = { g: g, os: os };
  }
  function padStop() {
    if (!padNodes) return; var n = padNodes, t = ctx.currentTime; padNodes = null;
    n.g.gain.cancelScheduledValues(t); n.g.gain.setValueAtTime(Math.max(n.g.gain.value, 0.0001), t); n.g.gain.exponentialRampToValueAtTime(0.0001, t + 0.6);
    setTimeout(function () { n.os.forEach(function (o) { try { o.stop(); } catch (e) { /* already stopped */ } }); }, 700);
  }

  function resumeIfNeeded() { if (ctx && ctx.state === 'suspended') return ctx.resume().catch(function () {}); return Promise.resolve(); }
  /* First gesture: create and resume the context. Listeners are removed once it is running. */
  function unlock() {
    if (!enabled || !ensure()) return;
    resumeIfNeeded().then(function () { if (ctx.state === 'running') { unlocked = true; padStart(); ['pointerdown', 'keydown', 'touchstart'].forEach(function (n) { root.removeEventListener(n, unlock, true); }); } });
  }
  ['pointerdown', 'keydown', 'touchstart'].forEach(function (n) { root.addEventListener(n, unlock, { capture: true, passive: true }); });
  document.addEventListener('visibilitychange', function () { if (document.hidden) padStop(); else if (enabled && ctx) resumeIfNeeded().then(padStart); });

  /* Delegated cues: clicks and hovers on interactive elements, so every page has sound without per-element wiring.
     data-snd="name" picks a cue, data-snd="none" silences an element. */
  function autowire() {
    var fine = root.matchMedia && root.matchMedia('(hover: hover) and (pointer: fine)').matches;
    var sel = 'a[href],button,[role="tab"],summary,[data-snd]';
    document.addEventListener('click', function (e) {
      var el = e.target.closest && e.target.closest(sel); if (!el) return;
      var n = el.getAttribute('data-snd'); if (n === 'none') return; play(n || 'click');
    });
    if (fine) document.addEventListener('pointerover', function (e) {
      var el = e.target.closest && e.target.closest(sel + ',.dw-card,[data-snd-hover]');
      if (!el || (e.relatedTarget && el.contains(e.relatedTarget)) || el.getAttribute('data-snd') === 'none') return; play('hover');
    });
  }

  DW.sound = {
    CUES: CUES, palettes: Object.keys(PALETTES),
    get enabled() { return enabled; }, get unlocked() { return unlocked; }, get palette() { return palette; },
    play: play, autowire: autowire, unlock: unlock,
    setPalette: function (n) { if (PALETTES[n]) { padStop(); palette = n; padStart(); } },
    setVolume: function (v) { volume = Math.max(0, Math.min(1, v)); if (master) master.gain.value = 0.3 * volume; },
    setPad: function (on) { padWanted = !!on; if (on) padStart(); else padStop(); },
    setEnabled: function (v) {
      enabled = !!v;
      if (!enabled) padStop(); else if (ctx) resumeIfNeeded().then(padStart);
    }
  };
})(typeof window !== 'undefined' ? window : globalThis);
