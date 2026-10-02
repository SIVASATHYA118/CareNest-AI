import sys, uuid; import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone, timedelta
import app as A
from simulator.sensor_simulator import SensorSimulator
c = A.app.test_client()
c.post('/api/login', json={'username':'admin','password':'admin123'})
sim = SensorSimulator(seed=3)
def tick(n, mode, rate=0.3, t0=None):
    sim.set_mode(mode); last=None
    for i in range(n):
        r = sim.step(rate); r['client_id']=str(uuid.uuid4())
        res = c.post('/api/vitals', json=r).json
        last = res
    return last
r = tick(20,'NORMAL'); print('NORMAL ->', r['risk']['level'], r['risk']['reasons'])
seen=set()
for i in range(12):
    sim.set_mode('WARNING'); x=sim.step(0.3); x['client_id']=str(uuid.uuid4()); res=c.post('/api/vitals',json=x).json; seen.add(res['risk']['level'])
print('WARNING levels seen during ramp+hold:', seen)
for i in range(25):
    x=sim.step(0.3); x['client_id']=str(uuid.uuid4()); res=c.post('/api/vitals',json=x).json
print('WARNING steady ->', res['risk']['level'], res['risk']['ml_level'], res['risk']['rule_level'], res['risk']['reasons'], res['risk']['early_warning']['message'])
print('alerts:', [(a['alert_code'],a['risk'],a['status']) for a in c.get('/api/alerts').json['alerts']])
print(c.post('/api/caregiver-note', json={'note':'Patient is feeling weak and has difficulty breathing.','language':'en'}).json)
x=sim.step(0.3); x['client_id']=str(uuid.uuid4()); res=c.post('/api/vitals',json=x).json; print('after note ->', res['risk']['level'], res['risk']['reasons'])
sim.set_mode('CRITICAL')
for i in range(6):
    x=sim.step(0.35); x['client_id']=str(uuid.uuid4()); res=c.post('/api/vitals',json=x).json; print(' crit tick', x['heart_rate'], x['spo2'], res['risk']['level'], res.get('alert_id'))
print(res['risk']['reasons'])
al = c.get('/api/alerts?status=open').json['alerts']; print('open alerts', [(a['alert_code'],a['risk'],a['status']) for a in al])
hid = [a for a in al if a['risk']=='HIGH'][0]['id']
print(c.post(f'/api/alerts/{hid}/acknowledge', json={}).json['alert']['status'])
print(c.post('/api/caregiver-response', json={'alert_id':hid,'response_note':'Checked patient and contacted healthcare provider.'}).status_code)
print(c.post(f'/api/alerts/{hid}/responding', json={}).json['alert']['status'])
print(c.post(f'/api/alerts/{hid}/resolve', json={'response_note':'done'}).json['alert']['status'])
print('bad transition ->', c.post(f'/api/alerts/{hid}/acknowledge', json={}).status_code)
# no re-alert while still critical
for i in range(4):
    x=sim.step(0.35); x['client_id']=str(uuid.uuid4()); res=c.post('/api/vitals',json=x).json
print('after resolve, new alert id (should be None):', res.get('alert_id'))
tick(25,'NORMAL',0.4)
print('recovered:', c.get('/api/risk/current').json['risk']['level'])
# validation / resilience
print('missing values ->', c.post('/api/vitals', json={'heart_rate':80,'client_id':'m1'}).status_code, c.post('/api/vitals', json={'heart_rate':80,'client_id':'m1'}).json['duplicate'])
print('garbage ->', c.post('/api/vitals', json={'heart_rate':'abc'}).status_code, c.post('/api/vitals', json={'heart_rate':999}).status_code, c.post('/api/vitals', data='xx').status_code, c.post('/api/vitals', json={}).status_code)
# offline sync
now=datetime.now(timezone.utc); buf=[]
for i in range(7):
    r=sim.step(0.3); r.update(client_id='off-%d'%i, timestamp=(now-timedelta(seconds=(7-i)*2)).isoformat().replace('+00:00','Z')); buf.append(r)
print('sync', c.post('/api/sync', json={'readings':buf}).json, c.post('/api/sync', json={'readings':buf}).json)
print('hist', c.get('/api/vitals/history?hours=24').json['total'], len(c.get('/api/vitals/history?hours=1').json['readings']))
print(c.post('/api/risk/analyze', json={'heart_rate':125,'spo2':89,'temperature':39,'respiratory_rate':28}).json['risk']['level'])
print(c.get('/api/dashboard').status_code, c.get('/api/settings/info').status_code, c.get('/api/patient/P001').json)
print(c.post('/api/simulation/mode', json={'mode':'critical'}).json['ok'])
