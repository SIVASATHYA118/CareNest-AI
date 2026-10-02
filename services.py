"""Business logic shared by the routes: ingest a reading -> AI risk -> alert."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from ai import note_context
from ai.risk_engine import RANK, VITAL_KEYS, get_engine
from config import Config
from db import log_event, normalize_ts, utcnow_iso
from simulator.sensor_simulator import TARGETS, generate_history

# Plausible physiological limits - anything outside is treated as a sensor error.
PLAUSIBLE = {"heart_rate": (20, 250), "spo2": (50, 100), "temperature": (30, 43),
             "respiratory_rate": (4, 60), "systolic_bp": (50, 260), "diastolic_bp": (30, 160)}
ALIASES = {"hr": "heart_rate", "SpO2": "spo2", "temp": "temperature", "rr": "respiratory_rate",
           "sbp": "systolic_bp", "dbp": "diastolic_bp"}


class ValidationError(ValueError):
    pass


def clean_reading(data, last=None):
    """Validate one incoming reading. Missing values are carried forward, never crash."""
    if not isinstance(data, dict):
        raise ValidationError("Reading must be a JSON object.")
    data = {ALIASES.get(k, k): v for k, v in data.items()}
    out, imputed = {}, []
    for k in VITAL_KEYS:
        raw = data.get(k)
        if raw in (None, "", "null"):
            fallback = (last or {}).get(k) if last else None
            if fallback is None:
                fallback = TARGETS["NORMAL"][k]
            out[k] = fallback
            imputed.append(k)
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            raise ValidationError("Invalid value for %s." % k)
        lo, hi = PLAUSIBLE[k]
        if val != val or not (lo <= val <= hi):
            raise ValidationError("%s value %s is outside the plausible sensor range." % (k, raw))
        out[k] = val
    if len(imputed) == len(VITAL_KEYS):
        raise ValidationError("Reading contains no sensor values.")
    return out, imputed


def _row_vitals(row):
    return {k: row[k] for k in VITAL_KEYS}


def recent_notes(db, patient_id, ts):
    """Caregiver notes inside the context window that ends at `ts`."""
    try:
        end = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        end = datetime.now(timezone.utc)
    start = (end - timedelta(minutes=Config.CONTEXT_NOTE_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = db.execute("SELECT note,language,severity,tags FROM caregiver_notes "
                      "WHERE patient_id=? AND timestamp>=? AND timestamp<=? ORDER BY id",
                      (patient_id, start, ts)).fetchall()
    notes = []
    for r in rows:
        info = note_context.analyze(r["note"], r["language"])
        notes.append(info)
    return notes


def _maybe_alert(db, patient_id, assessment, ts, vital_id):
    """Create an alert on escalation; avoid duplicates and re-alerting after resolve."""
    level = assessment["level"]
    if level == "LOW":
        return None
    latest = db.execute("SELECT * FROM alerts WHERE patient_id=? AND kind='vital' ORDER BY id DESC LIMIT 1", (patient_id,)).fetchone()
    open_alert = db.execute("SELECT risk FROM alerts WHERE patient_id=? AND kind='vital' AND status!='Resolved' "
                            "ORDER BY id DESC", (patient_id,)).fetchall()
    if any(RANK[a["risk"]] >= RANK[level] for a in open_alert):
        return None
    if latest and latest["status"] == "Resolved" and RANK[latest["risk"]] >= RANK[level]:
        # Suppress until the patient has returned to LOW at least once since resolution.
        recovered = db.execute("SELECT 1 FROM vitals WHERE patient_id=? AND id>? AND risk_level='LOW' LIMIT 1",
                               (patient_id, latest["resolved_after_vital_id"] or 0)).fetchone()
        if not recovered:
            return None
    reason = " ".join(assessment["reasons"][:3])
    if level == "HIGH":
        reason = "Multiple abnormal vital trends detected. " + reason
    cur = db.execute("INSERT INTO alerts(patient_id,risk,reason,created_at,status,vital_id) VALUES(?,?,?,?,?,?)",
                     (patient_id, level, reason, ts, "New", vital_id))
    log_event(db, "alert_created", "%s alert #%d created" % (level, cur.lastrowid), patient_id, ts)
    return cur.lastrowid


def ingest_reading(db, data, patient_id=None, source="live", create_alerts=True, commit=True):
    patient_id = patient_id or data.get("patient_id") or Config.DEFAULT_PATIENT_ID
    if not db.execute("SELECT 1 FROM patients WHERE patient_id=?", (patient_id,)).fetchone():
        raise ValidationError("Unknown patient: %s" % patient_id)
    client_id = data.get("client_id")
    if client_id:
        dup = db.execute("SELECT * FROM vitals WHERE client_id=?", (client_id,)).fetchone()
        if dup:
            return {"duplicate": True, "vital_id": dup["id"], "risk": json.loads(dup["risk_json"] or "null")}
    ts = normalize_ts(data.get("timestamp"))
    last = db.execute("SELECT * FROM vitals WHERE patient_id=? AND timestamp<=? ORDER BY timestamp DESC, id DESC LIMIT 1",
                      (patient_id, ts)).fetchone()
    vitals, imputed = clean_reading(data, _row_vitals(last) if last else None)
    prev = db.execute("SELECT * FROM vitals WHERE patient_id=? AND timestamp<=? ORDER BY timestamp DESC, id DESC LIMIT ?",
                      (patient_id, ts, Config.RECENT_WINDOW)).fetchall()
    recent = [_row_vitals(r) for r in reversed(prev)]
    assessment = get_engine().assess(vitals, recent, recent_notes(db, patient_id, ts))
    source = data.get("source") or source
    cur = db.execute(
        "INSERT INTO vitals(patient_id,heart_rate,spo2,temperature,respiratory_rate,systolic_bp,diastolic_bp,"
        "timestamp,client_id,imputed,source,risk_level,risk_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (patient_id, vitals["heart_rate"], vitals["spo2"], vitals["temperature"], vitals["respiratory_rate"],
         vitals["systolic_bp"], vitals["diastolic_bp"], ts, client_id, ",".join(imputed), source,
         assessment["level"], json.dumps(assessment, ensure_ascii=False)))
    vital_id = cur.lastrowid
    alert_id = _maybe_alert(db, patient_id, assessment, ts, vital_id) if create_alerts else None
    if commit:
        db.commit()
    return {"duplicate": False, "vital_id": vital_id, "risk": assessment, "alert_id": alert_id,
            "imputed": imputed, "timestamp": ts}


def seed_history(conn):
    """Insert 24h of synthetic history so charts are not empty on first launch."""
    for r in generate_history(Config.HISTORY_SEED_HOURS, Config.HISTORY_SEED_STEP_MIN):
        ingest_reading(conn, r, Config.DEFAULT_PATIENT_ID, source="seed", create_alerts=False, commit=False)
    log_event(conn, "system_start", "Synthetic history seeded")
    conn.commit()


def reset_simulation(db, patient_id=None):
    pid = patient_id or Config.DEFAULT_PATIENT_ID
    for table in ("caregiver_responses",):
        db.execute("DELETE FROM caregiver_responses WHERE alert_id IN (SELECT id FROM alerts WHERE patient_id=?)", (pid,))
    for table in ("alerts", "caregiver_notes", "vitals", "system_events", "attendance", "equipment"):
        db.execute("DELETE FROM %s WHERE patient_id=?" % table, (pid,))
    ensure_equipment(db, pid)
    seed_history(db)
    log_event(db, "simulation_reset", "Simulation reset to NORMAL", pid)
    db.commit()


def vital_to_dict(row, with_risk=True):
    d = {k: row[k] for k in ("id", "patient_id", "heart_rate", "spo2", "temperature", "respiratory_rate",
                             "systolic_bp", "diastolic_bp", "timestamp", "source", "risk_level")}
    d["imputed"] = [x for x in (row["imputed"] or "").split(",") if x]
    if with_risk:
        d["risk"] = json.loads(row["risk_json"]) if row["risk_json"] else None
    return d


def alert_to_dict(db, row):
    d = dict(row)
    d["alert_code"] = "A-%04d" % row["id"]
    pat = db.execute("SELECT name FROM patients WHERE patient_id=?", (row["patient_id"],)).fetchone()
    d["patient"] = pat["name"] if pat else row["patient_id"]
    d["responses"] = [dict(r) for r in db.execute(
        "SELECT * FROM caregiver_responses WHERE alert_id=? ORDER BY id", (row["id"],)).fetchall()]
    return d


# ---------------------------------------------------------------------------
# Medical-equipment monitoring and caregiver attendance verification
# ---------------------------------------------------------------------------
EQUIPMENT = {   # device: (label, normal status, normal value, unit)
    "spo2_probe": ("SpO\u2082 finger probe", "Connected", None, None),
    "o2_concentrator": ("Oxygen concentrator", "Normal", 2.0, "L/min"),
    "backup_battery": ("Bedside backup battery", "Mains", 100.0, "%"),
}
BATTERY_DRAIN_PER_SEC = 1.5   # accelerated so the demo shows a low battery within ~50 s


def _parse(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


def ensure_equipment(db, patient_id):
    now = utcnow_iso()
    for dev, (label, status, value, unit) in EQUIPMENT.items():
        db.execute("INSERT OR IGNORE INTO equipment(patient_id,device,label,status,value,unit,detail,alerted,updated_at) "
                   "VALUES(?,?,?,?,?,?,?,0,?)", (patient_id, dev, label, status, value, unit, "", now))


def set_equipment_fault(db, patient_id, fault):
    """Demo control: inject or clear a simulated equipment fault."""
    ensure_equipment(db, patient_id)
    now = utcnow_iso()

    def upd(dev, status, value, detail=""):
        db.execute("UPDATE equipment SET status=?, value=?, detail=?, updated_at=? WHERE patient_id=? AND device=?",
                   (status, value, detail, now, patient_id, dev))
    if fault == "probe":
        upd("spo2_probe", "Disconnected", None, "No signal from the finger probe")
        log_event(db, "equipment_fault", "SpO\u2082 probe disconnected (simulated)", patient_id)
    elif fault == "o2":
        upd("o2_concentrator", "Low flow", 0.8, "Flow below the prescribed 2.0 L/min")
        log_event(db, "equipment_fault", "Oxygen concentrator low flow (simulated)", patient_id)
    elif fault == "clear":
        upd("spo2_probe", "Connected", None)
        upd("o2_concentrator", "Normal", 2.0)
        log_event(db, "equipment_cleared", "Equipment faults cleared (simulated)", patient_id)
    else:
        raise ValidationError("fault must be probe, o2 or clear.")


def _battery_state(db):
    """Battery follows the simulated power failure: mains = 100 %, then drains on backup."""
    ev = db.execute("SELECT event_type, timestamp FROM system_events WHERE event_type IN "
                    "('power_failure','power_restored') ORDER BY id DESC LIMIT 1").fetchone()
    if ev and ev["event_type"] == "power_failure":
        secs = max(0.0, (datetime.now(timezone.utc) - _parse(ev["timestamp"])).total_seconds())
        return "On battery", round(max(10.0, 100.0 - BATTERY_DRAIN_PER_SEC * secs), 0)
    return "Mains", 100.0


def _fault_for(dev, status, value):
    """Return (risk, message) when a device needs attention, else None."""
    if dev == "spo2_probe" and status == "Disconnected":
        return "MEDIUM", "SpO\u2082 finger probe disconnected. SpO\u2082 readings may be unreliable; check the probe on the patient."
    if dev == "o2_concentrator" and status in ("Low flow", "Fault"):
        return "HIGH", "Oxygen concentrator flow is low (%.1f L/min, prescribed 2.0). Check tubing, filter and power." % (value or 0)
    if dev == "backup_battery" and status == "On battery" and value is not None and value < 30:
        return ("HIGH" if value < 15 else "MEDIUM"), "Bedside device battery is at %d%% on backup power. Restore mains power." % value
    return None


def evaluate_equipment(db, patient_id):
    """Refresh derived state, raise one alert per new fault (edge-triggered), return device list."""
    ensure_equipment(db, patient_id)
    status, level = _battery_state(db)
    db.execute("UPDATE equipment SET status=?, value=?, updated_at=? WHERE patient_id=? AND device='backup_battery' "
               "AND (status!=? OR value!=?)", (status, level, utcnow_iso(), patient_id, status, level))
    out = []
    for r in db.execute("SELECT * FROM equipment WHERE patient_id=? ORDER BY rowid", (patient_id,)).fetchall():
        fault = _fault_for(r["device"], r["status"], r["value"])
        if fault and not r["alerted"]:
            cur = db.execute("INSERT INTO alerts(patient_id,risk,reason,created_at,status,kind,device) VALUES(?,?,?,?,?,?,?)",
                             (patient_id, fault[0], fault[1], utcnow_iso(), "New", "equipment", r["device"]))
            log_event(db, "alert_created", "%s equipment alert #%d created (%s)" % (fault[0], cur.lastrowid, r["label"]), patient_id)
            db.execute("UPDATE equipment SET alerted=1 WHERE patient_id=? AND device=?", (patient_id, r["device"]))
        elif not fault and r["alerted"]:
            db.execute("UPDATE equipment SET alerted=0 WHERE patient_id=? AND device=?", (patient_id, r["device"]))
        d = dict(r)
        d["fault"] = bool(fault)
        d["severity"] = fault[0] if fault else None
        out.append(d)
    return out


def attendance_status(db, patient_id):
    last = db.execute("SELECT * FROM attendance WHERE patient_id=? ORDER BY id DESC LIMIT 1", (patient_id,)).fetchone()
    on_site = bool(last and last["action"] == "in")
    act = db.execute(
        "SELECT MAX(t) m FROM (SELECT MAX(timestamp) t FROM attendance WHERE patient_id=? UNION ALL "
        "SELECT MAX(timestamp) FROM caregiver_notes WHERE patient_id=? UNION ALL "
        "SELECT MAX(r.timestamp) FROM caregiver_responses r JOIN alerts a ON a.id=r.alert_id WHERE a.patient_id=?)",
        (patient_id, patient_id, patient_id)).fetchone()["m"]
    hist = db.execute("SELECT caregiver,action,method,timestamp FROM attendance WHERE patient_id=? ORDER BY id DESC LIMIT 5",
                      (patient_id,)).fetchall()
    return {"on_site": on_site, "since": last["timestamp"] if on_site else None,
            "caregiver": last["caregiver"] if last else None, "last_activity": act,
            "history": [dict(h) for h in hist], "escalation_seconds": Config.ESCALATION_SECONDS}


def record_attendance(db, patient_id, caregiver, action, method="Simulated NFC tap at bedside"):
    if action not in ("in", "out"):
        raise ValidationError("action must be 'in' or 'out'.")
    st = attendance_status(db, patient_id)
    if (action == "in") == st["on_site"]:
        return False
    db.execute("INSERT INTO attendance(patient_id,caregiver,action,method,timestamp) VALUES(?,?,?,?,?)",
               (patient_id, caregiver, action, method, utcnow_iso()))
    log_event(db, "caregiver_checkin" if action == "in" else "caregiver_checkout",
              "%s %s (%s)" % (caregiver, "checked in at the bedside" if action == "in" else "checked out", method), patient_id)
    return True


def check_escalation(db, patient_id):
    """HIGH alert still open with no verified caregiver check-in after the timer -> escalate once."""
    now = datetime.now(timezone.utc)
    on_site = attendance_status(db, patient_id)["on_site"]
    rows = db.execute("SELECT * FROM alerts WHERE patient_id=? AND risk='HIGH' AND status!='Resolved' "
                      "AND escalated_at IS NULL", (patient_id,)).fetchall()
    for a in rows:
        if (now - _parse(a["created_at"])).total_seconds() < Config.ESCALATION_SECONDS:
            continue
        seen = db.execute("SELECT 1 FROM attendance WHERE patient_id=? AND action='in' AND timestamp>=?",
                          (patient_id, a["created_at"])).fetchone()
        if on_site or seen:
            continue
        db.execute("UPDATE alerts SET escalated_at=? WHERE id=?", (utcnow_iso(), a["id"]))
        log_event(db, "escalation", "Secondary contact notified (simulated): no verified caregiver check-in for alert A-%04d" % a["id"], patient_id)
