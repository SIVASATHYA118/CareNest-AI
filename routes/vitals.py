"""Vitals ingestion, history and AI risk endpoints."""
import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

import services
from ai.risk_engine import get_engine
from config import Config
from db import get_db, log_event, normalize_ts
from routes.auth import login_required

bp = Blueprint("vitals", __name__, url_prefix="/api")


def _pid():
    return request.args.get("patient_id") or Config.DEFAULT_PATIENT_ID


@bp.route("/vitals", methods=["POST"])
@login_required
def post_vitals():
    db = get_db()
    data = request.get_json(silent=True)
    try:
        result = services.ingest_reading(db, data or {})
    except services.ValidationError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, **result), (200 if result["duplicate"] else 201)


@bp.route("/vitals/latest")
@login_required
def latest():
    db = get_db()
    row = db.execute("SELECT * FROM vitals WHERE patient_id=? ORDER BY timestamp DESC, id DESC LIMIT 1", (_pid(),)).fetchone()
    if not row:
        return jsonify(vital=None)
    return jsonify(vital=services.vital_to_dict(row))


@bp.route("/vitals/history")
@login_required
def history():
    """?hours=1|6|24  -> evenly down-sampled series for charts (max `limit` points).
       ?latest=N      -> the most recent N readings with explanations (for tables)."""
    db = get_db()
    pid = _pid()
    if request.args.get("latest"):
        try:
            n = max(1, min(200, int(request.args["latest"])))
        except ValueError:
            return jsonify(error="latest must be a number"), 400
        rows = db.execute("SELECT * FROM vitals WHERE patient_id=? ORDER BY timestamp DESC, id DESC LIMIT ?", (pid, n)).fetchall()
        return jsonify(readings=[services.vital_to_dict(r) for r in rows])
    try:
        hours = float(request.args.get("hours", 1))
        limit = max(20, min(600, int(request.args.get("limit", 240))))
    except ValueError:
        return jsonify(error="hours and limit must be numbers"), 400
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = db.execute("SELECT * FROM vitals WHERE patient_id=? AND timestamp>=? ORDER BY timestamp, id", (pid, since)).fetchall()
    total = len(rows)
    if total > limit:                        # stride sampling keeps charts light
        step = total / limit
        rows = [rows[int(i * step)] for i in range(limit)] + [rows[-1]]
    return jsonify(total=total, readings=[services.vital_to_dict(r, with_risk=False) for r in rows])


@bp.route("/risk/analyze", methods=["POST"])
@login_required
def analyze():
    """Run the risk engine on supplied vitals WITHOUT storing them (what-if / testing)."""
    db = get_db()
    data = request.get_json(silent=True) or {}
    pid = data.get("patient_id") or Config.DEFAULT_PATIENT_ID
    last = db.execute("SELECT * FROM vitals WHERE patient_id=? ORDER BY timestamp DESC, id DESC LIMIT 1", (pid,)).fetchone()
    try:
        vitals, imputed = services.clean_reading(data, services._row_vitals(last) if last else None)
    except services.ValidationError as e:
        return jsonify(error=str(e)), 400
    prev = db.execute("SELECT * FROM vitals WHERE patient_id=? ORDER BY timestamp DESC, id DESC LIMIT ?",
                      (pid, Config.RECENT_WINDOW)).fetchall()
    recent = [services._row_vitals(r) for r in reversed(prev)]
    notes = services.recent_notes(db, pid, normalize_ts(None))
    return jsonify(risk=get_engine().assess(vitals, recent, notes), imputed=imputed)


@bp.route("/risk/current")
@login_required
def current_risk():
    db = get_db()
    row = db.execute("SELECT * FROM vitals WHERE patient_id=? ORDER BY timestamp DESC, id DESC LIMIT 1", (_pid(),)).fetchone()
    if not row:
        return jsonify(risk=None)
    return jsonify(risk=json.loads(row["risk_json"]), vital=services.vital_to_dict(row, with_risk=False))


@bp.route("/sync", methods=["POST"])
@login_required
def sync():
    """Accept readings buffered while offline / on backup power. Idempotent via client_id."""
    db = get_db()
    data = request.get_json(silent=True) or {}
    readings = data.get("readings")
    if not isinstance(readings, list):
        return jsonify(error="Expected {'readings': [...]}"), 400
    readings = sorted(readings, key=lambda r: normalize_ts((r or {}).get("timestamp")) if isinstance(r, dict) else "")
    stored = dup = bad = 0
    errors = []
    for r in readings:
        try:
            res = services.ingest_reading(db, r if isinstance(r, dict) else {}, source="offline-buffer", commit=False)
            if res["duplicate"]:
                dup += 1
            else:
                stored += 1
        except services.ValidationError as e:
            bad += 1
            errors.append(str(e))
    log_event(db, "sync_complete", "Synced %d buffered readings (%d duplicates, %d rejected)" % (stored, dup, bad))
    db.commit()
    return jsonify(ok=True, stored=stored, duplicates=dup, rejected=bad, errors=errors[:5])
