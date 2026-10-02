/* offline.js - API helper, connectivity state, localStorage buffering and re-sync.
 *
 * Two simulated failure types, both handled the same way: the bedside device keeps
 * recording, readings are buffered in localStorage, and they are re-sent to Flask
 * (POST /api/sync) when the link / power comes back. Duplicates are ignored by the
 * server through each reading's client_id, so a retried sync is always safe.
 */
window.CN = window.CN || {};
(function (CN) {
  const KEY = 'carenest_net_v1';
  const MAX_BUFFER = 5000;
  const defaults = { manualOffline: false, power: false, buffer: [], synced: 0 };
  let st = Object.assign({}, defaults);
  try { st = Object.assign(st, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (e) { /* ignore corrupt state */ }
  st.syncing = false; st.unreachable = false; st.msg = '';
  const listeners = [];

  function save() {
    try { localStorage.setItem(KEY, JSON.stringify({ manualOffline: st.manualOffline, power: st.power, buffer: st.buffer, synced: st.synced })); }
    catch (e) { /* storage full or blocked: keep working in memory */ }
  }
  const uid = () => (crypto.randomUUID ? crypto.randomUUID() : 'r' + Date.now() + Math.random().toString(16).slice(2));

  // ---- API wrapper: never throws for HTTP errors; throws {network:true} when unreachable ----
  CN.api = async function (path, opts) {
    opts = opts || {};
    if (st.manualOffline && !opts.bypass) { const e = new Error('Internet failure (simulated)'); e.network = true; throw e; }
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), opts.timeout || 6000);
    let res;
    try {
      res = await fetch(path, { method: opts.method || 'GET', credentials: 'same-origin', signal: ctl.signal,
        headers: { 'Content-Type': 'application/json' }, body: opts.body ? JSON.stringify(opts.body) : undefined });
    } catch (err) { const e = new Error('Network unavailable'); e.network = true; throw e; }
    finally { clearTimeout(timer); }
    let data = null; try { data = await res.json(); } catch (e) { /* non-JSON body */ }
    if (res.status === 401) { location.href = '/login'; }
    return { ok: res.ok, status: res.status, data: data };
  };

  CN.toast = function (msg, kind) {
    const box = document.getElementById('toasts'); if (!box) return;
    const t = document.createElement('div'); t.className = 'toast ' + (kind || ''); t.textContent = msg; box.appendChild(t);
    setTimeout(() => t.remove(), 4500);
  };

  const Net = CN.Net = {
    isOffline: () => st.manualOffline || st.power || st.unreachable || !navigator.onLine,
    forcedOffline: () => st.manualOffline,
    mode: () => (st.power ? 'power' : (Net.isOffline() ? 'offline' : 'online')),
    pending: () => st.buffer.length,
    synced: () => st.synced,
    onChange: (fn) => listeners.push(fn),
    uid: uid,
  };

  function notify() { save(); render(); listeners.forEach(fn => { try { fn(); } catch (e) { /* ignore */ } }); }

  // Basic on-device threshold check so a local alarm still works with no server.
  CN.edgeCheck = function (r) {
    if (!r) return [];
    const out = [];
    if (r.spo2 < 92) out.push('SpO₂ low');
    if (r.heart_rate >= 120 || r.heart_rate < 45) out.push('heart rate extreme');
    if (r.temperature >= 38.5) out.push('high temperature');
    if (r.respiratory_rate >= 25) out.push('respiratory rate high');
    return out;
  };

  function render() {
    const $ = (id) => document.getElementById(id);
    const mode = Net.mode();
    document.body.classList.toggle('is-offline', mode === 'offline');
    document.body.classList.toggle('is-power', mode === 'power');
    const chip = $('netChip'); if (!chip) return;
    if (mode === 'power') { chip.className = 'chip warn'; chip.innerHTML = '<i class="dot"></i> ⚡ BACKUP MODE ACTIVE'; }
    else if (mode === 'offline') { chip.className = 'chip crit'; chip.innerHTML = '<i class="dot"></i> OFFLINE MODE'; }
    else if (st.syncing) { chip.className = 'chip info'; chip.innerHTML = '<i class="dot"></i> ONLINE · syncing'; }
    else { chip.className = 'chip ok'; chip.innerHTML = '<i class="dot"></i> ONLINE'; }
    $('netPending').textContent = st.buffer.length;
    $('netSynced').textContent = st.synced;
    $('netMsg').textContent = st.msg || (mode === 'power' ? 'Recording locally on backup power.' : (mode === 'offline' ? 'Recording locally. Readings will sync when the connection returns.' : ''));
    const edge = CN.edgeCheck(CN.Sim && CN.Sim.last);
    $('edgeAlert').textContent = (Net.isOffline() && edge.length) ? '🔔 Local alert on device: ' + edge.join(', ') : '';
  }

  // ---- buffering & sync ----
  Net.submit = async function (reading) {
    reading.client_id = reading.client_id || uid();
    if (Net.isOffline()) { bufferReading(reading); return { buffered: true }; }
    try {
      const res = await CN.api('/api/vitals', { method: 'POST', body: reading });
      if (st.unreachable) { st.unreachable = false; }
      if (st.buffer.length && !st.syncing) Net.trySync();
      return res;
    } catch (e) {
      if (e.network) { st.unreachable = true; bufferReading(reading); return { buffered: true }; }
      throw e;
    }
  };

  function bufferReading(r) {
    if (!st.buffer.length && !Net.isOffline()) st.synced = 0;
    r.source = 'offline-buffer';
    st.buffer.push(r);
    if (st.buffer.length > MAX_BUFFER) st.buffer.splice(0, st.buffer.length - MAX_BUFFER);
    notify();
  }

  Net.trySync = async function () {
    if (st.syncing || Net.isOffline() || !st.buffer.length) return;
    st.syncing = true; st.msg = 'Syncing offline readings...'; notify();
    try {
      while (st.buffer.length) {
        const batch = st.buffer.slice(0, 100);
        const res = await CN.api('/api/sync', { method: 'POST', body: { readings: batch } });
        if (!res.ok) throw new Error('Sync rejected');
        st.buffer.splice(0, batch.length);
        st.synced += batch.length; notify();
      }
      st.msg = 'Sync complete. All buffered readings are on the server.';
      CN.toast('Offline readings synced: ' + st.synced, 'ok');
    } catch (e) {
      if (e.network) st.unreachable = true;
      st.msg = 'Sync paused. Will retry automatically.';
    } finally { st.syncing = false; notify(); document.dispatchEvent(new CustomEvent('cn:reading')); }
  };

  Net.clearBuffer = function () { st.buffer = []; st.synced = 0; st.msg = ''; notify(); };

  async function logEvent(type, detail) {
    try { await CN.api('/api/events', { method: 'POST', bypass: true, body: { event_type: type, detail: detail } }); } catch (e) { /* best effort */ }
  }

  Net.setInternet = async function (online) {
    if (!online) {
      if (st.manualOffline) return;
      await logEvent('internet_failure', 'Simulated internet failure');
      if (!st.buffer.length) st.synced = 0;
      st.manualOffline = true; st.msg = '';
    } else {
      if (!st.manualOffline) return;
      st.manualOffline = false; st.unreachable = false;
      st.msg = 'ONLINE. Syncing offline readings...';
      await logEvent('internet_restored', 'Internet restored, ' + st.buffer.length + ' readings pending');
    }
    notify();
    if (online) Net.trySync();
  };

  Net.setPower = async function (on) {
    if (on) {
      if (st.power) return;
      await logEvent('power_failure', 'Simulated power failure, device on backup mode');
      if (!st.buffer.length) st.synced = 0;
      st.power = true; st.msg = '';
    } else {
      if (!st.power) return;
      st.power = false; st.msg = 'Power restored. Synchronizing buffered readings...';
      await logEvent('power_restored', 'Power restored, ' + st.buffer.length + ' readings buffered');
    }
    notify();
    if (!on) Net.trySync();
  };

  // heartbeat: detect a real server outage coming back, then sync automatically
  setInterval(async () => {
    if (st.manualOffline || st.power) return;
    if (st.unreachable || st.buffer.length) {
      try { await CN.api('/api/ping', { timeout: 3000 }); st.unreachable = false; notify(); Net.trySync(); } catch (e) { st.unreachable = true; notify(); }
    }
  }, 3000);
  window.addEventListener('online', () => { st.unreachable = false; Net.trySync(); notify(); });
  window.addEventListener('offline', notify);
  document.addEventListener('DOMContentLoaded', () => { render(); if (st.buffer.length && !Net.isOffline()) Net.trySync(); });
})(window.CN);
