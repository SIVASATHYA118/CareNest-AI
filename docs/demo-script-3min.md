# 3-minute demo video script (Sensor -> Platform -> AI Risk -> Alert -> Caregiver Response)

Setup: `python app.py`, open http://127.0.0.1:5000, sign in `admin` / `admin123`, click **RESET SIMULATION**. Record at 1080p.

| Time | Do | Say |
|---|---|---|
| 0:00-0:15 | Dashboard, Risk LOW | "CareNest AI turns a bedroom into a small monitored ward. Everything you see uses simulated sensors; it is a prototype, not a medical device." |
| 0:15-0:35 | Point at pipeline bar + vital cards | "A simulated bedside device streams vitals every two seconds to the Flask platform. Equipment status and caregiver attendance are tracked here too." |
| 0:35-1:05 | Click **WARNING** | "Vitals drift gradually. The AI risk engine moves LOW to MEDIUM and explains why: ML model, safety rules, trend and caregiver context." |
| 1:05-1:30 | Caregiver Notes: pick the breathing/weakness phrase, Save | "The caregiver note is used as context. It only raises risk because the vitals are also abnormal." |
| 1:30-2:00 | Click **CRITICAL** | "Risk goes HIGH, the caregiver is notified, and the early-deterioration indicator shows a prototype early-warning estimate." |
| 2:00-2:25 | Click **Acknowledge**, type a response note, **Mark as Responding**, **Resolve** | "The caregiver acknowledges, responds and resolves. Every step is time-stamped." |
| 2:25-2:45 | Back to dashboard: **O2 LOW FLOW**, then **Check in** | "Equipment faults raise their own alerts. Check-in verifies the caregiver is at the bedside; with no check-in a HIGH alert escalates." |
| 2:45-3:00 | **SIMULATE INTERNET FAILURE**, then **RESTORE** | "If the connection or power fails, the device keeps recording locally and syncs afterwards without duplicates." |

Tip: after WARNING / CRITICAL the risk takes 10-20 s to change; talk while it moves. Keep the video under 3:00.
