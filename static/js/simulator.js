/* simulator.js - the simulated bedside device.
 * Vitals start from a baseline and DRIFT toward the target of the current mode with small
 * noise (never fully random). Every tick the reading is sent through CN.Net.submit(), which
 * posts to Flask or buffers in localStorage when offline / on backup power.
 * Mirrors simulator/sensor_simulator.py.
 */
(function (CN) {
  const KEY = 'carenest_sim_v1';
  const TARGETS = {
    NORMAL:   { heart_rate: 72,  spo2: 98, temperature: 36.8, respiratory_rate: 16, systolic_bp: 118, diastolic_bp: 78 },
    WARNING:  { heart_rate: 105, spo2: 94, temperature: 38.0, respiratory_rate: 22, systolic_bp: 135, diastolic_bp: 85 },
    CRITICAL: { heart_rate: 125, spo2: 89, temperature: 39.0, respiratory_rate: 28, systolic_bp: 150, diastolic_bp: 95 },
  };
  const NOISE = { heart_rate: 1.5, spo2: 0.4, temperature: 0.05, respiratory_rate: 0.6, systolic_bp: 2, diastolic_bp: 1.5 };
  const DP = { heart_rate: 0, spo2: 1, temperature: 1, respiratory_rate: 0, systolic_bp: 0, diastolic_bp: 0 };
  const RATE = 0.3;

  let s = { mode: 'NORMAL', cur: Object.assign({}, TARGETS.NORMAL), interval: 2000, auto: false };
  try { const saved = JSON.parse(localStorage.getItem(KEY) || 'null'); if (saved && TARGETS[saved.mode]) s = Object.assign(s, saved); } catch (e) { /* ignore */ }
  let timer = null, autoLeft = 0, busy = false;
  const gauss = () => { let u = 0, v = 0; while (!u) u = Math.random(); while (!v) v = Math.random(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify({ mode: s.mode, cur: s.cur, interval: s.interval, auto: s.auto })); } catch (e) { /* ignore */ } };

  const Sim = CN.Sim = { last: null, recent: [], TARGETS: TARGETS };
  Sim.mode = () => s.mode;
  Sim.settings = () => ({ interval: s.interval, auto: s.auto });

  function tick() {
    const target = TARGETS[s.mode], r = { patient_id: 'P001' };
    Object.keys(target).forEach(k => {
      s.cur[k] += (target[k] - s.cur[k]) * RATE;
      let v = s.cur[k] + gauss() * NOISE[k];
      if (k === 'spo2') v = Math.min(v, 100);
      r[k] = +v.toFixed(DP[k]);
    });
    r.timestamp = new Date().toISOString();
    r.client_id = CN.Net.uid();
    Sim.last = r; Sim.recent.push(r); if (Sim.recent.length > 40) Sim.recent.shift();
    return r;
  }

  async function loop() {
    if (busy) return; busy = true;
    try {
      if (s.auto && s.mode === 'NORMAL' && Math.random() < 0.01) { s.mode = 'WARNING'; autoLeft = 30; paintButtons(); }
      else if (autoLeft > 0 && --autoLeft === 0 && s.mode === 'WARNING') { s.mode = 'NORMAL'; paintButtons(); }
      const r = tick(); save();
      const res = await CN.Net.submit(r);
      document.dispatchEvent(new CustomEvent('cn:reading', { detail: res }));
    } catch (e) { /* a bad tick must never stop the simulator */ }
    finally { busy = false; }
  }

  Sim.start = function () { if (timer) clearInterval(timer); timer = setInterval(loop, s.interval); loop(); };
  Sim.setInterval = function (ms) { s.interval = ms; save(); Sim.start(); };
  Sim.setAuto = function (on) { s.auto = !!on; save(); };

  Sim.setMode = async function (mode) {
    if (!TARGETS[mode]) return;
    s.mode = mode; autoLeft = 0; save(); paintButtons();
    CN.api('/api/simulation/mode', { method: 'POST', body: { mode: mode } }).catch(() => { /* offline: local only */ });
    loop();   // send a reading immediately so the dashboard reacts at once
  };

  Sim.reset = async function () {
    s.mode = 'NORMAL'; s.cur = Object.assign({}, TARGETS.NORMAL); autoLeft = 0; Sim.recent = []; save();
    CN.Net.clearBuffer();
    try {
      const res = await CN.api('/api/simulation/reset', { method: 'POST' });
      if (res.ok) CN.toast('Simulation reset. Demo data restored.', 'ok'); else CN.toast('Reset failed on the server.', 'err');
    } catch (e) { CN.toast('Server unreachable: local simulator reset only.', 'err'); }
    paintButtons(); loop();
  };

  // Simulated equipment faults (oxygen concentrator, SpO2 probe) - handled by the server.
  Sim.equipment = async function (fault) {
    const f = fault === 'o2' ? 'o2' : fault === 'probe' ? 'probe' : 'clear';
    try {
      const res = await CN.api('/api/equipment/fault', { method: 'POST', body: { fault: f } });
      if (res.ok) { CN.toast(f === 'clear' ? 'Equipment faults cleared.' : 'Equipment fault simulated.', 'ok'); document.dispatchEvent(new Event('cn:reading')); }
      else CN.toast((res.data && res.data.error) || 'Could not change equipment state.', 'err');
    } catch (e) { CN.toast('You are offline. Equipment controls need the server connection.', 'err'); }
  };

  function paintButtons() {
    document.querySelectorAll('[data-demo]').forEach(b => {
      const d = b.dataset.demo;
      if (TARGETS[d]) b.classList.toggle('on', d === s.mode);
      if (d === 'net-off') b.classList.toggle('toggle-on', CN.Net.forcedOffline());
      if (d === 'power-off') b.classList.toggle('toggle-on', CN.Net.mode() === 'power');
    });
    const st = document.getElementById('demoState'); if (st) st.textContent = 'Mode: ' + s.mode;
    const sm = document.getElementById('simMode'); if (sm) sm.textContent = 'Mode: ' + s.mode;
  }

  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-demo]'); if (!b) return;
    const d = b.dataset.demo;
    if (TARGETS[d]) Sim.setMode(d);
    else if (d === 'net-off') CN.Net.setInternet(false);
    else if (d === 'net-on') CN.Net.setInternet(true);
    else if (d === 'power-off') CN.Net.setPower(true);
    else if (d === 'power-on') CN.Net.setPower(false);
    else if (d === 'reset') Sim.reset();
    else if (d.indexOf('eq-') === 0) Sim.equipment(d.slice(3));
    setTimeout(paintButtons, 50);
  });
  const tog = () => document.getElementById('demoToggle');
  document.addEventListener('DOMContentLoaded', () => {
    paintButtons(); CN.Net.onChange(paintButtons); Sim.start();
    const t = tog(); if (t) t.addEventListener('click', () => {
      const p = document.getElementById('demo'); p.classList.toggle('collapsed'); t.textContent = p.classList.contains('collapsed') ? 'Show' : 'Hide';
    });
  });
})(window.CN);
