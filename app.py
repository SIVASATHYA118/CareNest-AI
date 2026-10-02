"""CareNest AI - Smart Home Hospital Monitoring & Early Risk Detection System."""
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_cors import CORS

import db
from config import Config
from routes import alerts, auth, caregiver, system, vitals, ward
from routes.auth import login_required


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app, supports_credentials=True)
    app.teardown_appcontext(db.close_db)

    for module in (auth, vitals, alerts, caregiver, system, ward):
        app.register_blueprint(module.bp)

    @app.context_processor
    def inject():
        return {"user_name": session.get("name") or session.get("user")}

    @app.route("/")
    def index():
        return redirect(url_for("dashboard_page" if session.get("user") else "auth.login_page"))

    def page(name, endpoint, **extra):
        @login_required
        def view():
            return render_template(name + ".html", active=name, **extra)
        view.__name__ = endpoint
        app.add_url_rule("/" + name, endpoint, view)

    page("dashboard", "dashboard_page")
    page("patient", "patient_page")
    page("vitals", "vitals_page")
    page("history", "history_page")
    page("alerts", "alerts_page")
    page("caregiver", "caregiver_page")
    page("settings", "settings_page")

    @app.errorhandler(404)
    def not_found(_e):
        if request.path.startswith("/api/"):
            return jsonify(error="Endpoint not found."), 404
        return redirect(url_for("index"))

    @app.errorhandler(500)
    def server_error(_e):
        return jsonify(error="Something went wrong on the server. Your data was not lost; please retry."), 500

    @app.errorhandler(Exception)
    def any_error(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return e
        app.logger.exception("Unhandled error")
        return jsonify(error="Something went wrong on the server. Please retry."), 500

    with app.app_context():
        db.init_db()
    return app


app = create_app()

if __name__ == "__main__":
    print("\n  CareNest AI running at  http://127.0.0.1:5000   (login: admin / admin123)\n")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
