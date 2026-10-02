"""Central configuration for CareNest AI."""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("CARENEST_SECRET", "carenest-demo-secret-change-me")
    DATABASE = os.path.join(BASE_DIR, "database", "database.db")
    MODEL_PATH = os.path.join(BASE_DIR, "ai", "model.pkl")

    DEFAULT_PATIENT_ID = "P001"
    HISTORY_SEED_HOURS = 24          # synthetic history created on first run
    HISTORY_SEED_STEP_MIN = 10       # one seeded reading every 10 minutes
    CONTEXT_NOTE_MINUTES = 60        # caregiver notes count as context for this long
    RECENT_WINDOW = 15               # readings used for trend analysis

    ESCALATION_SECONDS = 45          # demo timer: HIGH alert with no verified caregiver check-in escalates

    DEMO_USERNAME = "admin"
    DEMO_PASSWORD = "admin123"
