"""SQLite helpers: connection handling, schema, seeding."""
import os
import sqlite3
from datetime import datetime, timezone

from flask import g

from config import Config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  full_name TEXT,
  role TEXT
);
CREATE TABLE IF NOT EXISTS patients(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  age INTEGER,
  gender TEXT,
  room TEXT,
  status TEXT DEFAULT 'Monitoring'
);
CREATE TABLE IF NOT EXISTS vitals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id TEXT NOT NULL REFERENCES patients(patient_id),
  heart_rate REAL, spo2 REAL, temperature REAL, respiratory_rate REAL,
  systolic_bp REAL, diastolic_bp REAL,
  timestamp TEXT NOT NULL,
  client_id TEXT UNIQUE,          -- de-duplication key for retried / re-synced readings
  imputed TEXT,                   -- which fields were missing and carried forward
  source TEXT DEFAULT 'live',     -- live | offline-buffer | seed
  risk_level TEXT,
  risk_json TEXT                  -- full explainable assessment
);
CREATE INDEX IF NOT EXISTS idx_vitals_pt_ts ON vitals(patient_id, timestamp);
CREATE TABLE IF NOT EXISTS caregiver_notes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id TEXT NOT NULL REFERENCES patients(patient_id),
  note TEXT NOT NULL,
  translation TEXT,
  language TEXT NOT NULL DEFAULT 'en',
  severity TEXT,
  tags TEXT,
  author TEXT,
  timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id TEXT NOT NULL REFERENCES patients(patient_id),
  risk TEXT NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'New',   -- New | Acknowledged | Responding | Resolved
  vital_id INTEGER,
  acknowledged_at TEXT, acknowledged_by TEXT,
  responding_at TEXT,
  resolved_at TEXT,
  resolved_after_vital_id INTEGER,
  kind TEXT NOT NULL DEFAULT 'vital',   -- vital | equipment
  device TEXT,                          -- set for equipment alerts
  escalated_at TEXT                     -- set when no verified check-in arrived in time
);
CREATE TABLE IF NOT EXISTS caregiver_responses(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alert_id INTEGER NOT NULL REFERENCES alerts(id),
  caregiver TEXT,
  action TEXT,
  response_note TEXT,
  timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS equipment(
  patient_id TEXT NOT NULL,
  device TEXT NOT NULL,
  label TEXT,
  status TEXT,
  value REAL,
  unit TEXT,
  detail TEXT,
  alerted INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT,
  PRIMARY KEY(patient_id, device)
);
CREATE TABLE IF NOT EXISTS attendance(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id TEXT NOT NULL,
  caregiver TEXT,
  action TEXT NOT NULL,                 -- in | out
  method TEXT,
  timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS system_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id TEXT,
  event_type TEXT NOT NULL,
  detail TEXT,
  timestamp TEXT NOT NULL
);
"""


def utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_ts(value):
    """Return an ISO-8601 UTC string with second precision (or now if invalid)."""
    if not value:
        return utcnow_iso()
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return utcnow_iso()


def _connect():
    conn = sqlite3.connect(Config.DATABASE, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = _connect()
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def log_event(db, event_type, detail="", patient_id=None, ts=None):
    db.execute(
        "INSERT INTO system_events(patient_id,event_type,detail,timestamp) VALUES(?,?,?,?)",
        (patient_id or Config.DEFAULT_PATIENT_ID, event_type, detail, ts or utcnow_iso()),
    )


def init_db():
    """Create tables, the demo user/patient and a synthetic 24h history."""
    from werkzeug.security import generate_password_hash
    import services  # local import: services needs the AI engine

    os.makedirs(os.path.dirname(Config.DATABASE), exist_ok=True)
    conn = _connect()
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(alerts)")}
    for name, ddl in (("kind", "TEXT NOT NULL DEFAULT 'vital'"), ("device", "TEXT"), ("escalated_at", "TEXT")):
        if name not in cols:   # upgrade a database created by an older version
            conn.execute("ALTER TABLE alerts ADD COLUMN %s %s" % (name, ddl))
    if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        conn.execute(
            "INSERT INTO users(username,password_hash,full_name,role) VALUES(?,?,?,?)",
            (Config.DEMO_USERNAME, generate_password_hash(Config.DEMO_PASSWORD),
             "Meena (Caregiver)", "caregiver"),
        )
    if not conn.execute("SELECT 1 FROM patients LIMIT 1").fetchone():
        conn.execute(
            "INSERT INTO patients(patient_id,name,age,gender,room,status) VALUES(?,?,?,?,?,?)",
            (Config.DEFAULT_PATIENT_ID, "Arun Kumar", 62, "Male", "Bedroom - Home Ward 1", "Monitoring"),
        )
    conn.commit()
    services.ensure_equipment(conn, Config.DEFAULT_PATIENT_ID)
    conn.commit()
    if not conn.execute("SELECT 1 FROM vitals LIMIT 1").fetchone():
        services.seed_history(conn)
    conn.close()
