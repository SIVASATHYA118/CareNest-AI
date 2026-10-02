"""Tests for equipment monitoring, caregiver attendance and escalation.  Run: python tests/test_ward_flow.py"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone, timedelta

import app as A
import db as D
import services
from config import Config

c = A.app.test_client()
assert c.post('/api/login', json={'username': 'admin', 'password': 'admin123'}).status_code == 200
c.post('/api/simulation/reset')


def dash():
    return c.get('/api/dashboard').json


def eq_alerts(d, status_not='Resolved'):
    return [a for a in d['alerts'] if a['kind'] == 'equipment' and a['status'] != status_not]


d = dash()
assert [e['device'] for e in d['equipment']] == ['spo2_probe', 'o2_concentrator', 'backup_battery']
assert not any(e['fault'] for e in d['equipment']) and not eq_alerts(d)
print('1 equipment normal after reset: OK')

# oxygen concentrator fault -> exactly one HIGH equipment alert, however often the dashboard polls
assert c.post('/api/equipment/fault', json={'fault': 'o2'}).status_code == 200
for _ in range(3):
    d = dash()
al = eq_alerts(d)
assert len(al) == 1 and al[0]['risk'] == 'HIGH' and al[0]['device'] == 'o2_concentrator', al
print('2 O2 low flow -> single HIGH equipment alert:', al[0]['reason'])

# vital-sign risk logic is not blocked by an open equipment alert
assert d['latest']['risk_level'] == 'LOW'

# probe fault -> MEDIUM alert
c.post('/api/equipment/fault', json={'fault': 'probe'}); d = dash()
assert sorted(a['risk'] for a in eq_alerts(d)) == ['HIGH', 'MEDIUM']
print('3 probe disconnected -> MEDIUM alert: OK')

# equipment alerts use the normal workflow; a persisting fault is not re-alerted after resolve
aid = [a for a in eq_alerts(d) if a['device'] == 'spo2_probe'][0]['id']
assert c.post('/api/alerts/%d/acknowledge' % aid).status_code == 200
assert c.post('/api/alerts/%d/resolve' % aid, json={'response_note': 'Probe re-attached'}).status_code == 200
d = dash(); assert len(eq_alerts(d)) == 1
print('4 acknowledge/resolve works, no duplicate while fault persists: OK')

# clear, then the same fault can alert again
c.post('/api/equipment/fault', json={'fault': 'clear'}); dash()
c.post('/api/equipment/fault', json={'fault': 'probe'}); d = dash()
assert any(a['device'] == 'spo2_probe' and a['status'] == 'New' for a in d['alerts'])
assert c.post('/api/equipment/fault', json={'fault': 'nonsense'}).status_code == 400
print('5 clear + re-fault raises a fresh alert; bad input -> 400: OK')

# ---- escalation / attendance
c.post('/api/simulation/reset'); dash()
c.post('/api/equipment/fault', json={'fault': 'o2'}); dash()
Config.ESCALATION_SECONDS = 0
d = dash()
hi = [a for a in d['alerts'] if a['kind'] == 'equipment' and a['risk'] == 'HIGH'][0]
assert hi['escalated_at'], 'unattended HIGH alert should escalate'
assert any(e['event_type'] == 'escalation' for e in d['events'])
print('6 unattended HIGH alert escalated:', hi['escalated_at'])

# a caregiver who is checked in is verified -> no escalation
c.post('/api/simulation/reset'); Config.ESCALATION_SECONDS = 0
r = c.post('/api/attendance', json={'action': 'in'}); assert r.status_code == 201 and r.json['attendance']['on_site']
assert c.post('/api/attendance', json={'action': 'in'}).json['changed'] is False       # idempotent
c.post('/api/equipment/fault', json={'fault': 'o2'}); d = dash()
assert not any(a['escalated_at'] for a in d['alerts']), 'checked-in caregiver must prevent escalation'
assert d['attendance']['on_site'] and d['attendance']['last_activity']
r = c.post('/api/attendance', json={'action': 'out'}); assert r.status_code == 201 and not r.json['attendance']['on_site']
assert c.post('/api/attendance', json={'action': 'dance'}).status_code == 400
Config.ESCALATION_SECONDS = 45
print('7 check-in verified, idempotent, bad action -> 400: OK')

# ---- battery follows a simulated power failure
c.post('/api/simulation/reset'); dash()
conn = D._connect()
old = (datetime.now(timezone.utc) - timedelta(seconds=60)).strftime('%Y-%m-%dT%H:%M:%SZ')
D.log_event(conn, 'power_failure', 'test', ts=old); conn.commit(); conn.close()
d = dash(); bat = [e for e in d['equipment'] if e['device'] == 'backup_battery'][0]
assert bat['status'] == 'On battery' and bat['value'] < 30, bat
assert any(a['device'] == 'backup_battery' for a in eq_alerts(d))
print('8 power failure drains battery -> alert at %d%%: OK' % bat['value'])
conn = D._connect(); D.log_event(conn, 'power_restored', 'test'); conn.commit(); conn.close()
d = dash(); assert [e for e in d['equipment'] if e['device'] == 'backup_battery'][0]['status'] == 'Mains'
print('9 power restored -> Mains: OK')
c.post('/api/simulation/reset')
print('ALL WARD TESTS PASSED')
