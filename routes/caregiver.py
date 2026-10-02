"""Caregiver notes (English/Tamil) and caregiver responses to alerts."""
from flask import Blueprint, jsonify, request, session

from ai import note_context
from config import Config
from db import get_db, log_event, normalize_ts, utcnow_iso
from routes.auth import login_required
import services

bp = Blueprint("caregiver", __name__, url_prefix="/api")


@bp.route("/caregiver-note", methods=["POST"])
@login_required
def add_note():
    data = request.get_json(silent=True) or {}
    text = str(data.get("note", "")).strip()
    lang = str(data.get("language", "en")).lower()
    if not text:
        return jsonify(error="Please type a note before saving."), 400
    if len(text) > 1000:
        return jsonify(error="Note is too long (max 1000 characters)."), 400
    if lang not in ("en", "ta"):
        return jsonify(error="Language must be 'en' or 'ta'."), 400
    pid = data.get("patient_id") or Config.DEFAULT_PATIENT_ID
    info = note_context.analyze(text, lang)
    db = get_db()
    ts = normalize_ts(data.get("timestamp"))
    cur = db.execute(
        "INSERT INTO caregiver_notes(patient_id,note,translation,language,severity,tags,author,timestamp) VALUES(?,?,?,?,?,?,?,?)",
        (pid, text, note_context.translate(text, lang), lang, info["severity"], ",".join(info["tags"]),
         session.get("name") or session.get("user"), ts))
    log_event(db, "caregiver_note", "Note added (%s, context: %s)" % (lang, info["severity"]), pid)
    db.commit()
    return jsonify(ok=True, id=cur.lastrowid, analysis=info), 201


@bp.route("/caregiver-notes")
@login_required
def list_notes():
    pid = request.args.get("patient_id") or Config.DEFAULT_PATIENT_ID
    rows = get_db().execute("SELECT * FROM caregiver_notes WHERE patient_id=? ORDER BY id DESC LIMIT 50", (pid,)).fetchall()
    notes = []
    for r in rows:
        d = dict(r)
        d["labels"] = note_context.analyze(r["note"], r["language"])["labels"]
        notes.append(d)
    return jsonify(notes=notes, presets=note_context.PRESETS)


@bp.route("/caregiver-response", methods=["POST"])
@login_required
def add_response():
    data = request.get_json(silent=True) or {}
    note = str(data.get("response_note", "")).strip()
    try:
        alert_id = int(data.get("alert_id"))
    except (TypeError, ValueError):
        return jsonify(error="alert_id is required."), 400
    if not note:
        return jsonify(error="Please type a response note."), 400
    db = get_db()
    if not db.execute("SELECT 1 FROM alerts WHERE id=?", (alert_id,)).fetchone():
        return jsonify(error="Alert not found."), 404
    db.execute("INSERT INTO caregiver_responses(alert_id,caregiver,action,response_note,timestamp) VALUES(?,?,?,?,?)",
               (alert_id, session.get("name") or session.get("user"), "note", note[:1000], utcnow_iso()))
    db.commit()
    return jsonify(ok=True), 201
