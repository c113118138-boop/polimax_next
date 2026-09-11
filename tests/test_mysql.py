"""Runs only against the disposable localhost:13316 MySQL server, never env's DB."""
import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
admin = create_engine('mysql+pymysql://root@127.0.0.1:13316', hide_parameters=True)
schema = 'polimax_test_' + os.urandom(6).hex()
with admin.begin() as c:
    c.exec_driver_sql(f'CREATE DATABASE `{schema}` CHARACTER SET utf8mb4')
    c.exec_driver_sql(f'USE `{schema}`')
    for filename in ('tests/legacy-schema.sql',):
        sql = '\n'.join(line for line in (ROOT/filename).read_text().splitlines() if not line.startswith('--'))
        for statement in sql.split(';'):
            if statement.strip(): c.exec_driver_sql(statement)
    c.exec_driver_sql("CREATE USER IF NOT EXISTS 'polimax_test'@'127.0.0.1' IDENTIFIED BY 'isolated-test'")
    c.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{schema}`.* TO 'polimax_test'@'127.0.0.1'")
    c.exec_driver_sql("INSERT INTO CarList (license_plate,car_type,owner,purchase_date,amount,passengers,equipment) VALUES ('REAL-001','Toyota','王小明','2025-01-01','100','5','備胎')")
    c.exec_driver_sql("INSERT INTO formio_responses (form_id,reason,place,start,end,plate,employees,applicant_ID) VALUES ('11509A0099','工案','舊案件','2026-09-12 09:00:00','2026-09-12 12:00:00','REAL-001','王小明,李小華','old-user')")
    c.exec_driver_sql("INSERT INTO form_flows (form_id,status) VALUES ('11509A0099','PENDING')")

folder = tempfile.TemporaryDirectory(prefix='polimax-mysql-files-')
legacy_root=Path(folder.name)/'回應'
(legacy_root/'主表').mkdir(parents=True)
(legacy_root/'主表'/'11509A0099.json').write_text(json.dumps({'content':{'Form_Type':'主表','Requirement_select':'工案','applicantID':'old-user','RequireOption_Memo':'舊 JSON 備註','usageTimeRegistration':['王小明','李小華'],'Reason_Case_Grid':[{'Case_ID_and_name':'既有完整案件','Reason_Case_city':'新竹市','reasonCaseGridSelect':'東區'}]}},ensure_ascii=False))
(legacy_root/'發車紀錄表').mkdir()
(legacy_root/'發車紀錄表'/'11509B0040.json').write_text(json.dumps({'Form_Type':'發車紀錄表','parent_form_id':'11509A0099','panel6':'REAL-001','panelTable11Text2':'王小明','panelTableText':'100','panelTable9':True,'page1Text':'150','page2':True,'panelTableRadio':'異狀備註','panelTable12':'需清潔'},ensure_ascii=False))
os.environ.update(AMS_AUTH_MODE='test',PREVIEW_LOGIN_ENABLED='1',AMS_DATABASE_MODE='mysql',MYSQL_HOST='127.0.0.1',MYSQL_PORT='13316',
    MYSQL_DATABASE=schema,MYSQL_USER='polimax_test',MYSQL_PASSWORD='isolated-test',PREVIEW_DATA_DIR=folder.name,AMS_LEGACY_RESPONSES_DIR=folder.name+'/回應')
sys.path.insert(0,str(ROOT/'backend'))
import app as a
from fastapi.testclient import TestClient
from legacy_store import CHECKS_B,CHECKS_C

class MySQLContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(a.app); cls.client.__enter__()
        r=cls.client.post('/api/auth/login',json={'role':'admin'},headers={'x-ams-client':'preview'})
        assert r.status_code == 200, r.text
    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None,None,None)
    def request(self, method, path, body=None, status=200):
        r=self.client.request(method,'/api'+path,json=body,headers={'x-ams-client':'preview'})
        self.assertEqual(r.status_code,status,r.text)
        return r.json()
    def test_mysql_roundtrip_and_atomicity(self):
        self.assertEqual(self.request('GET','/health')['database'],'MySQL')
        cars=[r for r in self.request('GET','/resources') if r['kind']=='vehicle'];self.assertEqual(len(cars),1)
        car=cars[0];self.assertEqual(car['label'],'REAL-001');self.assertNotIn('_legacy_id',car)
        old=self.request('GET','/bookings/11509A0099')
        self.assertEqual(old['content']['employees'],['王小明','李小華'])
        self.assertEqual(old['slots'][0]['resource_id'],car['id'])
        self.assertEqual(old['content']['notes'],'舊 JSON 備註')
        self.assertEqual(old['content']['details'][0]['name'],'既有完整案件')
        old_stage=self.request('GET','/stages/11509B0040')
        self.assertEqual(old_stage['content']['start']['driver'],'王小明')
        self.assertEqual(old_stage['content']['arrival']['mileage'],'150')
        self.assertEqual(old_stage['content']['start']['interior'],'異狀')
        data={k:v for k,v in car.items() if k not in ('id','kind','label')}
        data.update(notes='MySQL write',_legacy_id=99999)
        self.request('PUT',f"/resources/{car['id']}",{'kind':'vehicle','label':car['label'],'data':data})
        with a.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT notes FROM CarList WHERE ID=1')).scalar(),'MySQL write')
        with a.engine.begin() as c:
            c.execute(text("UPDATE CarList SET holder='外部修改' WHERE ID=1"))
        self.assertEqual(self.request('GET','/resources')[0]['holder'],'外部修改')
        slot={'resource_id':car['id'],'start':'2026-09-12T10:00:00+08:00','end':'2026-09-12T11:00:00+08:00'}
        body={'kind':'A','content':{'title':'完整新表單','reason':'工案','employees':['王小明'],'total_people':1,
            'details':[{'name':'完整案件','city':'新竹市','district':'東區'}],'slots':[slot],'notes':'額外欄位'}}
        self.request('POST','/bookings',body,409)
        slot.update(start='2026-09-13T10:00:00+08:00',end='2026-09-13T11:00:00+08:00')
        booking=self.request('POST','/bookings',body)
        self.assertGreater(int(booking['id'][-4:]),99)
        with a.engine.connect() as c:
            row=c.execute(text('SELECT * FROM formio_responses WHERE form_id=:id'),{'id':booking['id']}).mappings().one()
            self.assertEqual(row['place'],'新竹市東區');self.assertEqual(row['reason'],'工案 - 完整案件');self.assertEqual(row['plate'],'REAL-001')
        self.assertEqual(self.request('GET','/bookings/'+booking['id'])['content']['notes'],'額外欄位')
        replacement=self.request('PUT','/bookings/'+booking['id'],{**body,'revision':booking['revision']})
        with a.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT is_deleted FROM formio_responses WHERE form_id=:id'),{'id':booking['id']}).scalar(),1)
        record=self.request('POST',f"/resources/{car['id']}/records",{'category':'insurance','data':{'company':'測試保險','expiry':'2027-01-01'}})
        self.request('PUT',f"/records/{record['id']}",{'category':'insurance','data':{'company':'更新保險','expiry':'2028-01-01'}})
        with a.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT company FROM insurance_records')).scalar(),'更新保險')
        # A value valid for extension storage but too long for the original table
        # must roll back BOTH tables, including the previously flushed extension.
        with a.engine.connect() as c:
            before=c.execute(text('SHOW TABLES')).scalars().all()
        self.request('POST','/resources',{'kind':'vehicle','label':'X'*30,'data':data},503)
        with a.engine.connect() as c:
            self.assertEqual(c.execute(text('SHOW TABLES')).scalars().all(),before)
            self.assertFalse(any(name.startswith('ams_preview_') for name in before))
            self.assertEqual(c.execute(text('SELECT count(*) FROM CarList')).scalar(),1)
        self.request('DELETE','/bookings/'+replacement['id'])
        self.request('POST','/bookings',body)
        self.request('DELETE',f"/records/{record['id']}")
        with a.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT isdelete FROM insurance_records')).scalar(),1)
        equipment=self.request('POST','/resources',{'kind':'equipment','label':'EQ-LIVE','data':{'name':'量測儀','location':'A1','state':'列管','quantity':1,'accessories':[{'name':'主機','quantity':1}]}})
        self.assertEqual(next(r for r in self.request('GET','/resources') if r['id']==equipment['id'])['accessories'][0]['name'],'主機')
        for category,data in [('cost',{'type':'maintenance','reason':'保養','amount':20}),('maintenance',{'type':'inspection','date':'2026-09-10'}),('garage',{'notes':'車庫'}),('manager',{'name':'王小明'})]:
            self.request('POST',f"/resources/{car['id']}/records",{'category':category,'data':data})
        self.assertEqual(len(self.request('GET',f"/resources/{car['id']}/records")),4)
        with a.engine.begin() as c:
            c.execute(text("INSERT INTO CarList (license_plate,car_type) VALUES ('EXTERNAL-002','外部新增')"))
        first=next(r for r in self.request('GET','/resources') if r['label']=='EXTERNAL-002')
        second=next(r for r in self.request('GET','/resources') if r['label']=='EXTERNAL-002')
        self.assertEqual(first['id'],second['id'])
        # External edits change the optimistic revision without a shadow table.
        with a.engine.begin() as c:
            c.execute(text("UPDATE formio_responses SET employees='外部員工' WHERE form_id='11509A0099'"))
        changed=self.request('GET','/bookings/11509A0099')
        again=self.request('GET','/bookings/11509A0099')
        self.assertEqual(changed['revision'],again['revision'])
        self.assertEqual(changed['content']['employees'],['外部員工'])
        live=next(b for b in self.request('GET','/bookings') if b['content'].get('notes')=='額外欄位')
        for index,mileage in enumerate((100,110,110,120)):
            stage={'driver':'王小明','employees':['王小明'],'place':'實際地點','mileage':mileage,'confirmed':True,
                'checks':CHECKS_B if index<2 else CHECKS_C,
                'tires':'正常','interior':'正常','exterior':'正常','equipment':'正常'}
            live=self.request('POST','/bookings/'+live['id']+'/advance',{'expected_status':live['status'],'revision':live['revision'],'content':stage})
        with a.engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT status FROM form_flows WHERE form_id=:id'),{'id':live['id']}).scalar(),'RETURN_ARRIVED')
        self.assertEqual(len(self.request('GET','/bookings/'+live['id'])['stages']),2)
        from concurrent.futures import ThreadPoolExecutor
        import copy
        concurrent=copy.deepcopy(body)
        concurrent['content']['slots'][0].update(start='2026-09-20T10:00:00+08:00',end='2026-09-20T11:00:00+08:00')
        def reserve(_):
            return self.client.post('/api/bookings',json=concurrent,headers={'x-ams-client':'preview'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(reserve,range(2))),[200,409])
        # Existing file-service contract, using a mock: no real file is uploaded.
        import httpx
        from unittest.mock import patch
        original_client=httpx.AsyncClient
        transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'file_uuid':'legacy-file-123'}))
        with patch('legacy_api.httpx.AsyncClient',lambda **kwargs:original_client(transport=transport,**kwargs)):
            upload=self.client.post('/api/files',content=b'isolated-test',headers={'x-ams-client':'preview','x-file-name':'note.txt','content-type':'text/plain'})
        self.assertEqual(upload.status_code,200,upload.text)
        self.assertEqual(upload.json()['id'],'legacy-file-123')
        response=self.client.get('/api/files/legacy-file-123',follow_redirects=False)
        self.assertEqual(response.status_code,307)
        self.assertTrue(response.headers['location'].endswith('/file/legacy-file-123'))
        attached=self.request('POST',f"/resources/{car['id']}/records",{'category':'garage','data':{'notes':'附件相容','attachments':[upload.json()]}})
        with a.engine.connect() as c:
            value=c.execute(text('SELECT attachment_uuids FROM garage_files WHERE sn=:sn'),{'sn':attached['id']//10}).scalar()
            self.assertEqual(json.loads(value)[0]['uuid'],'legacy-file-123')
        # A legacy D row may contain several numbered areas inside parentheses.
        with a.engine.begin() as c:
            c.execute(text("INSERT INTO formio_responses (form_id,reason,place,start,end,plate,employees,applicant_ID) VALUES ('11509D0040','工作間租用','批覆區(1-1, 1-2)','2026-09-22 09:00:00','2026-09-22 12:00:00','','','old-user')"))
        room=next(r for r in self.request('GET','/resources') if r['kind']=='room' and r['label']=='1-1')
        room_body={'kind':'D','content':{'slots':[{'resource_id':room['id'],'start':'2026-09-22T10:00:00+08:00','end':'2026-09-22T11:00:00+08:00'}]}}
        self.request('POST','/bookings',room_body,409)
        self.assertEqual(len(self.request('GET','/bookings/11509D0040')['slots']),2)
        equipment_body=copy.deepcopy(body);equipment_body['kind']='E';equipment_body['content']['reason']='開案'
        equipment_body['content']['slots'][0]['resource_id']=equipment['id']
        self.request('POST','/bookings',equipment_body)
        # Exercise a separate connection after all writes and prove complete JSON persists.
        a.engine.dispose()
        self.assertTrue(any(b['content'].get('notes')=='額外欄位' for b in self.request('GET','/bookings')))

if __name__=='__main__':
    try:
        result = unittest.main(verbosity=2,exit=False).result
    finally:
        a.engine.dispose()
        with admin.begin() as c: c.exec_driver_sql(f'DROP DATABASE `{schema}`')
        admin.dispose();folder.cleanup()
    sys.exit(0 if result.wasSuccessful() else 1)
