"""Contract tests run in a disposable database, never the preview database."""
import copy
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

TEST_DATA=tempfile.TemporaryDirectory(prefix='polimax-contract-')
os.environ['PREVIEW_DATA_DIR']=TEST_DATA.name
os.environ['AMS_DATABASE_MODE']='demo'
os.environ.pop('PREVIEW_DATABASE_URL',None)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import app as a
import integrations as x
import permissions as p
from fastapi.testclient import TestClient
from sqlalchemy import select
HEADERS={'X-AMS-Client':'preview'}

class Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(a.app);cls.client.__enter__()
        cls.login('admin')
        cls.resources=cls.client.get('/api/resources').json()
        cls.car=next(r for r in cls.resources if r['kind']=='vehicle')
        cls.car2=[r for r in cls.resources if r['kind']=='vehicle'][1]
        cls.room=[r for r in cls.resources if r['kind']=='room']
        cls.equip=next(r for r in cls.resources if r['kind']=='equipment')
        cls.day=a.now().replace(hour=9,minute=0,second=0,microsecond=0)+timedelta(days=100)
        cls.counter=0
    @classmethod
    def tearDownClass(cls):cls.client.__exit__(None,None,None);a.engine.dispose();TEST_DATA.cleanup()
    @classmethod
    def login(cls,role):
        r=cls.client.post('/api/auth/login',json={'role':role},headers=HEADERS)
        assert r.status_code==200,r.text
        return r.json()
    def setUp(self):self.login('admin')
    def body(self,kind='A',resource=None,reason='工案',day=None):
        Contracts.counter+=1
        day=day or self.day+timedelta(days=Contracts.counter)
        rid=resource or {'A':self.car['id'],'D':self.room[0]['id'],'E':self.equip['id']}[kind]
        return {'kind':kind,'content':{'title':'測試申請','reason':reason if kind=='A' else '作業區租用' if kind=='D' else '開案','total_people':2,'employees':['林品安','陳予晴'],'details':[{'name':'DEMO 案件','city':'新竹市','district':'東區','leader':'林品安','sales':['陳予晴'],'notes':'明細備註'}],'slots':[{'resource_id':rid,'start':a.iso(day),'end':a.iso(day+timedelta(hours=1))}],'notes':'機密備註','purposes':[]}}
    def post(self,path,body=None,status=200):
        r=self.client.post(path,json=body,headers=HEADERS);self.assertEqual(r.status_code,status,r.text);return r.json()
    def put(self,path,body,status=200):
        r=self.client.put(path,json=body,headers=HEADERS);self.assertEqual(r.status_code,status,r.text);return r.json()
    def create(self,body=None):return self.post('/api/bookings',body or self.body())
    def stage(self,kind='B',mileage=100):
        return {'driver':'林品安','codriver':'陳予晴','employees':['林品安','陳予晴'],'place':'測試廠區','mileage':mileage,'confirmed':True,'checks':a.stages.CHECKS_B if kind=='B' else a.stages.CHECKS_C,'tires':'正常','interior':'正常','exterior':'正常','equipment':'正常','notes':'階段備註'}
    def advance(self,b,data,status=200):return self.post('/api/bookings/'+b['id']+'/advance',{'expected_status':b['status'],'revision':b['revision'],'content':data},status)
    def test_auth_policies(self):
        self.post('/api/auth/logout')
        self.assertEqual(self.client.get('/api/bookings').status_code,401)
        self.login('draft');self.post('/api/bookings',self.body(),403)
        self.login('viewer');self.assertEqual(self.client.get('/api/auth/me').json()['permissions']['ui']['calendar.options.holidayToggle'],'Hidden')
        forms=self.client.get('/api/bookings').json()
        self.assertNotIn('notes',json.dumps(forms))
        self.post('/api/bookings',self.body(),403)
        self.login('borrower');b=self.body();b['content']['applicant']='冒用員工';self.post('/api/bookings',b,403)
        b=self.create();self.assertEqual(self.client.delete('/api/bookings/'+b['id'],headers=HEADERS).status_code,403)
    def test_policy_snapshots_and_multirole(self):
        policy=p.default_policy();policy['version']=2
        policy['roles']['extra']={'Lending_form':{'levels':{'0':{'submit':1}}}}
        policy['user_roles']['demo-draft']=['draft','extra']
        path=Path(TEST_DATA.name)/'policy.json';path.write_text(json.dumps(policy));os.environ['AMS_POLICY_FILE']=str(path)
        self.post('/api/permissions/sync');self.login('draft');self.assertTrue(self.client.get('/api/auth/me').json()['permissions']['forms']['Lending_form']['submit'])
        self.login('admin');path.unlink();self.post('/api/permissions/sync',status=503)
        self.assertEqual(self.client.get('/api/permissions').json()['version'],2)
        policy['version']=3;policy['user_roles']['demo-draft']=['draft'];path.write_text(json.dumps(policy));self.post('/api/permissions/sync');os.environ.pop('AMS_POLICY_FILE')
    def test_booking_reasons_and_pairing(self):
        for reason in a.REASONS:
            b=self.body(reason=reason)
            if reason=='材料送貨':b['content']['details'][0]['name']=''
            f=self.create(b);self.assertEqual(f['content']['reason'],reason)
        b=self.body();slot=b['content']['slots'][0]
        b['content']['slots']=[{**slot,'start':a.iso(self.day+timedelta(days=200,hours=i*2)),'end':a.iso(self.day+timedelta(days=200,hours=i*2+1))} for i in range(3)]
        self.assertEqual(len(self.create(b)['slots']),3)
        b=self.body();b['content']['details']*=2;b['content']['slots']*=3;self.post('/api/bookings',b,422)
    def test_booking_boundaries(self):
        b=self.body();self.create(b);self.post('/api/bookings',b,409)
        adjacent=copy.deepcopy(b);adjacent['content']['slots'][0]['start']=b['content']['slots'][0]['end'];adjacent['content']['slots'][0]['end']=a.iso(a.parse(b['content']['slots'][0]['end'])+timedelta(hours=1));self.post('/api/bookings',adjacent,409)
        other=copy.deepcopy(b);other['content']['slots'][0]['resource_id']=self.car2['id'];self.create(other)
        b=self.body();b['content']['slots']*=2;self.post('/api/bookings',b,409)
        b=self.body();b['content']['slots'][0]['end']=b['content']['slots'][0]['start'];self.create(b)
        b=self.body();b['content']['slots'][0]['end']=a.iso(self.day);self.post('/api/bookings',b,422)
    def test_versions_delete_release(self):
        body=self.body();f=self.create(body)
        edited=self.put('/api/bookings/'+f['id'],{**body,'revision':f['revision']})
        self.assertNotEqual(edited['id'],f['id']);self.assertEqual(edited['previous_id'],f['id'])
        detail=self.client.get('/api/bookings/'+edited['id']).json();self.assertEqual(detail['previous_version']['id'],f['id'])
        self.assertEqual(self.client.delete('/api/bookings/'+edited['id'],headers=HEADERS).status_code,200)
        self.create(body)
    def test_concurrent_reservation(self):
        body=self.body()
        token=self.client.cookies.get('ams_preview_session')
        def submit(_):
            with TestClient(a.app) as c:
                c.cookies.set('ams_preview_session',token)
                return c.post('/api/bookings',json=body,headers=HEADERS).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(submit,range(2)))
        self.assertEqual(sorted(results),[200,409])
    def test_rooms_and_equipment(self):
        day=self.day+timedelta(days=300)
        for room in self.room[:3]:self.create(self.body('D',room['id'],day=day))
        self.post('/api/bookings',self.body('D',self.room[0]['id'],day=day),409)
        b=self.body('D');b['content']['slots'][0]['end']=b['content']['slots'][0]['start'];self.post('/api/bookings',b,422)
        b=self.body('E');f=self.create(b);self.post('/api/bookings',b,409)
        f=self.put('/api/bookings/'+f['id'],{**b,'revision':f['revision']});self.assertIn('E',f['id'])
        self.advance(f,self.stage(),409)
        off=self.post('/api/resources',{'kind':'equipment','data':{'name':'停用設備','location':'X','state':'停用'},'label':''})
        self.post('/api/bookings',self.body('E',off['id']),422)
    def test_field_rules_recursive_and_cold_start(self):
        with a.Session.begin() as db:
            row=db.scalar(select(p.Policy).where(p.Policy.active==1));original=row.payload
            policy=json.loads(original)
            policy['roles']['borrower']['Lending_form']['fields']['notes']={'read':1,'write':0}
            row.payload=json.dumps(policy)
        try:
            self.login('borrower');body=self.body();self.post('/api/bookings',body,403)
            body['content'].pop('notes');self.post('/api/bookings',body,403)
            body['content']['details'][0].pop('notes');self.create(body)
            check=self.post('/api/permissions/check',{'checks':[{'type':'form','module':'AMS','doctype':'Lending_form','ops':['submit']}]})
            self.assertTrue(check['results'][0]['result']['allow'])
        finally:
            with a.Session.begin() as db:
                db.scalar(select(p.Policy).where(p.Policy.active==1)).payload=original
            self.login('admin')
        with a.Session.begin() as db:
            row=db.scalar(select(p.Policy).where(p.Policy.active==1));version=row.version;row.active=0
        os.environ['AMS_POLICY_FILE']='/missing-policy-source.json'
        try:self.assertEqual(self.client.get('/api/bookings').status_code,403)
        finally:
            os.environ.pop('AMS_POLICY_FILE')
            with a.Session.begin() as db:db.get(p.Policy,version).active=1
    def test_full_flow_revisions(self):
        b=self.create();bad=self.stage();bad['checks']=[];self.advance(b,bad,422)
        bad=self.stage();bad['codriver']='';self.advance(b,bad,422)
        original=b;b=self.advance(b,self.stage(mileage=100));self.advance(original,self.stage(),409)
        b=self.advance(b,{'mileage':120,'confirmed':True,'anomalies':[]})
        b=self.advance(b,self.stage('C',130))
        self.advance(b,{'mileage':129,'confirmed':True},422)
        b=self.advance(b,{'mileage':155,'confirmed':True});self.assertEqual(b['status'],'RETURN_ARRIVED')
        detail=self.client.get('/api/bookings/'+b['id']).json();stages={s['kind']:s for s in detail['stages']}
        self.assertEqual(len(stages),2);self.assertEqual(stages['B']['parent_id'],b['id'])
        self.assertEqual(float(stages['C']['content']['arrival']['mileage'])-float(stages['B']['content']['start']['mileage']),55)
        s=stages['B'];content=copy.deepcopy(s['content']);content['start']['notes']='修正備註'
        updated=self.put('/api/stages/'+s['id'],{'revision':s['revision'],'content':content});self.assertEqual(updated['id'],s['id'])
        self.assertEqual(self.client.get('/api/bookings/'+b['id']).json()['status'],'RETURN_ARRIVED')
        self.assertTrue(self.client.get('/api/stages/'+s['id']).json()['versions'])
        self.assertEqual(self.client.delete('/api/stages/'+s['id'],headers=HEADERS).status_code,200)
        self.assertTrue(self.client.get('/api/bookings/'+b['id']).json()['incomplete'])
    def test_assets_records_files(self):
        for field in ['model','owner','purchase_date','amount','passengers']:
            data={'model':'TEST','owner':'測試','purchase_date':'2026-09-10','amount':1,'passengers':1};data.pop(field)
            self.post('/api/resources',{'kind':'vehicle','label':'INVALID-'+field,'data':data},422)
        headers={**HEADERS,'X-File-Name':'note.txt','Content-Type':'text/plain'}
        upload=self.client.post('/api/files',content=b'persisted attachment',headers=headers);self.assertEqual(upload.status_code,200)
        file=upload.json();self.assertEqual(self.client.get('/api/files/'+file['id']).content,b'persisted attachment')
        for category,data in [('insurance',{'company':'測試','expiry':'2026-09-10','policy_files':[file],'claim_files':[file]}),('cost',{'type':'保養','reason':'測試','amount':10,'attachments':[file]}),('maintenance',{'type':'驗車','date':'2026-09-10'}),('garage',{'notes':'廠商'}),('manager',{'name':'測試管理人'})]:
            r=self.post(f'/api/resources/{self.car["id"]}/records',{'category':category,'data':data})
            self.put('/api/records/'+str(r['id']),{'category':category,'data':{**data,'notes':'修訂'}})
            records=self.client.get(f'/api/resources/{self.car["id"]}/records').json();self.assertIn(r['id'],[v['id'] for v in records])
            self.assertEqual(self.client.delete('/api/records/'+str(r['id']),headers=HEADERS).status_code,200)
    def test_reports_maps_scans(self):
        b=self.client.get('/api/beacons').json()[0];self.assertEqual(b['id'],'000b');self.assertEqual(self.client.get('/api/findmy/000b').json()['beacon']['major'],11)
        p1=self.client.get('/api/positions').json();p2=self.client.get('/api/positions').json();self.assertEqual(p1,p2)
        car=next(r for r in p1 if r['resource_id']==self.car['id']);self.assertNotEqual(car['time'],car['updated_at']);self.assertTrue(x.valid(car['lat'],car['lng']))
        self.post('/api/beacons',{'id':'00ff','owner':self.car['client_id'],'programmed':'y'})
        self.post('/api/reports/import',{'reports':[{'source':'findmy','report_id':'car-source','major':255,'lat':25,'lng':121,'record_time':a.iso(a.now()+timedelta(days=1)),'created_at':a.iso(a.now())}]})
        latest=next(v for v in self.client.get('/api/positions').json() if v['resource_id']==self.car['id']);self.assertEqual(latest['source'],'FindMy');self.assertEqual(latest['lat'],car['lat'])
        today=a.now().replace(hour=0,minute=0,second=0,microsecond=0)
        trajectory=self.client.get(f'/api/trajectory/{self.car["id"]}',params={'start':a.iso(today),'end':a.iso(today+timedelta(days=1))}).json()
        self.assertGreater(trajectory['total'],1000);self.assertLessEqual(len(trajectory['points']),1001);self.assertEqual(trajectory['points'][0]['type'],'start');self.assertEqual(trajectory['points'][-1]['type'],'end')
        exact=self.client.get(f'/api/trajectory/{self.car["id"]}',params={'start':a.iso(today+timedelta(hours=9)),'end':a.iso(today+timedelta(hours=9,seconds=5))}).json();self.assertEqual(len(exact['points']),1)
        report={'source':'scan','report_id':'boundary','client_id':'TEST-STATION','major':99,'record_time':a.iso(a.now()-timedelta(seconds=300)),'created_at':a.iso(a.now()),'rssi':-80,'power':66}
        self.assertEqual(self.post('/api/reports/import',{'reports':[report]})['inserted'],1)
        self.assertEqual(self.post('/api/reports/import',{'reports':[report]})['duplicates'],1)
        scan=self.client.get('/api/scans',params={'station':'TEST-STATION'}).json()[0];self.assertEqual(scan['status'],'offline');self.assertEqual(scan['name'],'未知設備')
    def test_notifications_failure_dedup(self):
        with a.Session.begin() as db:
            for n in db.scalars(select(x.Notification)):db.delete(n)
        os.environ['AMS_NOTIFY_FAIL']='1'
        first=self.post('/api/notifications/check');self.assertGreaterEqual(first['failed'],4)
        os.environ.pop('AMS_NOTIFY_FAIL')
        success=self.post('/api/notifications/check');self.assertEqual(success['sent'],first['failed'])
        self.assertEqual(self.post('/api/notifications/check')['sent'],0)
        rows=self.client.get('/api/notifications').json();self.assertTrue(all(set(n['content'])=={'CompanyTax','UserID','Title','Content','Service'} for n in rows))
    def test_restart_persistence(self):
        f=self.create()
        with TestClient(a.app) as other:
            other.cookies.set('ams_preview_session',self.client.cookies.get('ams_preview_session'))
            self.assertEqual(other.get('/api/bookings/'+f['id']).json()['id'],f['id'])

if __name__=='__main__':unittest.main(verbosity=2)
