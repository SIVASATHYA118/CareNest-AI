"""Authentication: simple session login (demo credentials only)."""
from functools import wraps

from flask import Blueprint, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash

from db import get_db, log_event

bp = Blueprint("auth", __name__)


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("user"):
            if request.path.startswith("/api/"):
                return jsonify(error="Authentication required. Please log in again."), 401
            return redirect(url_for("auth.login_page"))
        return fn(*a, **kw)
    return wrapper


@bp.route("/login")
def login_page():
    from flask import render_template
    if session.get("user"):
        return redirect(url_for("dashboard_page"))
    return render_template("login.html")


@bp.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not username or not password:
        return jsonify(error="Enter both username and password."), 400
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify(error="Incorrect username or password."), 401
    session["user"] = row["username"]
    session["name"] = row["full_name"]
    log_event(db, "login", "User %s signed in" % username)
    db.commit()
    return jsonify(ok=True, redirect=url_for("dashboard_page"))


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login_page"))
