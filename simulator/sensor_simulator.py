"""
Software sensor simulator (no hardware needed).

Values do NOT jump randomly. Each vital starts at a baseline and drifts toward the
target of the active mode with small noise, so transitions look like a real patient
slowly getting better or worse. The browser runs an equivalent generator
(static/js/simulator.js) so the "bedside device" keeps working while the server is
unreachable; this Python version is used for seeding history and for tests.
"""
import random
from datetime import datetime, timedelta, timezone

TARGETS = {
    "NORMAL":   {"heart_rate": 72,  "spo2": 98, "temperature": 36.8, "respiratory_rate": 16, "systolic_bp": 118, "diastolic_bp": 78},
    "WARNING":  {"heart_rate": 105, "spo2": 94, "temperature": 38.0, "respiratory_rate": 22, "systolic_bp": 135, "diastolic_bp": 85},
    "CRITICAL": {"heart_rate": 125, "spo2": 89, "temperature": 39.0, "respiratory_rate": 28, "systolic_bp": 150, "diastolic_bp": 95},
}
NOISE = {"heart_rate": 1.5, "spo2": 0.4, "temperature": 0.05, "respiratory_rate": 0.6,
         "systolic_bp": 2.0, "diastolic_bp": 1.5}
DECIMALS = {"heart_rate": 0, "spo2": 1, "temperature": 1, "respiratory_rate": 0,
            "systolic_bp": 0, "diastolic_bp": 0}


class SensorSimulator:
    def __init__(self, mode="NORMAL", seed=None):
        self.rng = random.Random(seed)
        self.mode = mode if mode in TARGETS else "NORMAL"
        self.current = dict(TARGETS["NORMAL"])

    def set_mode(self, mode):
        if mode not in TARGETS:
            raise ValueError("Unknown mode: %s" % mode)
        self.mode = mode

    def step(self, rate=0.3):
        """Move each vital a fraction `rate` toward the target, then add small noise."""
        target = TARGETS[self.mode]
        out = {}
        for k, tgt in target.items():
            self.current[k] += (tgt - self.current[k]) * rate
            noisy = self.current[k] + self.rng.gauss(0, NOISE[k])
            if k == "spo2":
                noisy = min(noisy, 100)
            out[k] = round(noisy, DECIMALS[k])
        return out


def generate_history(hours=24, step_minutes=10, seed=7):
    """Synthetic history: mostly normal with one mild 'warning' episode."""
    sim = SensorSimulator(seed=seed)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    n = int(hours * 60 / step_minutes)
    episode = range(int(n * 0.30), int(n * 0.30) + 5)   # ~50 minutes of mild deterioration
    rows = []
    for i in range(n):
        ts = now - timedelta(minutes=step_minutes * (n - i))
        sim.set_mode("WARNING" if i in episode else "NORMAL")
        reading = sim.step(rate=0.5)
        reading["timestamp"] = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append(reading)
    return rows
