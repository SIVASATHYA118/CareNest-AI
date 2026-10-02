"""
Train the prototype risk classifier on an automatically generated SYNTHETIC dataset.

Run:  python ai/train_model.py      (app.py also trains automatically if model.pkl is missing)
"""
import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config  # noqa: E402

FEATURES = ["heart_rate", "spo2", "temperature", "respiratory_rate",
            "systolic_bp", "diastolic_bp", "trend_score"]
LEVELS = ["LOW", "MEDIUM", "HIGH"]


def _deviation_score(df):
    """Weighted distance outside the normal range -> continuous synthetic risk score."""
    z = np.zeros(len(df))
    z += 1.0 * np.maximum.reduce([np.zeros(len(df)), (df.heart_rate - 100) / 20, (60 - df.heart_rate) / 15])
    z += 2.0 * np.maximum(0, (95 - df.spo2) / 3)
    z += 1.5 * np.maximum.reduce([np.zeros(len(df)), (df.temperature - 37.5) / 1.0, (36.1 - df.temperature) / 1.0])
    z += 1.5 * np.maximum.reduce([np.zeros(len(df)), (df.respiratory_rate - 20) / 5, (12 - df.respiratory_rate) / 3])
    z += 0.6 * np.maximum.reduce([np.zeros(len(df)), (df.systolic_bp - 130) / 25, (90 - df.systolic_bp) / 15])
    z += 0.4 * np.maximum.reduce([np.zeros(len(df)), (df.diastolic_bp - 90) / 15, (60 - df.diastolic_bp) / 10])
    z += 0.7 * df.trend_score
    return z


def generate_dataset(n=6000, seed=42):
    rng = np.random.default_rng(seed)
    # (class weight, means, sds, trend mean) for three synthetic patient states
    profiles = [
        (0.45, [72, 98, 36.8, 16, 118, 78], [8, 1.0, 0.3, 2, 9, 6], 0.3),
        (0.30, [104, 94, 38.0, 22, 135, 85], [10, 1.5, 0.5, 3, 12, 8], 1.0),
        (0.25, [125, 89, 39.0, 28, 150, 95], [12, 3.0, 0.7, 4, 16, 10], 2.0),
    ]
    rows = []
    counts = rng.multinomial(n, [p[0] for p in profiles])
    for (_, mean, sd, tmean), c in zip(profiles, counts):
        vals = rng.normal(mean, sd, size=(c, 6))
        trend = np.clip(rng.normal(tmean, 0.7, size=c), 0, 4)
        rows.append(np.column_stack([vals, trend]))
    df = pd.DataFrame(np.vstack(rows), columns=FEATURES)
    df["spo2"] = df["spo2"].clip(70, 100)
    score = _deviation_score(df) + rng.normal(0, 0.25, len(df))
    df["risk_level"] = np.where(score >= 5.0, "HIGH", np.where(score >= 1.2, "MEDIUM", "LOW"))
    return df


def train(save=True, verbose=False):
    df = generate_dataset()
    X_tr, X_te, y_tr, y_te = train_test_split(df[FEATURES], df["risk_level"], test_size=0.2,
                                              random_state=42, stratify=df["risk_level"])
    model = RandomForestClassifier(n_estimators=60, max_depth=12, random_state=42, class_weight="balanced")
    model.fit(X_tr, y_tr)
    pred = model.predict(X_te)
    acc = float(accuracy_score(y_te, pred))
    if verbose:
        print("Synthetic hold-out accuracy: %.3f" % acc)
        print(classification_report(y_te, pred))
    bundle = {"model": model, "features": FEATURES, "synthetic_accuracy": acc,
              "n_samples": len(df), "importances": dict(zip(FEATURES, map(float, model.feature_importances_)))}
    if save:
        joblib.dump(bundle, Config.MODEL_PATH)
        if verbose:
            print("Saved model to", Config.MODEL_PATH)
    return bundle


if __name__ == "__main__":
    train(save=True, verbose=True)
