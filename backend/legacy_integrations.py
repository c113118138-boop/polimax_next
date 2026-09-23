"""Read the existing tracking tables; keep external import/notification jobs separate."""
from datetime import timedelta
from gps_history import trajectory_rows
import json
import os
from pathlib import Path
from fastapi import Depends
from sqlalchemy import MetaData,Table,select,insert,update,delete,func,inspect
from legacy_store import fail,iso,parse,now

def install(app,store,current,check):
    def table(repo,name):
        if name not in repo.t:
            if name not in inspect(repo.c).get_table_names():return None
            repo.t[name]=Table(name,MetaData(),autoload_with=repo.c)
        return repo.t[name]
    def point(row):
        if not row:return None
        lat=row.get('latitude');lng=row.get('longitude')
        return {'lat':float(lat) if lat is not None else None,'lng':float(lng) if lng is not None else None,
            'time':iso(row.get('record_time') or row.get('timestamp')),'record_time':iso(row.get('record_time') or row.get('timestamp')),'created_at':iso(row.get('created_at') or row.get('timestamp'))}
    def beacons(repo):
        t=table(repo,'BeaconList')
        if t is None:return []
        result=[]
        for row in repo.c.execute(select(t)).mappings():
            try:major=int(row['id'],16)
            except ValueError:major=None
            result.append({'id':row['id'],'major':major,'owner':row['owner'] or '', 'programmed':row['programmed'] or 'n','ble_mac':row['BLEMacAddr'] or ''})
        return result
    @app.get('/api/beacons')
    def list_beacons(user=Depends(current)):
        check(user,'BeaconList','read')
        with store().session() as repo:return beacons(repo)
    @app.post('/api/beacons')
    def create_beacon(body:dict,user=Depends(current)):
        check(user,'BeaconList','create')
        with store().session(True) as repo:
            t=table(repo,'BeaconList');ident=str(body.get('id','')).lower()
            try:valid=len(ident)==4 and 0<=int(ident,16)<=65535
            except ValueError:valid=False
            if not valid or not body.get('owner'):fail('請填寫四位十六進位 ID 與名稱')
            if repo.c.execute(select(t.c.id).where(t.c.id==ident)).first():fail('Beacon 已存在',409)
            repo.c.execute(insert(t).values(id=ident,owner=body['owner'],programmed=body.get('programmed','n'),BLEMacAddr=body.get('ble_mac','')))
        return {'id':ident}
    @app.put('/api/beacons/{ident}')
    def edit_beacon(ident:str,body:dict,user=Depends(current)):
        check(user,'BeaconList','write')
        if body.get('id',ident)!=ident:fail('Beacon ID 不可修改')
        if not body.get('owner') or body.get('programmed') not in ('y','n'):fail('請填寫名稱與燒錄狀態')
        with store().session(True) as repo:
            t=table(repo,'BeaconList')
            if not repo.c.execute(select(t.c.id).where(t.c.id==ident)).first():fail('找不到 Beacon',404)
            repo.c.execute(update(t).where(t.c.id==ident).values(owner=body['owner'],programmed=body['programmed'],BLEMacAddr=body.get('ble_mac','')))
        return {'ok':True}
    @app.delete('/api/beacons/{ident}')
    def delete_beacon(ident:str,user=Depends(current)):
        check(user,'BeaconList','delete')
        with store().session(True) as repo:
            t=table(repo,'BeaconList');repo.c.execute(delete(t).where(t.c.id==ident))
        return {'ok':True}
    @app.get('/api/positions')
    def positions(user=Depends(current)):
        check(user,'CarUpdate','read');result=[]
        with store().session() as repo:
            t=table(repo,'gps_readings')
            for r in repo.resources():
                if r['kind']!='vehicle':continue
                row=None
                if t is not None and r.get('client_id'):
                    row=repo.c.execute(select(t).where(t.c.client_id==r['client_id']).order_by(t.c.record_time.desc(),t.c.id.desc()).limit(1)).mappings().first()
                result.append({'resource_id':r['id'],'label':r['label'],'source':'gps','position_source':'gps','test_data':False,
                    'lat':None,'lng':None,**(point(row) or {}),'latest_report_time':iso(row.get('created_at')) if row else None,'missing':not bool(row)})
        return result
    @app.get('/api/trajectory/{rid}')
    def trajectory(rid:int,start:str,end:str,limit:int=1000,user=Depends(current)):
        check(user,'carMap','read');s,e=parse(start),parse(end)
        if s>=e:fail('結束時間必須晚於開始時間')
        if e-s>timedelta(days=90):fail('單次最多查詢 90 天')
        s=max(s,now()-timedelta(days=90))
        if s>=e:return {'points':[],'count':0,'total':0}
        with store().session() as repo:
            r=repo.resource(rid);t=table(repo,'gps_readings')
            if t is None or not r.get('client_id'):return {'points':[],'count':0,'total':0}
            rows,total=trajectory_rows(repo.c,t,r['client_id'],s,e,max(2,min(limit,10000)))
            points=[point(row) for row in rows]
            return {'points':points,'count':len(points),'total':total,'test_data':False}
    @app.get('/api/findmy/{ident}')
    def findmy(ident:str,user=Depends(current)):
        check(user,'FindMy','read')
        with store().session() as repo:
            beacon=next((b for b in beacons(repo) if b['id']==ident),None)
            if not beacon:fail('找不到 Beacon',404)
            t=table(repo,'new_reports');row=None
            if t is not None:row=repo.c.execute(select(t).where(t.c.sheet_id==ident).order_by(t.c.timestamp.desc(),t.c.id.desc()).limit(1)).mappings().first()
            position=point(row)
            return {**beacon,'beacon':beacon,'points':[position] if position and position['lat'] is not None and position['lng'] is not None else [],'point':position,'position':position,'latest':position,'test_data':False,**(position or {'lat':None,'lng':None})}
    @app.get('/api/stations')
    def stations(user=Depends(current)):
        check(user,'Latest_Device','read')
        with store().session() as repo:
            t=table(repo,'Outdoor_Beacon_readings')
            return list(repo.c.execute(select(t.c.client_id).distinct()).scalars()) if t is not None else []
    @app.get('/api/scans')
    def scans(station:str='',user=Depends(current)):
        check(user,'Latest_Device','read')
        with store().session() as repo:
            t=table(repo,'Outdoor_Beacon_readings')
            if t is None:return []
            q=select(t).where(t.c.client_id==station).order_by(t.c.created_at.desc()).limit(1000)
            seen=set();result=[]
            for row in repo.c.execute(q).mappings():
                if row['major'] in seen:continue
                seen.add(row['major']);age=(now()-row['created_at']).total_seconds()
                result.append({'major':row['major'],'minor':row['minor'],'client_id':station,'rssi':row['rssi'],'power':row['battery'],'created_at':iso(row['created_at']),'age_seconds':age,'online':age<300})
            return result
    @app.get('/api/holidays')
    def holidays(user=Depends(current)):
        path=os.getenv('AMS_HOLIDAYS_FILE')
        return json.loads(Path(path).read_text()) if path else []
    @app.get('/api/notifications')
    def notifications(user=Depends(current)):
        check(user,'Administration','read')
        with store().session() as repo:
            t=table(repo,'notification')
            if t is None:return []
            return [{'id':row['id'],'created_at':iso(row['created_at']),'payload':{'Title':row['title'],'Content':row['content'],'UserID':row['email']},'success':True,'source':'legacy'} for row in repo.c.execute(select(t).order_by(t.c.created_at.desc()).limit(500)).mappings()]
    @app.post('/api/notifications/check')
    def notification_check(user=Depends(current)):
        fail('通知由既有系統流程處理；新版不會另行發送通知。',409)
    @app.post('/api/reports/sync')
    @app.post('/api/reports/import')
    def reports(user=Depends(current)):
        check(user,'Administration','write');fail('定位資料由既有匯入程序寫入資料庫；請在原系統更新。',409)
