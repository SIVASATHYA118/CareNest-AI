/* charts.js - Chart.js helpers: live traces and the history page. */
(function (CN) {
  const C = CN.Charts = { live: {} };
  const SPECS = {
    hr:   { key: 'heart_rate', label: 'Heart rate', lo: 60, hi: 100, min: 40, max: 150 },
    spo2: { key: 'spo2', label: 'SpO₂', lo: 95, hi: 100, min: 84, max: 100 },
    temp: { key: 'temperature', label: 'Temperature', lo: 36.1, hi: 37.5, min: 35, max: 40.5 },
    rr:   { key: 'respiratory_rate', label: 'Respiratory rate', lo: 12, hi: 20, min: 8, max: 34 },
  };
  C.SPECS = SPECS;

  function make(canvas, spec, dark) {
    const line = dark ? '#5EEAA6' : '#0B7A75', band = dark ? 'rgba(182,212,208,.35)' : 'rgba(74,96,105,.35)';
    const tick = dark ? '#8FB0B6' : '#4A6069', grid = dark ? 'rgba(255,255,255,.07)' : 'rgba(0,0,0,.06)';
    return new Chart(canvas, {
      type: 'line',
      data: { labels: [], datasets: [
        { label: spec.label, data: [], borderColor: line, borderWidth: 2, pointRadius: 0, tension: .3, fill: false },
        { label: 'Normal low', data: [], borderColor: band, borderDash: [4, 4], borderWidth: 1, pointRadius: 0, fill: false },
        { label: 'Normal high', data: [], borderColor: band, borderDash: [4, 4], borderWidth: 1, pointRadius: 0, fill: false },
      ] },
      options: { animation: false, responsive: true, maintainAspectRatio: false, interaction: { intersect: false, mode: 'index' },
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { color: tick, maxTicksLimit: 6, maxRotation: 0 }, grid: { color: grid } },
                  y: { min: spec.min, max: spec.max, ticks: { color: tick }, grid: { color: grid } } } },
    });
  }

  function fill(chart, spec, rows) {
    const t = (r) => new Date(r.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: rows.length > 60 ? undefined : '2-digit' });
    chart.data.labels = rows.map(t);
    chart.data.datasets[0].data = rows.map(r => r[spec.key]);
    chart.data.datasets[1].data = rows.map(() => spec.lo);
    chart.data.datasets[2].data = rows.map(() => spec.hi);
    chart.update('none');
  }

  // Live charts: create whichever canvases exist on this page.
  C.initLive = function () {
    const dark = document.body.dataset.page === 'dashboard';
    [['cHR', 'hr'], ['cSPO2', 'spo2'], ['cTEMP', 'temp'], ['cRR', 'rr']].forEach(([id, k]) => {
      const el = document.getElementById(id); if (el) C.live[k] = make(el, SPECS[k], dark);
    });
  };
  C.updateLive = function (rows) {
    Object.keys(C.live).forEach(k => fill(C.live[k], SPECS[k], rows));
  };

  // History page
  C.initHistory = function () {
    const charts = {};
    [['hHR', 'hr'], ['hSPO2', 'spo2'], ['hTEMP', 'temp'], ['hRR', 'rr']].forEach(([id, k]) => {
      const el = document.getElementById(id); if (el) charts[k] = make(el, SPECS[k], false);
    });
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    let hours = 1;
    async function load() {
      try {
        const [h, t] = await Promise.all([CN.api('/api/vitals/history?hours=' + hours), CN.api('/api/vitals/history?latest=60')]);
        if (!h.ok || !t.ok) throw new Error('bad response');
        Object.keys(charts).forEach(k => fill(charts[k], SPECS[k], h.data.readings));
        document.getElementById('histInfo').textContent = h.data.total + ' readings in the last ' + hours + ' h' + (h.data.total > h.data.readings.length ? ' (charts are down-sampled for speed)' : '') + '. Dashed lines mark the prototype normal range.';
        document.getElementById('histRows').innerHTML = t.data.readings.map(r => {
          const why = (r.risk && r.risk.reasons ? r.risk.reasons : []).join(' • ');
          return '<tr><td>' + new Date(r.timestamp).toLocaleString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', day: 'numeric', month: 'short' }) +
            (r.source === 'offline-buffer' ? ' <span class="tag">synced</span>' : '') + '</td><td>' + Math.round(r.heart_rate) + '</td><td>' + (+r.spo2).toFixed(1) +
            '</td><td>' + (+r.temperature).toFixed(1) + '</td><td>' + Math.round(r.respiratory_rate) + '</td><td>' + Math.round(r.systolic_bp) + '/' + Math.round(r.diastolic_bp) +
            '</td><td><span class="chip ' + r.risk_level + '">' + r.risk_level + '</span></td><td class="expl">' + esc(why) + '</td></tr>';
        }).join('');
      } catch (e) {
        CN.toast('Could not load history. The server may be offline.', 'err');
      }
    }
    document.querySelectorAll('#range button').forEach(b => b.addEventListener('click', () => {
      document.querySelectorAll('#range button').forEach(x => x.classList.remove('on')); b.classList.add('on');
      hours = +b.dataset.h; load();
    }));
    load();
    document.addEventListener('cn:reading', (() => { let n = 0; return () => { if (++n % 8 === 0) load(); }; })());
  };
})(window.CN);
