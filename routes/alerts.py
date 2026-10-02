"""Alert lifecycle: New -> Acknowledged -> Responding -> Resolved."""
from flask import Blueprint, jsonify, request, session

import services
from config import Config
from db import get_db, log_event, utcnow_iso
from routes.auth import login_required

bp = Blueprint("alerts", __name__, url_prefix="/api")


@bp.route("/alerts")
@login_required
def list_alerts():
    db = get_db()
    pid = request.args.get("patient_id") or Config.DEFAULT_PATIENT_ID
    status = request.args.get("status")
    sql, args = "SELECT * FROM alerts WHERE patient_id=?", [pid]
    if status == "open":
        sql += " AND status!='Resolved'"
    elif status:
        sql += " AND status=?"; args.append(status)
    rows = db.execute(sql + " ORDER BY id DESC LIMIT 100", args).fetchall()
    return jsonify(alerts=[services.alert_to_dict(db, r) for r in rows])


def _transition(alert_id, new_status, allowed_from, column, action_label):
    db = get_db()
    row = db.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
    if not row:
        return jsonify(error="Alert not found."), 404
    if row["status"] == new_status:
        return jsonify(ok=True, alert=services.alert_to_dict(db, row), unchanged=True)
    if row["status"] not in allowed_from:
        return jsonify(error="Cannot mark a %s alert as %s." % (row["status"].lower(), new_status.lower())), 409
    now = utcnow_iso()
    who = session.get("name") or session.get("user")
    extra = ""
    params = [new_status, now]
    if new_status == "Acknowledged":
        extra = ", acknowledged_by=?"; params.append(who)
    if new_status == "Resolved":
        last = db.execute("SELECT MAX(id) m FROM vitals WHERE patient_id=?", (row["patient_id"],)).fetchone()["m"]
        extra = ", resolved_after_vital_id=?"; params.append(last or 0)
    db.execute("UPDATE alerts SET status=?, %s=?%s WHERE id=?" % (column, extra), params + [alert_id])
    note = str((request.get_json(silent=True) or {}).get("response_note", "")).strip()
    db.execute("INSERT INTO caregiver_responses(alert_id,caregiver,action,response_note,timestamp) VALUES(?,?,?,?,?)",
               (alert_id, who, action_label, note[:1000], now))
    log_event(db, "alert_" + new_status.lower(), "Alert #%d %s by %s" % (alert_id, new_status.lower(), who), row["patient_id"])
    db.commit()
    row = db.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
    return jsonify(ok=True, alert=services.alert_to_dict(db, row))


@bp.route("/alerts/<int:alert_id>/acknowledge", methods=["POST"])
@login_required
def acknowledge(alert_id):
    return _transition(alert_id, "Acknowledged", ("New",), "acknowledged_at", "acknowledged")


@bp.route("/alerts/<int:alert_id>/responding", methods=["POST"])
@login_required
def responding(alert_id):
    return _transition(alert_id, "Responding", ("New", "Acknowledged"), "responding_at", "responding")


@bp.route("/alerts/<int:alert_id>/resolve", methods=["POST"])
@login_required
def resolve(alert_id):
    return _transition(alert_id, "Resolved", ("New", "Acknowledged", "Responding"), "resolved_at", "resolved")
