"""
Hybrid risk engine:  ML prediction + safety rules + recent trend + caregiver context.

Output is ALWAYS one of LOW / MEDIUM / HIGH with a plain-language explanation.
This is decision support for demonstration - it never states a diagnosis.
"""
import os

import joblib
import pandas as pd

from ai import safety_rules as sr
from ai.train_model import FEATURES, train
from config import Config

LEVELS, RANK = sr.LEVELS, sr.RANK
DISCLAIMER = "Risk detected based on monitored vital trends and available caregiver context."
EARLY_LABEL = "Prototype early-warning estimation based on simulated trends."
VITAL_KEYS = ["heart_rate", "spo2", "temperature", "respiratory_rate", "systolic_bp", "diastolic_bp"]


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def _mean(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else None


class RiskEngine:
    def __init__(self):
        self.bundle = None
        self.load()

    def load(self):
        try:
            if not os.path.exists(Config.MODEL_PATH):
                train(save=True)
            self.bundle = joblib.load(Config.MODEL_PATH)
        except Exception:                      # corrupt/incompatible pickle -> retrain
            self.bundle = train(save=True)

    # ---------------- trend ----------------
    @staticmethod
    def compute_trend(current, recent):
        """recent = previous readings, oldest first. Compare newest 3 vs oldest of window."""
        window = list(recent) + [current]
        if len(window) < 6:
            return 0.0, {}, {}
        latest, base = window[-3:], window[:min(6, len(window) - 3)]
        d = {}
        for k in VITAL_KEYS:
            a, b = _mean(latest, k), _mean(base, k)
            d[k] = (a - b) if (a is not None and b is not None) else 0.0
        score = (_clip(d["heart_rate"] / 15, 0, 1) + _clip(d["temperature"] / 0.6, 0, 1)
                 + _clip(d["respiratory_rate"] / 4, 0, 1) + _clip(-d["spo2"] / 3, 0, 1))
        dirs = {
            "heart_rate": "up" if d["heart_rate"] >= 5 else "steady",
            "temperature": "up" if d["temperature"] >= 0.2 else "steady",
            "respiratory_rate": "up" if d["respiratory_rate"] >= 2 else "steady",
            "spo2": "down" if d["spo2"] <= -1 else "steady",
        }
        return float(score), dirs, d

    # ---------------- ML ----------------
    def ml_predict(self, current, trend_score):
        row = {k: current.get(k) for k in VITAL_KEYS}
        row["trend_score"] = trend_score
        X = pd.DataFrame([row], columns=FEATURES)
        model = self.bundle["model"]
        probs = model.predict_proba(X)[0]
        pmap = {c: float(p) for c, p in zip(model.classes_, probs)}
        level = max(pmap, key=pmap.get)
        return level, {l: round(pmap.get(l, 0.0), 3) for l in LEVELS}

    # ---------------- main entry ----------------
    def assess(self, current, recent=(), notes=()):
        """
        current: dict of six vitals; recent: previous readings (oldest first, each may include
        vitals only); notes: recent caregiver notes as dicts with 'severity','tags','labels'.
        """
        trend_score, dirs, deltas = self.compute_trend(current, recent)
        ml_level, probs = self.ml_predict(current, trend_score)
        rules = sr.evaluate(current)
        level = ml_level if RANK[ml_level] >= RANK[rules["rule_level"]] else rules["rule_level"]
        n_abn = len(rules["abnormal"])

        # persistence: last 5 readings + current all have >= 3 abnormal vitals
        tail = list(recent)[-5:] + [current]
        persistent = len(tail) >= 6 and all(len(sr.evaluate(r)["abnormal"]) >= 3 for r in tail)

        adjustments = []
        # recent trend
        if level == "LOW" and trend_score >= 2 and n_abn >= 1:
            level = "MEDIUM"; adjustments.append("trend")
        elif level == "MEDIUM" and trend_score >= 3 and rules["severe_count"] >= 1:
            level = "HIGH"; adjustments.append("trend")
        # persistence
        if persistent and level == "LOW":
            level = "MEDIUM"; adjustments.append("persistence")
        # caregiver context
        note_sev = "none"
        note_labels = []
        for n in notes:
            note_labels += [l for l in n.get("labels", []) if l not in note_labels]
            if n.get("severity") == "severe":
                note_sev = "severe"
            elif n.get("severity") == "moderate" and note_sev == "none":
                note_sev = "moderate"
        if note_sev == "severe":
            if level == "MEDIUM" and n_abn >= 2:
                level = "HIGH"; adjustments.append("caregiver")
            elif level == "LOW" and n_abn >= 1:
                level = "MEDIUM"; adjustments.append("caregiver")
        elif note_sev == "moderate" and level == "LOW" and n_abn >= 2:
            level = "MEDIUM"; adjustments.append("caregiver")

        escalation = 0 if n_abn == 0 else (1 if not persistent else 2)
        if persistent and level == "HIGH":
            escalation = 3

        reasons = self._reasons(level, rules, dirs, trend_score, persistent, note_sev, note_labels, adjustments)
        early = self._early_warning(level, dirs, deltas, trend_score, persistent, probs)
        return {
            "level": level, "ml_level": ml_level, "ml_probabilities": probs,
            "rule_level": rules["rule_level"], "rule_flags": rules["flags"],
            "abnormal": rules["abnormal"], "trend_score": round(trend_score, 2),
            "trend": dirs, "persistent": persistent, "escalation_level": escalation,
            "context": {"severity": note_sev, "labels": note_labels},
            "adjustments": adjustments, "reasons": reasons,
            "summary": ("The current pattern indicates increased monitoring risk."
                        if level != "LOW" else "No elevated risk pattern detected in the monitored data."),
            "disclaimer": DISCLAIMER, "early_warning": early,
        }

    # ---------------- explanation ----------------
    @staticmethod
    def _reasons(level, rules, dirs, trend_score, persistent, note_sev, note_labels, adjustments):
        if level == "LOW" and not rules["abnormal"]:
            r = ["Current vital signs are within the configured monitoring range.",
                 "No significant deterioration trend detected."]
            r.append("No concerning caregiver note detected." if note_sev == "none"
                     else "Caregiver note reviewed: " + ", ".join(note_labels) + ".")
            return r
        text = {
            ("heart_rate", "high", 2): "Heart rate has increased significantly.",
            ("heart_rate", "high", 1): "Heart rate is elevated.",
            ("heart_rate", "low", 1): "Heart rate is below the normal monitoring range.",
            ("heart_rate", "low", 2): "Heart rate is well below the normal monitoring range.",
            ("spo2", "low", 1): "SpO₂ is below the normal monitoring range.",
            ("spo2", "low", 2): "SpO₂ is significantly below the normal monitoring range.",
            ("temperature", "high", 1): "Temperature is above the normal monitoring range.",
            ("temperature", "high", 2): "Temperature is well above the normal monitoring range.",
            ("temperature", "low", 1): "Temperature is below the normal monitoring range.",
            ("temperature", "low", 2): "Temperature is well below the normal monitoring range.",
            ("respiratory_rate", "high", 1): "Respiratory rate is elevated.",
            ("respiratory_rate", "high", 2): "Respiratory rate is significantly elevated.",
            ("respiratory_rate", "low", 1): "Respiratory rate is below the normal monitoring range.",
            ("respiratory_rate", "low", 2): "Respiratory rate is well below the normal monitoring range.",
            ("systolic_bp", "high", 1): "Blood pressure is above the normal monitoring range.",
            ("systolic_bp", "high", 2): "Blood pressure is well above the normal monitoring range.",
            ("diastolic_bp", "high", 1): "Blood pressure is above the normal monitoring range.",
            ("diastolic_bp", "high", 2): "Blood pressure is well above the normal monitoring range.",
            ("systolic_bp", "low", 1): "Blood pressure is below the normal monitoring range.",
            ("systolic_bp", "low", 2): "Blood pressure is well below the normal monitoring range.",
            ("diastolic_bp", "low", 1): "Blood pressure is below the normal monitoring range.",
            ("diastolic_bp", "low", 2): "Blood pressure is well below the normal monitoring range.",
        }
        out = []
        for a in sorted(rules["abnormal"], key=lambda a: -a["severity"]):
            t = text.get((a["vital"], a["direction"], a["severity"]))
            if t and t not in out and len(out) < 4:       # keep the explanation short
                out.append(t)
        combos = [f for f in rules["flags"] if "combined" in f or "together" in f]
        out.extend(combos[:1])
        arrows = [n for n, k, s in (("heart rate ↑", "heart_rate", "up"), ("temperature ↑", "temperature", "up"),
                                    ("respiratory rate ↑", "respiratory_rate", "up"), ("SpO₂ ↓", "spo2", "down"))
                  if dirs.get(k) == s]
        if arrows:
            out.append("Recent readings show a worsening trend (%s)." % ", ".join(arrows))
        if persistent:
            out.append("Multiple abnormal vitals have persisted across recent readings.")
        if note_sev != "none":
            out.append("Caregiver reported " + ", ".join(note_labels) + ".")
        return out or ["Recent readings are close to the edge of the monitoring range."]

    @staticmethod
    def _early_warning(level, dirs, deltas, trend_score, persistent, probs):
        worse = [n for n, ok in (("Heart rate ↑", deltas.get("heart_rate", 0) >= 7.5),
                                 ("Temperature ↑", deltas.get("temperature", 0) >= 0.3),
                                 ("Respiratory rate ↑", deltas.get("respiratory_rate", 0) >= 2),
                                 ("SpO₂ ↓", deltas.get("spo2", 0) <= -1.5)) if ok]
        active = len(worse) >= 2 or (RANK[level] >= 1 and (len(worse) >= 1 or persistent))
        p_risk = probs.get("MEDIUM", 0) * 0.5 + probs.get("HIGH", 0)
        index = int(round(100 * _clip(0.5 * trend_score / 4 + 0.5 * p_risk, 0, 1)))
        if active:
            msg = "Potential deterioration trend detected."
            action = "Increase monitoring frequency and review the patient."
            window = "Elevated watch suggested for the next 24–48 hours."
        else:
            msg = "No deterioration trend detected in recent readings."
            action = "Continue routine monitoring."
            window = "No elevated watch window suggested."
        return {"active": active, "message": msg, "trend_signals": worse, "suggested_action": action,
                "watch_window": window, "index": index, "label": EARLY_LABEL}


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = RiskEngine()
    return _engine
