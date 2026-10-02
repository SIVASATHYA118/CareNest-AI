"""Medical-equipment simulation controls and caregiver attendance (check-in / check-out)."""
from flask import Blueprint, jsonify, request, session

import services
from config import Config
from db import get_db
from routes.auth import login_required

bp = Blueprint("ward", __name__, url_prefix="/api")


def _pid():
    return request.args.get("patient_id") or (request.get_json(silent=True) or {}).get("patient_id") or Config.DEFAULT_PATIENT_ID


@bp.route("/equipment")
@login_required
def equipment():
    db = get_db()
    data = services.evaluate_equipment(db, _pid())
    db.commit()
    return jsonify(equipment=data)


@bp.route("/equipment/fault", methods=["POST"])
@login_required
def equipment_fault():
    db = get_db()
    fault = str((request.get_json(silent=True) or {}).get("fault", "")).lower()
    try:
        services.set_equipment_fault(db, _pid(), fault)
    except services.ValidationError as e:
        return jsonify(error=str(e)), 400
    data = services.evaluate_equipment(db, _pid())
    db.commit()
    return jsonify(ok=True, equipment=data)


@bp.route("/attendance", methods=["GET", "POST"])
@login_required
def attendance():
    db = get_db()
    pid = _pid()
    if request.method == "POST":
        action = str((request.get_json(silent=True) or {}).get("action", "")).lower()
        who = session.get("name") or session.get("user")
        try:
            changed = services.record_attendance(db, pid, who, action)
        except services.ValidationError as e:
            return jsonify(error=str(e)), 400
        db.commit()
        return jsonify(ok=True, changed=changed, attendance=services.attendance_status(db, pid)), 201 if changed else 200
    return jsonify(attendance=services.attendance_status(db, pid))
