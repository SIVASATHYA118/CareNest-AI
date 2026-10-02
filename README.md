# CareNest AI

**Smart Home Hospital Monitoring & Early Risk Detection System**
*A virtual hospital ward for safer home healthcare.*

Prototype for the hackathon challenge **"Operation Ward Zero — Build a Hospital That Fits Inside a Bedroom"**.

> CareNest AI is a prototype decision-support system using simulated data. Risk levels are intended for demonstration and do not constitute medical diagnosis or treatment advice. Real-world deployment would require clinical validation, regulatory review, cybersecurity controls and professional oversight.

## 1. Problem
Patients recovering at home lack the continuous observation of a hospital ward. Deterioration is often noticed late, connectivity and power at home are unreliable, and caregivers may write notes in their own language.

## 2. Solution
A software "ward" for one bedroom: simulated bedside sensors stream vitals to a Flask backend, an AI-assisted risk engine classifies the situation as **LOW / MEDIUM / HIGH** with a plain-language explanation, alerts reach the caregiver, and the caregiver acknowledges, responds and resolves. The bedside device keeps recording through internet or power loss and re-syncs afterwards.

```
Sensors (simulated) -> Data collection -> Flask + SQLite -> Dashboard
        -> AI risk engine -> Risk level -> Explanation -> Alert -> Caregiver -> Acknowledge + respond
```

## 3. Features
- Login, hospital-style dashboard, sidebar navigation, responsive layout
- Sensor simulator with NORMAL / WARNING / CRITICAL modes (gradual drift, not random jumps)
- Vitals: heart rate, SpO₂, temperature, respiratory rate, blood pressure; live charts
- History page with 1 h / 6 h / 24 h charts and a table with risk + explanation per reading
- Hybrid AI risk engine: RandomForest + safety rules + trend + caregiver-note context
- Explainable output ("Why?") and an Early Deterioration Indicator
- Alert manager: New -> Acknowledged -> Responding -> Resolved, with response notes
- English and Tamil caregiver notes used as risk context
- Offline mode (localStorage buffer + sync) and power-failure (backup mode) simulation
- **Medical-equipment monitoring**: simulated SpO₂ probe, oxygen concentrator and bedside backup battery; a fault raises an equipment alert that follows the same acknowledge / respond / resolve workflow (battery drains during a simulated power failure)
- **Caregiver attendance verification**: simulated bedside NFC check-in / check-out; a HIGH alert with no verified check-in within the demo timer (45 s) is escalated to a secondary contact (simulated)
- Alert delivery: in-app banner, toast and sound; SMS / push are simulated (no external service needed)
- Demo control panel on every page

## 4. Architecture
See [docs/architecture.md](docs/architecture.md).

## 5. Technology stack
Python 3, Flask, Flask-CORS, SQLite, scikit-learn (RandomForest), pandas/numpy/joblib; HTML5, CSS3, vanilla JavaScript, Chart.js (bundled locally, so charts work with no internet).

## 6. Installation (Windows)
```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
(or double-click `run.bat`). On macOS/Linux use `source venv/bin/activate`.

## 7. How to run
Open **http://127.0.0.1:5000**. On first start the app creates the SQLite database, seeds 24 h of synthetic history and trains the model automatically (`ai/model.pkl`). To retrain manually: `python ai/train_model.py`.

## 8. Demo credentials
`admin` / `admin123`  (default patient: Arun Kumar, P001, 62, Male)

Step-by-step judge script: [docs/demo-script.md](docs/demo-script.md).

## 9. AI approach
Final risk = **ML prediction + safety rules + recent trend + caregiver context**.
1. **ML** – RandomForestClassifier trained on an automatically generated *synthetic* dataset (features: heart rate, SpO₂, temperature, respiratory rate, systolic/diastolic BP, trend score).
2. **Safety rules** (`ai/safety_rules.py`) – prototype thresholds and combinations (e.g. high RR + low SpO₂ -> HIGH). The final level is never lower than the rules' level, so ML alone cannot hide a dangerous pattern.
3. **Trend** – newest readings vs. the older part of the recent window (heart rate, temperature, respiratory rate up; SpO₂ down). Persistent multi-vital abnormality raises the escalation level.
4. **Caregiver context** – English/Tamil keyword lexicon (breathing, chest, dizziness, weakness...) with simple negation handling; a concerning note raises risk only when vitals are also abnormal.
5. **Explanation** – every prediction lists the reasons. The system never names a disease; it says "The current pattern indicates increased monitoring risk."

The **Early Deterioration Indicator** is labelled *"Prototype early-warning estimation based on simulated trends."* It does not claim a clinically validated 24–48 h prediction.

## 10. Sensor simulation
`simulator/sensor_simulator.py` (Python, used for seeding/tests) and `static/js/simulator.js` (the live bedside device). Each vital drifts toward the active mode's target with small noise. The browser generates readings so the device continues working when the server is unreachable.

## 11. Offline mechanism
- **Simulate Internet Failure**: API calls fail, readings are stored in `localStorage`, the banner shows `OFFLINE MODE` and `Offline readings pending: N`. A basic on-device threshold alarm still fires.
- **Simulate Power Failure**: `⚡ BACKUP MODE ACTIVE`, recording continues locally.
- On restore the buffer is sent to `POST /api/sync` in batches; each reading has a `client_id`, so re-sending is safe (duplicates ignored). The banner shows `Synced: N`.

## 12. Safety considerations
Simulated data only; not a medical device; no diagnosis claims; thresholds are labelled prototype logic; ML accuracy is measured on synthetic data only; login required; input validation (missing values carried forward, implausible values rejected, duplicates ignored); friendly error messages.

## 13. Future improvements
Real IoT sensors (BLE pulse oximeter, thermometer), better time-series models (LSTM/GRU, per-patient baselines), edge AI, secure cloud deployment (TLS, roles, audit logs), hospital/EHR integration (HL7 FHIR), more languages with real translation, clinical validation and regulatory review, advanced anomaly detection.

## 14. Tests
`python tests/test_backend_flow.py` runs the full API flow (risk transitions, alerts, dedupe, sync, bad input).
`python tests/test_ward_flow.py` covers equipment faults, battery drain, attendance check-in and escalation.

### Mapping to the Operation Ward Zero deliverables
| Deliverable | Where |
|---|---|
| IoT simulation | `static/js/simulator.js` (bedside device), `simulator/sensor_simulator.py` |
| Full-stack platform | Flask + SQLite + dashboard, alert workflow (`routes/`, `services.py`, `templates/`) |
| AI/ML risk (Low/Medium/High + reason, English notes) | `ai/` (RandomForest + safety rules + trend + notes) |
| Hints: equipment, attendance, offline/power, multilingual notes, 24–48 h early warning | equipment cards, attendance card, offline/backup mode, English + Tamil notes, early-deterioration indicator (prototype estimate) |
| Technical documentation | this README, `docs/architecture.md` |
| 3-minute demo video | `docs/demo-script-3min.md` |

## 15. Screenshots
See `docs/screenshots/` (dashboard, HIGH-risk alert, equipment fault + attendance, offline mode, history).
