"""
Rule-based safety layer.

IMPORTANT: every threshold here is PROTOTYPE SAFETY LOGIC chosen for demonstration.
They are not clinically validated and are not diagnostic criteria.
"""

LEVELS = ["LOW", "MEDIUM", "HIGH"]
RANK = {l: i for i, l in enumerate(LEVELS)}

# name: (label, unit, normal_low, normal_high, severe_low, severe_high)
#   value outside normal range  -> mild abnormal (1 point)
#   value beyond severe bounds  -> significantly abnormal (2 points)
VITALS = {
    "heart_rate":       ("Heart rate", "bpm", 60, 100, 50, 120),
    "spo2":             ("SpO₂", "%", 95, 101, 92, None),
    "temperature":      ("Temperature", "°C", 36.1, 37.5, 35.5, 38.5),
    "respiratory_rate": ("Respiratory rate", "/min", 12, 20, 9, 25),
    "systolic_bp":      ("Systolic BP", "mmHg", 90, 130, 80, 160),
    "diastolic_bp":     ("Diastolic BP", "mmHg", 60, 90, 50, 100),
}


def grade(name, value):
    """Return (direction, severity) where direction in low/high/normal, severity 0-2."""
    _, _, lo, hi, slo, shi = VITALS[name]
    if value is None:
        return "normal", 0
    if value < lo:
        return "low", 2 if (slo is not None and value < slo) else 1
    if value > hi:
        return "high", 2 if (shi is not None and value >= shi) else 1
    return "normal", 0


def evaluate(v):
    """Apply the safety rules to one reading (dict with the six vitals)."""
    abnormal = []
    for name in VITALS:
        direction, sev = grade(name, v.get(name))
        if sev:
            abnormal.append({"vital": name, "direction": direction, "severity": sev})
    points = sum(a["severity"] for a in abnormal)
    severe_count = sum(1 for a in abnormal if a["severity"] == 2)

    hr, spo2, temp, rr = v.get("heart_rate"), v.get("spo2"), v.get("temperature"), v.get("respiratory_rate")
    level, flags = "LOW", []

    def bump(new, text):
        nonlocal level
        if RANK[new] > RANK[level]:
            level = new
        flags.append(text)

    if spo2 is not None and spo2 < 90:
        bump("HIGH", "SpO₂ is significantly below the normal monitoring range.")
    elif spo2 is not None and spo2 < 92:
        bump("MEDIUM", "SpO₂ is clearly below the normal monitoring range.")
    if hr is not None and (hr >= 130 or hr < 45):
        bump("HIGH", "Heart rate is far outside the normal monitoring range.")
    if temp is not None and hr is not None and temp >= 38.5 and hr >= 110:
        bump("HIGH", "High temperature together with a high heart rate.")
    elif temp is not None and hr is not None and temp > 37.5 and hr > 100:
        bump("MEDIUM", "Temperature and heart rate are both elevated.")
    if rr is not None and spo2 is not None and rr >= 24 and spo2 < 93:
        bump("HIGH", "Elevated respiratory rate combined with low SpO₂ (high-risk safety rule).")
    elif rr is not None and spo2 is not None and rr > 20 and spo2 < 95:
        bump("MEDIUM", "Respiratory rate is elevated while SpO₂ is below range.")
    if severe_count >= 2 or points >= 8:
        bump("HIGH", "Multiple vitals are significantly abnormal at the same time.")
    elif len(abnormal) >= 3:
        bump("MEDIUM", "Several vitals are outside the normal monitoring range.")
    elif severe_count == 1:
        bump("MEDIUM", "One vital is significantly outside the normal monitoring range.")

    return {"rule_level": level, "abnormal": abnormal, "points": points,
            "severe_count": severe_count, "flags": flags}
