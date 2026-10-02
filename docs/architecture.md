# CareNest AI - Architecture

```
 Bedside device (browser)              Flask backend                     Browser UI
 ┌──────────────────────┐   POST /api/vitals   ┌───────────────────┐   GET /api/dashboard
 │ simulator.js         │ ───────────────────► │ routes/vitals.py  │ ◄──────────────────  dashboard.js
 │  drift + noise       │                      │ services.py       │
 │ offline.js           │   POST /api/sync     │  validate         │
 │  localStorage buffer │ ───────────────────► │  ai/risk_engine   │──► SQLite (vitals, alerts,
 └──────────────────────┘                      │  alert manager    │     notes, responses, events)
                                               └───────────────────┘
```

## Data flow for one reading
1. `simulator.js` creates a reading (with `client_id`, timestamp) every 2 s.
2. `offline.js` posts it to `/api/vitals`; on failure/offline/power loss it buffers in localStorage.
3. `services.ingest_reading` validates (missing -> carry forward, implausible -> 400, duplicate `client_id` -> ignored).
4. The last 15 readings and recent caregiver notes (60 min) feed `RiskEngine.assess`.
5. The full assessment (level, reasons, trend, early warning) is stored with the reading.
6. On MEDIUM/HIGH an alert is created unless an equal/higher one is open, or the last one was just resolved and the patient has not returned to LOW.
7. Dashboards poll `/api/dashboard`; a banner notifies the caregiver of new alerts; the caregiver acknowledges / responds / resolves.

## Equipment and attendance
- `equipment` table holds one row per simulated device (SpO₂ probe, oxygen concentrator, backup battery). The demo panel injects faults via `POST /api/equipment/fault`; the battery level is derived from the simulated power-failure event.
- `services.evaluate_equipment` runs on every dashboard poll and raises **one** alert per new fault (edge-triggered, `alerts.kind='equipment'`), so a persisting fault does not re-alert after the caregiver resolves it.
- `attendance` table stores check-in / check-out (`POST /api/attendance`, simulated bedside NFC tap). `services.check_escalation` escalates a HIGH alert once (`alerts.escalated_at`) when no verified check-in exists within `Config.ESCALATION_SECONDS`.
- Vital-sign alert logic only considers `kind='vital'` alerts, so an open equipment alert never suppresses a risk alert.

## Risk engine
`final = max(ML, safety rules)`, then adjusted by trend, persistence and caregiver context (LOW/MEDIUM/HIGH only).

## Database (SQLite)
users, patients, vitals (with risk_level, risk_json, client_id), caregiver_notes, alerts, caregiver_responses, system_events.

## Resilience
| Failure | Behaviour |
|---|---|
| Internet / server down | Buffer in localStorage, OFFLINE MODE banner, local threshold alarm, auto-sync on return |
| Power failure (simulated) | BACKUP MODE, local recording, sync after restore |
| Missing sensor value | Carried forward from last reading, flagged as imputed |
| Invalid value | Rejected with a friendly message, simulator continues |
| Duplicate submission | Ignored (idempotent `client_id`) |
| Corrupt/missing model | Retrained automatically on start |
