"""Patient info, dashboard aggregate, simulation control, events, settings info."""
import json

from flask import Blueprint, jsonify, request

import services
from ai import safety_rules
from ai.risk_engine import get_engine
from config import Config
from db import get_db, log_event, utcnow_iso
from routes.auth import login_required
from simulator.sensor_simulator import TARGETS

bp = Blueprint("system", __name__, url_prefix="/api")


@bp.route("/ping")
def ping():
    return jsonify(ok=True, time=utcnow_iso())


@bp.route("/patient/<patient_id>")
@login_required
def patient(patient_id):
    row = get_db().execute("SELECT * FROM patients WHERE patient_id=?", (patient_id,)).fetchone()
    if not row:
        return jsonify(error="Patient not found."), 404
    return jsonify(patient=dict(row))


@bp.route("/dashboard")
@login_required
def dashboard():
    """One call that feeds every page: patient, latest reading + risk, trend series, alerts, notes."""
    db = get_db()
    pid = request.args.get("patient_id") or Config.DEFAULT_PATIENT_ID
    pat = db.execute("SELECT * FROM patients WHERE patient_id=?", (pid,)).fetchone()
    if not pat:
        return jsonify(error="Patient not found."), 404
    equipment = services.evaluate_equipment(db, pid)   # may raise equipment alerts
    services.check_escalation(db, pid)                  # may escalate an unattended HIGH alert
    db.commit()
    latest = db.execute("SELECT * FROM vitals WHERE patient_id=? ORDER BY timestamp DESC, id DESC LIMIT 1", (pid,)).fetchone()
    series = db.execute("SELECT * FROM vitals WHERE patient_id=? ORDER BY timestamp DESC, id DESC LIMIT 40", (pid,)).fetchall()
    alerts = db.execute("SELECT * FROM alerts WHERE patient_id=? ORDER BY id DESC LIMIT 20", (pid,)).fetchall()
    notes = db.execute("SELECT * FROM caregiver_notes WHERE patient_id=? ORDER BY id DESC LIMIT 5", (pid,)).fetchall()
    events = db.execute("SELECT * FROM system_events WHERE patient_id=? ORDER BY id DESC LIMIT 8", (pid,)).fetchall()
    return jsonify(
        patient=dict(pat),
        latest=services.vital_to_dict(latest) if latest else None,
        series=[services.vital_to_dict(r, with_risk=False) for r in reversed(series)],
        alerts=[services.alert_to_dict(db, a) for a in alerts],
        notes=[dict(n) for n in notes],
        events=[dict(e) for e in events],
        equipment=equipment,
        attendance=services.attendance_status(db, pid),
        server_time=utcnow_iso(),
    )


@bp.route("/simulation/mode", methods=["POST"])
@login_required
def sim_mode():
    """Record the simulator mode (the browser device generator does the drifting)."""
    mode = str((request.get_json(silent=True) or {}).get("mode", "")).upper()
    if mode not in TARGETS:
        return jsonify(error="Mode must be NORMAL, WARNING or CRITICAL."), 400
    db = get_db()
    log_event(db, "sim_mode", "Simulation mode set to " + mode)
    db.commit()
    return jsonify(ok=True, mode=mode, target=TARGETS[mode])


@bp.route("/simulation/reset", methods=["POST"])
@login_required
def sim_reset():
    db = get_db()
    services.reset_simulation(db)
    return jsonify(ok=True)


@bp.route("/events", methods=["GET", "POST"])
@login_required
def events():
    db = get_db()
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        etype = str(d.get("event_type", "")).strip()[:40]
        if etype not in {"internet_failure", "internet_restored", "power_failure", "power_restored"}:
            return jsonify(error="Unknown event type."), 400
        log_event(db, etype, str(d.get("detail", ""))[:200])
        db.commit()
        return jsonify(ok=True), 201
    rows = db.execute("SELECT * FROM system_events ORDER BY id DESC LIMIT 30").fetchall()
    return jsonify(events=[dict(r) for r in rows])


@bp.route("/settings/info")
@login_required
def settings_info():
    b = get_engine().bundle
    return jsonify(
        thresholds={k: {"label": v[0], "unit": v[1], "normal_low": v[2], "normal_high": v[3]}
                    for k, v in safety_rules.VITALS.items()},
        model={"type": "RandomForestClassifier", "synthetic_accuracy": round(b["synthetic_accuracy"], 3),
               "training_samples": b["n_samples"], "features": b["features"],
               "importances": {k: round(v, 3) for k, v in b["importances"].items()}},
    )
