/* dashboard.js - page rendering, polling, alert actions, caregiver notes. */
(function (CN) {
  const page = document.body.dataset.page;
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const clock = (iso) => iso ? new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '';
  const clockS = (iso) => iso ? new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' }) : '';

  // Prototype ranges (mirror of ai/safety_rules.py): [normal low, normal high, severe low, severe high]
  const RNG = { heart_rate: [60, 100, 50, 120], spo2: [95, 101, 92, null], temperature: [36.1, 37.5, 35.5, 38.5],
                respiratory_rate: [12, 20, 9, 25], systolic_bp: [90, 130, 80, 160], diastolic_bp: [60, 90, 50, 100] };
  function sev(k, v) {
    const [lo, hi, slo, shi] = RNG[k];
    if (v < lo) return (slo != null && v < slo) ? 2 : 1;
    if (v > hi) return (shi != null && v >= shi) ? 2 : 1;
    return 0;
  }
  const CARDS = [
    { k: 'heart_rate', label: 'Heart rate', unit: 'bpm', range: '60–100', dp: 0, trend: 'heart_rate', icon: '♥' },
    { k: 'spo2', label: 'SpO₂', unit: '%', range: '95–100', dp: 1, trend: 'spo2', icon: '◍' },
    { k: 'temperature', label: 'Temperature', unit: '°C', range: '36.1–37.5', dp: 1, trend: 'temperature', icon: '🌡' },
    { k: 'respiratory_rate', label: 'Respiratory rate', unit: '/min', range: '12–20', dp: 0, trend: 'respiratory_rate', icon: '〰' },
    { k: 'bp', label: 'Blood pressure', unit: 'mmHg', range: '120/80 typical', dp: 0, icon: '◎' },
  ];

  let D = null, stale = false, inflight = false;

  // ---------------- data ----------------
  async function refresh() {
    if (inflight) return; inflight = true;
    try {
      const res = await CN.api('/api/dashboard');
      if (res.ok) { D = res.data; stale = false; } else { stale = true; }
    } catch (e) { stale = true; }
    finally { inflight = false; }
    render();
  }

  // ---------------- render ----------------
  function render() {
    common();
    if (!D) return;
    const fn = { dashboard: renderDashboard, vitals: renderVitals, patient: renderPatient, alerts: renderAlertsPage, caregiver: renderCaregiver, settings: renderSettings }[page];
    if (fn) fn();
  }

  function shown() { return CN.Net.isOffline() ? CN.Sim.last : (D && D.latest); }

  function common() {
    const pill = $('#riskPill'), upd = $('#updated');
    if (D && D.patient) $('#ptChip').textContent = D.patient.name + ' · ' + D.patient.patient_id;
    const L = D && D.latest;
    if (pill) {
      if (L) { pill.className = 'chip ' + L.risk_level; pill.textContent = 'Risk: ' + L.risk_level + (CN.Net.isOffline() ? ' (last analysed)' : ''); }
    }
    if (upd) {
      const ts = CN.Net.isOffline() && CN.Sim.last ? CN.Sim.last.timestamp : (L && L.timestamp);
      upd.textContent = ts ? 'Last updated ' + clockS(ts) + (stale ? ' · server unreachable' : '') : 'Waiting for data…';
    }
    banner();
  }

  // caregiver notification banner + one-time sound/toast for new alerts
  let seen = null;
  try { seen = JSON.parse(sessionStorage.getItem('cn_seen') || 'null'); } catch (e) { seen = null; }
  function banner() {
    const box = $('#notify'); if (!box || !D) return;
    const alerts = D.alerts || [];
    if (seen === null) { seen = alerts.map(a => a.id); try { sessionStorage.setItem('cn_seen', JSON.stringify(seen)); } catch (e) { /* ignore */ } }
    alerts.forEach(a => {
      if (seen.indexOf(a.id) === -1) {
        seen.push(a.id); try { sessionStorage.setItem('cn_seen', JSON.stringify(seen)); } catch (e) { /* ignore */ }
        CN.toast((a.kind === 'equipment' ? '🔧 Equipment alert' : a.risk === 'HIGH' ? '🚨 High-risk alert' : '⚠ Monitoring alert') + ' ' + a.alert_code + ' created', a.risk === 'HIGH' ? 'err' : '');
        if (a.risk === 'HIGH') beep();
      }
    });
    const fresh = alerts.filter(a => a.status === 'New').sort((x, y) => (y.risk === 'HIGH') - (x.risk === 'HIGH') || y.id - x.id)[0];
    if (!fresh) { box.innerHTML = ''; return; }
    const high = fresh.risk === 'HIGH';
    box.innerHTML = '<div class="notify ' + fresh.risk + '"><b>' + alertTitle(fresh) + ' ' + fresh.alert_code + '</b>' +
      '<span>' + alertLine(fresh) +
      ' Caregiver notified (simulated SMS and app push).</span><button data-banner="' + fresh.id + '">Acknowledge Alert</button>' +
      (page !== 'alerts' ? '<a href="/alerts" style="color:#fff">Open alert</a>' : '') + '</div>';
  }
  function beep() {
    try {
      const ac = new (window.AudioContext || window.webkitAudioContext)(), o = ac.createOscillator(), g = ac.createGain();
      o.frequency.value = 880; g.gain.value = 0.05; o.connect(g); g.connect(ac.destination); o.start();
      setTimeout(() => { o.stop(); ac.close(); }, 350);
    } catch (e) { /* audio blocked: silent */ }
  }

  // ---------------- components ----------------
  function vitalCards() {
    const el = $('#vitalCards'); if (!el) return;
    const r = shown(); if (!r) { el.innerHTML = ''; return; }
    const trend = !CN.Net.isOffline() && D.latest && D.latest.risk ? D.latest.risk.trend || {} : {};
    el.innerHTML = CARDS.map(c => {
      let val, s;
      if (c.k === 'bp') { val = Math.round(r.systolic_bp) + '/' + Math.round(r.diastolic_bp); s = Math.max(sev('systolic_bp', r.systolic_bp), sev('diastolic_bp', r.diastolic_bp)); }
      else { val = (+r[c.k]).toFixed(c.dp); s = sev(c.k, r[c.k]); }
      const t = trend[c.trend]; const arrow = t === 'up' ? ' ↑' : (t === 'down' ? ' ↓' : '');
      return '<div class="vital ' + (s === 2 ? 'crit' : s === 1 ? 'warn' : '') + '"><div class="lab"><span>' + c.label + '</span><span title="Recent trend">' + arrow + '</span></div>' +
        '<div class="val">' + val + '<small>' + c.unit + '</small></div><div class="rng">Normal ' + c.range + '</div></div>';
    }).join('');
  }

  function riskPanel() {
    const el = $('#riskPanel'); if (!el) return;
    const L = D.latest;
    if (!L || !L.risk) { el.className = 'card risk'; el.innerHTML = '<div class="empty">Waiting for the first reading…</div>'; return; }
    const R = L.risk, E = R.early_warning;
    el.className = 'card risk ' + R.level;
    el.innerHTML =
      '<header><div><div class="muted small">Current risk</div><div class="level">' + R.level + ' RISK</div></div><span class="chip">' + (CN.Net.isOffline() ? 'Last analysed ' + clockS(L.timestamp) : 'Analysed ' + clockS(L.timestamp)) + '</span></header>' +
      '<h3>Why?</h3><ul>' + R.reasons.map(x => '<li>' + esc(x) + '</li>').join('') + '</ul>' +
      '<p style="margin:8px 0 0"><b>' + esc(R.summary) + '</b></p>' +
      '<div class="srcs"><span class="chip">ML model: ' + R.ml_level + '</span><span class="chip">Safety rules: ' + R.rule_level + '</span><span class="chip">Trend score: ' + R.trend_score + '</span>' +
      '<span class="chip">Caregiver context: ' + (R.context.severity === 'none' ? 'none' : esc(R.context.labels.join(', '))) + '</span><span class="chip">Escalation level: ' + R.escalation_level + '</span></div>' +
      '<div class="early ' + (E.active ? 'active' : '') + '"><b>Early deterioration indicator</b>' +
      '<div class="bar" title="Prototype deterioration index"><i style="width:' + E.index + '%"></i></div>' +
      '<div><b>' + esc(E.message) + '</b>' + (E.trend_signals.length ? ' Trend: ' + esc(E.trend_signals.join(', ')) + '.' : '') + '</div>' +
      '<div>Suggested action: ' + esc(E.suggested_action) + '</div><div class="small muted">' + esc(E.watch_window) + '</div>' +
      '<div class="small muted" style="margin-top:4px"><i>' + esc(E.label) + '</i></div></div>' +
      '<p class="small muted" style="margin:10px 0 0">' + esc(R.disclaimer) + ' Safety thresholds are prototype logic.</p>';
  }

  function patientCard() {
    const el = $('#patientCard'); if (!el) return;
    const p = D.patient, L = D.latest, off = CN.Net.isOffline(), mode = CN.Net.mode();
    const conn = mode === 'power' ? '<span class="chip warn">⚡ Backup mode</span>' : off ? '<span class="chip crit">Offline</span>' : '<span class="chip ok">Online</span>';
    el.innerHTML = '<header><h2>Patient</h2>' + conn + '</header><dl class="kv">' +
      '<dt>Patient</dt><dd>' + esc(p.name) + '</dd><dt>Patient ID</dt><dd>' + esc(p.patient_id) + '</dd><dt>Age</dt><dd>' + p.age + '</dd><dt>Gender</dt><dd>' + esc(p.gender) + '</dd>' +
      '<dt>Status</dt><dd>' + esc(p.status) + '</dd><dt>Risk</dt><dd>' + (L ? '<span class="chip ' + L.risk_level + '">' + L.risk_level + '</span>' : '–') + '</dd>' +
      '<dt>Connection</dt><dd>' + (off ? 'Offline (buffering ' + CN.Net.pending() + ')' : 'Online') + '</dd>' +
      '<dt>Last updated</dt><dd>' + (L ? clockS(L.timestamp) : '–') + '</dd></dl>';
  }

  function pipeline() {
    const el = $('#pipeline'); if (!el) return;
    const L = D.latest, off = CN.Net.isOffline(), mode = CN.Net.mode();
    const age = L ? (Date.now() - new Date(L.timestamp)) / 1000 : null;
    const open = (D.alerts || []).filter(a => a.status !== 'Resolved');
    const top = open.sort((a, b) => b.id - a.id)[0], lastA = (D.alerts || [])[0];
    const s = [];
    s.push(['Sensor', off ? 'Recording locally' : (age !== null && age < 20 ? 'Streaming' : 'Idle'), off ? 'warn' : 'ok']);
    s.push(['Platform', mode === 'power' ? 'Backup mode' : off ? 'Offline · ' + CN.Net.pending() + ' buffered' : 'Online', off ? 'warn' : 'ok']);
    s.push(['AI risk', L ? L.risk_level : '–', L ? (L.risk_level === 'HIGH' ? 'crit' : L.risk_level === 'MEDIUM' ? 'warn' : 'ok') : '']);
    s.push(['Alert', open.length ? open.length + ' open' : 'None', open.some(a => a.risk === 'HIGH') ? 'crit' : open.length ? 'warn' : 'ok']);
    s.push(['Caregiver', top ? (top.status === 'New' ? 'Awaiting response' : top.status) : (lastA && lastA.status === 'Resolved' ? 'Resolved' : 'Standing by'), top && top.status === 'New' ? 'crit' : top ? 'warn' : 'ok']);
    el.innerHTML = s.map(x => '<div class="step ' + x[2] + '"><small>' + x[0] + '</small><strong>' + esc(x[1]) + '</strong></div>').join('');
  }

  function equipmentCard() {
    const el = $('#equipCard'); if (!el) return;
    const eq = D.equipment || [];
    const rows = eq.map(d => {
      const cls = d.fault ? (d.severity === 'HIGH' ? 'crit' : 'warn') : 'ok';
      const val = d.value != null ? ' · ' + (d.unit === '%' ? Math.round(d.value) : (+d.value).toFixed(1)) + ' ' + esc(d.unit) : '';
      return '<div style="display:flex;justify-content:space-between;gap:8px;padding:6px 0;border-bottom:1px solid var(--line)"><span>' + esc(d.label) +
        '</span><span class="chip ' + cls + '">' + esc(d.status) + val + '</span></div>';
    }).join('');
    el.innerHTML = '<header><h2>Medical equipment</h2><span class="chip ' + (eq.some(d => d.fault) ? 'warn' : 'ok') + '">' + (eq.some(d => d.fault) ? 'Attention needed' : 'All normal') + '</span></header>' +
      (rows || '<div class="empty">No equipment registered.</div>') +
      '<p class="small muted" style="margin:8px 0 0">Simulated devices. A fault raises an equipment alert that follows the same acknowledge / respond / resolve workflow.</p>';
  }

  function attendanceCard() {
    const el = $('#attendCard'); if (!el) return;
    const A = D.attendance || {}, esc_ = (D.alerts || []).filter(a => a.escalated_at && a.status !== 'Resolved');
    const chip = A.on_site ? '<span class="chip ok">On site</span>' : '<span class="chip warn">Not checked in</span>';
    el.innerHTML = '<header><h2>Caregiver attendance</h2>' + chip + '</header>' +
      '<dl class="kv"><dt>Caregiver</dt><dd>' + esc(A.caregiver || '–') + '</dd><dt>On site since</dt><dd>' + (A.since ? clockS(A.since) : '–') + '</dd>' +
      '<dt>Last activity</dt><dd>' + (A.last_activity ? clockS(A.last_activity) : '–') + '</dd></dl>' +
      '<div class="actions" style="margin-top:10px">' + (A.on_site ? '<button class="btn ghost" data-attend="out">Check out</button>' : '<button class="btn" data-attend="in">Check in (simulated NFC tap)</button>') + '</div>' +
      (esc_.length ? '<p class="small" style="margin:8px 0 0;color:var(--crit,#c0392b)"><b>⏫ ' + esc_.map(a => a.alert_code).join(', ') + ' escalated: no verified check-in.</b></p>' : '') +
      '<p class="small muted" style="margin:8px 0 0">A HIGH alert with no check-in within ' + (A.escalation_seconds || 45) + ' s (demo timer) is escalated to a secondary contact.</p>';
  }

  function liveCharts() {
    const rows = CN.Net.isOffline() ? CN.Sim.recent : D.series;
    if (rows && rows.length) CN.Charts.updateLive(rows);
    const tag = $('#liveTag'); if (tag) tag.textContent = CN.Net.isOffline() ? '● LOCAL (offline)' : '● LIVE';
  }

  const isEq = (a) => a.kind === 'equipment';
  const alertTitle = (a) => isEq(a) ? '🔧 EQUIPMENT ALERT' : (a.risk === 'HIGH' ? '🚨 HIGH-RISK ALERT' : '⚠ Monitoring Alert');
  const alertLine = (a) => isEq(a) ? 'Equipment fault detected. Check the device at the bedside.' : (a.risk === 'HIGH' ? 'Immediate caregiver attention required.' : 'Patient condition requires increased observation.');

  function alertHTML(a) {
    const high = a.risk === 'HIGH';
    const st = a.status;
    let tl = '<div>Created ' + clock(a.created_at) + '</div>';
    if (a.acknowledged_at) tl += '<div>Caregiver acknowledged alert at ' + clock(a.acknowledged_at) + '.' + (a.acknowledged_by ? ' (' + esc(a.acknowledged_by) + ')' : '') + '</div>';
    if (a.responding_at) tl += '<div>Marked as responding at ' + clock(a.responding_at) + '.</div>';
    if (a.escalated_at) tl += '<div><b>⏫ Escalated at ' + clock(a.escalated_at) + '</b> — no verified caregiver check-in; secondary contact notified (simulated).</div>';
    if (a.resolved_at) tl += '<div>Alert resolved at ' + clock(a.resolved_at) + '.</div>';
    const notes = a.responses.filter(r => r.response_note).map(r => '<div class="resp"><b>Response note</b> · ' + esc(r.caregiver) + ' · ' + clock(r.timestamp) + '<br>' + esc(r.response_note) + '</div>').join('');
    let btns = '';
    if (st === 'New') btns += '<button class="btn" data-act="acknowledge">Acknowledge Alert</button>';
    if (st === 'New' || st === 'Acknowledged') btns += '<button class="btn warn" data-act="responding">Mark as Responding</button>';
    if (st !== 'Resolved') btns += '<button class="btn danger" data-act="resolve">Resolve Alert</button><button class="btn ghost" data-act="note">Save response note</button>';
    return '<article class="alert ' + a.risk + ' st-' + st + '" data-id="' + a.id + '"><header><b>' + a.alert_code + '</b><span class="chip ' + a.risk + '">' + a.risk + '</span><span class="chip ' + (st === 'New' ? 'crit' : st === 'Resolved' ? 'ok' : 'warn') + '">' + st + '</span><span class="muted small">' + esc(a.patient) + '</span></header>' +
      '<h4>' + alertTitle(a) + '</h4>' +
      '<div><b>' + alertLine(a) + '</b></div>' +
      '<div class="small" style="margin-top:4px"><b>Reason:</b> ' + esc(a.reason) + '</div><div class="tl">' + tl + '</div>' + notes +
      (st !== 'Resolved' ? '<textarea placeholder="Response note, e.g. Checked patient and contacted healthcare provider." aria-label="Response note"></textarea>' : '') +
      '<div class="actions">' + btns + '</div></article>';
  }
  function alertList(el, alerts) {
    const sig = JSON.stringify(alerts.map(a => [a.id, a.status, a.responses.length, a.escalated_at]));
    if (el.dataset.sig === sig) return;               // do not wipe a note the caregiver is typing
    el.dataset.sig = sig;
    el.innerHTML = alerts.length ? alerts.map(alertHTML).join('') : '<div class="empty">No alerts. The patient is being monitored.</div>';
  }

  function notesHTML(notes) {
    if (!notes.length) return '<div class="empty">No caregiver notes yet.</div>';
    return notes.map(n => '<div class="note"><q lang="' + n.language + '">' + esc(n.note) + '</q>' +
      '<div class="small muted"><span class="tag">' + (n.language === 'ta' ? 'தமிழ்' : 'English') + '</span>' +
      (n.tags ? n.tags.split(',').map(t => '<span class="tag">' + esc(t) + '</span>').join('') : '') + esc(n.author || '') + ' · ' + clock(n.timestamp) + '</div>' +
      (n.translation ? '<div class="small">' + (n.language === 'ta' ? 'English: ' : 'தமிழ்: ') + esc(n.translation) + '</div>' : '') + '</div>').join('');
  }
  function eventsHTML(events) {
    if (!events.length) return '<div class="muted">No events yet.</div>';
    return events.map(e => '<div style="padding:3px 0;border-bottom:1px solid var(--line)"><span class="muted">' + clockS(e.timestamp) + '</span> · ' + esc((e.event_type || '').replace(/_/g, ' ')) + (e.detail ? ' — ' + esc(e.detail) : '') + '</div>').join('');
  }
  function rangeTable() {
    const tb = $('#rangeTable tbody'); if (!tb || tb.children.length) return;
    tb.innerHTML = [['Heart rate', '60–100 bpm'], ['SpO₂', '95–100 %'], ['Temperature', '36.1–37.5 °C'], ['Respiratory rate', '12–20 breaths/min'], ['Systolic BP', '90–130 mmHg'], ['Diastolic BP', '60–90 mmHg']]
      .map(r => '<tr><td>' + r[0] + '</td><td>' + r[1] + '</td></tr>').join('');
  }

  // ---------------- pages ----------------
  function renderDashboard() {
    pipeline(); riskPanel(); patientCard(); vitalCards(); equipmentCard(); attendanceCard(); liveCharts();
    alertList($('#alertsOpen'), D.alerts.filter(a => a.status !== 'Resolved'));
    $('#notesRecent').innerHTML = notesHTML(D.notes);
    $('#eventsList').innerHTML = eventsHTML(D.events);
  }
  function renderVitals() { vitalCards(); liveCharts(); riskPanel(); }
  function renderPatient() { patientCard(); riskPanel(); rangeTable(); }

  let alertFilter = 'open';
  function renderAlertsPage() {
    alertList($('#alertsAll'), alertFilter === 'open' ? D.alerts.filter(a => a.status !== 'Resolved') : D.alerts);
  }

  let lastLoad = { notes: 0, settings: 0 };
  async function renderCaregiver() {
    if (Date.now() - lastLoad.notes < 4000) return; lastLoad.notes = Date.now();
    try {
      const res = await CN.api('/api/caregiver-notes');
      if (res.ok) { $('#notesAll').innerHTML = notesHTML(res.data.notes); if (!presets.length) fillPresets(res.data.presets); }
    } catch (e) { $('#notesAll').innerHTML = '<div class="empty">Notes unavailable while offline.</div>'; }
  }
  let presets = [];
  function fillPresets(list) {
    presets = list; const sel = $('#preset'); if (!sel) return;
    sel.innerHTML = '<option value="">Choose a phrase…</option>' + list.map((p, i) => '<option value="' + i + '">' + esc(p.en) + '</option>').join('');
  }

  async function renderSettings() {
    if (Date.now() - lastLoad.settings < 4000) return; lastLoad.settings = Date.now();
    rangeTable();
    try {
      const [info, ev] = await Promise.all([CN.api('/api/settings/info'), CN.api('/api/events')]);
      if (info.ok) {
        const m = info.data.model;
        $('#modelInfo').innerHTML = '<dl class="kv"><dt>Model</dt><dd>' + m.type + '</dd><dt>Training data</dt><dd>' + m.training_samples + ' synthetic observations</dd>' +
          '<dt>Synthetic hold-out accuracy</dt><dd>' + (m.synthetic_accuracy * 100).toFixed(1) + '%</dd><dt>Features</dt><dd>' + m.features.join(', ') + '</dd></dl>' +
          '<p class="muted">Accuracy is measured on synthetic data only and says nothing about real-world clinical performance. The ML output is combined with safety rules, trend and caregiver context.</p>';
      }
      if (ev.ok) $('#eventsList').innerHTML = eventsHTML(ev.data.events);
    } catch (e) { /* offline: keep last content */ }
  }

  // ---------------- interactions ----------------
  document.addEventListener('click', async (e) => {
    const at = e.target.closest('[data-attend]');
    if (at) {
      at.disabled = true;
      try {
        const r = await CN.api('/api/attendance', { method: 'POST', body: { action: at.dataset.attend } });
        if (r.ok) { CN.toast(at.dataset.attend === 'in' ? 'Checked in at the bedside.' : 'Checked out.', 'ok'); resetSigs(); refresh(); }
        else CN.toast((r.data && r.data.error) || 'Check-in failed.', 'err');
      } catch (err) { CN.toast('You are offline. Check-in needs the server connection.', 'err'); }
      at.disabled = false; return;
    }
    const bn = e.target.closest('[data-banner]');
    if (bn) { await doAlert(bn.dataset.banner, 'acknowledge', ''); return; }
    const b = e.target.closest('[data-act]'); if (!b) return;
    const art = b.closest('.alert'), ta = art.querySelector('textarea'), note = ta ? ta.value.trim() : '';
    if (b.dataset.act === 'note') {
      if (!note) { CN.toast('Type a response note first.', 'err'); return; }
      b.disabled = true;
      try {
        const r = await CN.api('/api/caregiver-response', { method: 'POST', body: { alert_id: +art.dataset.id, response_note: note } });
        if (r.ok) { CN.toast('Response note saved.', 'ok'); resetSigs(); refresh(); } else CN.toast((r.data && r.data.error) || 'Could not save the note.', 'err');
      } catch (err) { CN.toast('You are offline. Response notes need the server connection.', 'err'); }
      finally { b.disabled = false; }
      return;
    }
    b.disabled = true;
    await doAlert(art.dataset.id, b.dataset.act, note);
    b.disabled = false;
  });
  function resetSigs() { document.querySelectorAll('[data-sig]').forEach(el => { el.dataset.sig = ''; }); }
  async function doAlert(id, act, note) {
    try {
      const r = await CN.api('/api/alerts/' + id + '/' + act, { method: 'POST', body: { response_note: note } });
      if (r.ok) { CN.toast({ acknowledge: 'Alert acknowledged.', responding: 'Marked as responding.', resolve: 'Alert resolved.' }[act], 'ok'); resetSigs(); refresh(); }
      else CN.toast((r.data && r.data.error) || 'Action failed.', 'err');
    } catch (err) { CN.toast('You are offline. Alert actions need the server connection; try again when it is restored.', 'err'); }
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (CN.Charts && ['dashboard', 'vitals'].indexOf(page) > -1) CN.Charts.initLive();
    if (page === 'history') CN.Charts.initHistory();
    if (page === 'alerts') document.querySelectorAll('#alertFilter button').forEach(b => b.addEventListener('click', () => {
      document.querySelectorAll('#alertFilter button').forEach(x => x.classList.remove('on')); b.classList.add('on');
      alertFilter = b.dataset.f; resetSigs(); renderAlertsPage();
    }));
    if (page === 'caregiver') {
      const text = $('#noteText'), lang = $('#noteLang'), sel = $('#preset');
      sel.addEventListener('change', () => { if (sel.value !== '') text.value = presets[+sel.value][lang.value]; });
      lang.addEventListener('change', () => { if (sel.value !== '') text.value = presets[+sel.value][lang.value]; });
      text.addEventListener('input', () => { if (/[\u0B80-\u0BFF]/.test(text.value)) lang.value = 'ta'; });
      $('#saveNote').addEventListener('click', async () => {
        const note = text.value.trim();
        if (!note) { CN.toast('Please type a note first.', 'err'); return; }
        try {
          const r = await CN.api('/api/caregiver-note', { method: 'POST', body: { note: note, language: lang.value } });
          if (r.ok) {
            const sevr = r.data.analysis.severity;
            CN.toast('Note saved' + (sevr !== 'none' ? ' · used as risk context (' + r.data.analysis.labels.join(', ') + ')' : ''), 'ok');
            text.value = ''; sel.value = ''; lastLoad.notes = 0; refresh();
          } else CN.toast((r.data && r.data.error) || 'Could not save the note.', 'err');
        } catch (err) { CN.toast('You are offline. Notes need the server connection.', 'err'); }
      });
    }
    if (page === 'settings') {
      const sp = $('#speed'), au = $('#auto'), s = CN.Sim.settings();
      sp.value = String(s.interval); au.checked = s.auto;
      sp.addEventListener('change', () => CN.Sim.setInterval(+sp.value));
      au.addEventListener('change', () => CN.Sim.setAuto(au.checked));
    }
    refresh();
    setInterval(refresh, 3000);
    let t = null;
    document.addEventListener('cn:reading', () => { clearTimeout(t); t = setTimeout(refresh, 250); });
    CN.Net.onChange(() => { if (D) render(); });
  });
})(window.CN);
