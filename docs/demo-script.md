# Demo script (about 4 minutes)

Start: `python app.py`, open http://127.0.0.1:5000, sign in `admin` / `admin123`. Click **RESET SIMULATION** for a clean start.

1. **Normal** – Dashboard shows Arun Kumar (P001), **Risk: LOW**, all vitals green, pipeline "Sensor -> Platform -> AI risk -> Alert -> Caregiver" healthy.
2. **WARNING** – click WARNING. Vitals drift up over ~10 s; risk moves **LOW -> MEDIUM**, explanation appears, a *Monitoring Alert* is raised, Early Deterioration Indicator activates.
3. **Caregiver note** – Caregiver Notes page: pick the phrase "Patient is feeling weak and has difficulty breathing." (try language **Tamil**). Save. The note is used as context and the risk can rise to HIGH because vitals are abnormal too.
4. **CRITICAL** – click CRITICAL: HR ~125, SpO₂ ~89, Temp ~39, RR ~28. Risk **HIGH**, the banner shows **🚨 HIGH-RISK ALERT**, "Caregiver notified".
5. **Explain** – point to "Why?": each bullet, plus chips showing ML / safety rules / trend / caregiver context.
6. **Respond** – click **Acknowledge Alert** ("Caregiver acknowledged alert at …"), type "Checked patient and contacted healthcare provider.", click **Mark as Responding**, then **Resolve Alert**.
7. **Offline** – click NORMAL, then **SIMULATE INTERNET FAILURE**: `OFFLINE MODE`, pending count rising. Click **RESTORE INTERNET**: `Syncing…`, then `Synced: N`.
8. **Power** – **SIMULATE POWER FAILURE**: `⚡ BACKUP MODE ACTIVE`; **RESTORE POWER**: buffered readings synchronise.
9. **History** – History page: switch 1 h / 6 h / 24 h; table shows risk + explanation per reading ("synced" tag on buffered ones).
