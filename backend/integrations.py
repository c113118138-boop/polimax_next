"""Persistent fixture adapters: reports, beacons, holidays, and notification outbox.
Reports are imported once, never synthesized by a read endpoint.
"""
import json
import math
import os
import uuid
from datetime import timedelta
from pathlib import Path
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, select


def options():
    path=os.getenv('AMS_OPTIONS_FILE')
    if not path and os.getenv('AMS_DATABASE_MODE','mysql') != 'demo':
        return {'cities':json.loads(Path(__file__).with_name('taiwan_cities.json').read_text()),'test_data':False}
    return json.loads(Path(path).read_text()) if path else {'cities':{'臺北市':['中正區','信義區'],'新竹市':['東區','北區'],'臺中市':['西屯區','南屯區'],'高雄市':['左營區','前鎮區']},'test_data':True}

def valid(lat,lng):
    if lat is None or lng is None:return False
    return math.isfinite(lat) and math.isfinite(lng) and -90<=lat<=90 and -180<=lng<=180 and not (abs(lat-.00009)<=.0001 and abs(lng-.00017)<=.0001) and not (abs(lat)<.001 and abs(lng)<.001)

class BeaconInput(BaseModel):
    id:str
    owner:str=Field(min_length=1)
    programmed:str='n'
    equipment_resource_id:int|None=None
    ble_mac:str=''

class ReportInput(BaseModel):
    source:str
    report_id:str=Field(min_length=1,max_length=100)
    client_id:str=''
    major:int|None=None
    minor:int|None=None
    lat:float|None=None
    lng:float|None=None
    record_time:str
    created_at:str
    rssi:float|None=None
    power:float|None=None

class ReportBatch(BaseModel):
    reports:list[ReportInput]=Field(max_length=10000)


def seed(db):
    if db.get(Marker,'reports-v1'):return
    db.add(Marker(key='reports-v1',value='seeded'))
    day=now().replace(hour=0,minute=0,second=0,microsecond=0)
    resources=db.scalars(select(Resource).where(Resource.deleted==0).order_by(Resource.id)).all()
    cars=[r for r in resources if r.kind=='vehicle'];equipment=[r for r in resources if r.kind=='equipment']
    for i,r in enumerate(equipment[:2]):
        bid=f'{11+i:04x}';owner=json.loads(r.payload).get('name',r.label)
        db.add(Beacon(id=bid,major=11+i,owner=owner,programmed='y',resource_id=r.id,ble_mac=f'02:00:00:00:00:{11+i:02x}'))
        db.add(Report(id='findmy-demo-'+bid,source='findmy',major=11+i,lat=24.81+i*.01,lng=120.98+i*.01,record_time=now()-timedelta(minutes=20),created_at=now()-timedelta(minutes=19)))
    for i,r in enumerate(cars):
        client=json.loads(r.payload).get('client_id')
        if not client:continue
        count=1205 if i==0 else 1 if i==1 else 30
        for n in range(count):
            t=day+timedelta(hours=9,seconds=n*5)
            db.add(Report(id=f'gps-demo-{r.id}-{n}',source='gps',client_id=client,lat=24.80+n*.00001+i*.02,lng=120.968+n*.000014+i*.02,record_time=t,created_at=t))
        db.add(Report(id=f'gps-invalid-{r.id}',source='gps',client_id=client,lat=.00009,lng=.00017,record_time=day+timedelta(hours=12),created_at=day+timedelta(hours=12)))
    for station in ('PLM-STATION-01','PLM-STATION-02'):
        for i,age in enumerate((299,300,450)):
            db.add(Report(id=f'scan-demo-{station}-{i}',source='scan',client_id=station,major=11+i,minor=1,rssi=-48-i*13,power=80-i*12,record_time=now()-timedelta(seconds=age),created_at=now()-timedelta(seconds=age)))
    db.add(Marker(key='holiday',value=json.dumps([{'title':'測試假日','date':day.date().isoformat(),'allDay':True}])))
    if cars:
        car=Resource(kind='vehicle',label='TEST-NOTIFY',payload=json.dumps({'model':'測試通知專用車','owner':'測試管理員','purchase_date':day.date().isoformat(),'amount':0,'passengers':1,'manager':'demo-admin','notes':'虛構通知驗收車輛'},ensure_ascii=False));db.add(car);db.flush()
        for days in (-1,0,7,30,31):
            db.add(Record(resource_id=car.id,category='insurance',payload=json.dumps({'company':f'測試保險 {days:+d} 天','expiry':(day+timedelta(days=days)).date().isoformat(),'policy_files':[],'claim_files':[],'notes':'虛構邊界驗收資料'},ensure_ascii=False)))


def notification_check(db):
    result={'sent':0,'failed':0,'skipped':0,'test_data':True}
    last=db.get(Marker,'notification_last_check')
    if last and now()-parse(last.value)<timedelta(minutes=2):return {**result,'throttled':True}
    today=now().date()
    for r in db.scalars(select(Record).where(Record.category=='insurance',Record.deleted==0)):
        car=db.get(Resource,r.resource_id);p=json.loads(r.payload)
        if not car or car.deleted:continue
        manager=json.loads(car.payload).get('manager')
        try:expiry=parse(p['expiry']).date()
        except (KeyError,HTTPException):result['skipped']+=1;continue
        days=(expiry-today).days
        if not manager or days>30:result['skipped']+=1;continue
        key=f'{r.id}:{expiry.isoformat()}'
        previous=db.scalar(select(Notification).where(Notification.dedup_key==key,Notification.success==1,Notification.created_at>now()-timedelta(days=7)))
        if previous:result['skipped']+=1;continue
        state=f'保險已過期 {abs(days)} 天' if days<0 else '保險今日到期' if days==0 else '保險即將到期' if days<=7 else '保險到期提醒'
        body={'CompanyTax':os.getenv('AMS_COMPANY','polime'),'UserID':str(manager),'Title':f'{car.label} {state}',
              'Content':f'{car.label}／{p["company"]}／有效期限 {expiry}／'+(f'逾期 {abs(days)} 天' if days<0 else f'剩餘 {days} 天')+'，請安排續保。','Service':os.getenv('AMS_SERVICE','AMS')}
        success=os.getenv('AMS_NOTIFY_FAIL','0')!='1'
        db.add(Notification(id=uuid.uuid4().hex,dedup_key=key,payload=json.dumps(body,ensure_ascii=False),success=int(success),error='' if success else '測試通知來源失敗',created_at=now()))
        result['sent' if success else 'failed']+=1
    if result['failed']==0:
        if last:last.value=iso(now())
        else:db.add(Marker(key='notification_last_check',value=iso(now())))
    return result


def install(ctx):
    global Beacon,Report,Marker,Notification
    for name in ('Base','app','Resource','Record','Session','getdb','user','admin','now','iso','parse','dump','DATA','Sequence'):
        globals()[name]=ctx[name]
    class Beacon(Base):
        __tablename__='ams_preview_beacons'
        id=Column(String(40),primary_key=True)
        major=Column(Integer,unique=True,nullable=False)
        owner=Column(String(200),nullable=False)
        programmed=Column(String(1),nullable=False,default='n')
        resource_id=Column(Integer)
        ble_mac=Column(String(40))
        deleted=Column(Integer,default=0,nullable=False)
    class Report(Base):
        __tablename__='ams_preview_reports'
        id=Column(String(150),primary_key=True)
        source=Column(String(20),nullable=False,index=True)
        client_id=Column(String(100),index=True)
        major=Column(Integer,index=True)
        minor=Column(Integer)
        lat=Column(Float)
        lng=Column(Float)
        record_time=Column(DateTime,nullable=False,index=True)
        created_at=Column(DateTime,nullable=False,index=True)
        rssi=Column(Float)
        power=Column(Float)
    class Marker(Base):
        __tablename__='ams_preview_integration_state'
        key=Column(String(100),primary_key=True)
        value=Column(Text,nullable=False)
    class Notification(Base):
        __tablename__='ams_preview_notifications'
        id=Column(String(40),primary_key=True)
        dedup_key=Column(String(100),nullable=False,index=True)
        payload=Column(Text,nullable=False)
        success=Column(Integer,nullable=False)
        error=Column(Text)
        created_at=Column(DateTime,nullable=False)
    def bj(b):return {'id':b.id,'major':b.major,'owner':b.owner,'programmed':b.programmed,'equipment_resource_id':b.resource_id,'ble_mac':b.ble_mac}
    def validate_beacon(body):
        try:
            major=int(body.id,16)
            if major<0 or major>65535:raise ValueError()
        except ValueError:raise HTTPException(422,'Beacon ID 必須為 0000–ffff 十六進位字串')
        if body.programmed not in ('y','n'):raise HTTPException(422,'programmed 須為 y 或 n')
        return major
    @app.get('/api/beacons')
    def beacons(u=Depends(user),db=Depends(getdb)):return [bj(b) for b in db.scalars(select(Beacon).where(Beacon.deleted==0).order_by(Beacon.id))]
    @app.post('/api/beacons')
    def create_beacon(body:BeaconInput,u=Depends(admin),db=Depends(getdb)):
        major=validate_beacon(body)
        if db.scalar(select(Beacon).where(Beacon.major==major)):raise HTTPException(409,'Beacon ID 已存在（含歷史）')
        if body.equipment_resource_id:
            r=db.get(Resource,body.equipment_resource_id)
            if not r or r.kind!='equipment' or r.deleted:raise HTTPException(422,'請選擇有效設備')
        b=Beacon(id=body.id.lower(),major=major,owner=body.owner,programmed=body.programmed,resource_id=body.equipment_resource_id,ble_mac=body.ble_mac);db.add(b);db.commit();return bj(b)
    @app.put('/api/beacons/{id}')
    def edit_beacon(id:str,body:BeaconInput,u=Depends(admin),db=Depends(getdb)):
        b=db.get(Beacon,id)
        if not b or b.deleted:raise HTTPException(404,'找不到 Beacon')
        if body.id!=id:raise HTTPException(422,'Beacon ID 不可修改')
        validate_beacon(body)
        if body.equipment_resource_id:
            r=db.get(Resource,body.equipment_resource_id)
            if not r or r.kind!='equipment' or r.deleted:raise HTTPException(422,'請選擇有效設備')
        b.owner=body.owner;b.programmed=body.programmed;b.resource_id=body.equipment_resource_id;b.ble_mac=body.ble_mac;db.commit();return bj(b)
    @app.delete('/api/beacons/{id}')
    def delete_beacon(id:str,u=Depends(admin),db=Depends(getdb)):
        b=db.get(Beacon,id)
        if not b or b.deleted:raise HTTPException(404,'找不到 Beacon')
        b.deleted=1;db.commit();return {'ok':True}
    @app.post('/api/reports/import')
    def import_reports(body:ReportBatch,u=Depends(admin),db=Depends(getdb)):
        db.execute(select(Sequence).where(Sequence.key=='global').with_for_update()).scalar_one()
        count=0
        for p in body.reports:
            if p.source not in ('gps','findmy','scan'):raise HTTPException(422,'來源須為 gps／findmy／scan')
            if p.source in ('gps','scan') and not p.client_id:raise HTTPException(422,'GPS／掃描報告需要 client_id')
            if p.source in ('findmy','scan') and p.major is None:raise HTTPException(422,'FindMy／掃描報告需要 major')
            id=p.source+':'+p.report_id
            if db.get(Report,id):continue
            db.add(Report(id=id,source=p.source,client_id=p.client_id,major=p.major,minor=p.minor,lat=p.lat,lng=p.lng,record_time=parse(p.record_time),created_at=parse(p.created_at),rssi=p.rssi,power=p.power));count+=1
        db.commit();return {'inserted':count,'duplicates':len(body.reports)-count,'test_data':True}
    @app.post('/api/reports/sync')
    def sync_reports(u=Depends(admin),db=Depends(getdb)):
        marker=db.get(Marker,'last_sync')
        if marker and now()-parse(marker.value)<timedelta(minutes=1):raise HTTPException(429,'每分鐘最多更新一次')
        path=os.getenv('AMS_REPORTS_FILE')
        if not path:raise HTTPException(503,'尚未設定報告來源檔，請使用匯入報告')
        try:batch=ReportBatch.model_validate_json(Path(path).read_text())
        except (OSError,ValueError) as e:raise HTTPException(503,'來源讀取失敗，保留既有報告') from e
        result=import_reports(batch,u,db)
        if marker:marker.value=iso(now())
        else:db.add(Marker(key='last_sync',value=iso(now())))
        db.commit();return result
    def point(p):return {'lat':p.lat,'lng':p.lng,'time':iso(p.record_time),'created_at':iso(p.created_at)}
    @app.get('/api/positions')
    def positions(u=Depends(user),db=Depends(getdb)):
        result=[]
        for r in db.scalars(select(Resource).where(Resource.kind.in_(['vehicle','equipment']),Resource.deleted==0)):
            payload=json.loads(r.payload);client=payload.get('client_id');b=db.scalar(select(Beacon).where(((Beacon.resource_id==r.id)|(Beacon.owner==client)) if client else (Beacon.resource_id==r.id),Beacon.deleted==0))
            gps=[]
            if client and client.startswith(os.getenv('AMS_TRACKING_PREFIX','PLM')):
                gps=db.scalars(select(Report).where(Report.source=='gps',Report.client_id==client).order_by(Report.created_at.desc(),Report.id.desc())).all()
            fm=db.scalars(select(Report).where(Report.source=='findmy',Report.major==b.major).order_by(Report.created_at.desc(),Report.id.desc())).all() if b else []
            reports=gps if r.kind=='vehicle' else fm
            latest=reports[0] if reports else None
            position=next((p for p in reports if valid(p.lat,p.lng) and abs(p.lat)>1 and abs(p.lng)>1),None)
            gt=max((p.record_time for p in gps if p.record_time>=now()-timedelta(days=90)),default=None)
            ft=max((p.record_time for p in fm),default=None)
            source='GPS' if gt and (not ft or gt>ft) else 'FindMy' if ft else 'N/A'
            result.append({'resource_id':r.id,'client_id':client,'lat':position.lat if position else None,'lng':position.lng if position else None,'time':iso(position.record_time) if position else None,'updated_at':iso(latest.created_at) if latest else None,'gps_time':iso(gt),'findmy_time':iso(ft),'source':source,'test_data':True})
        return result
    @app.get('/api/trajectory/{id}')
    def trajectory(id:int,start:str,end:str,u=Depends(user),db=Depends(getdb)):
        s,e=parse(start),parse(end)
        if s>=e:raise HTTPException(422,'結束時間必須晚於開始時間')
        r=db.get(Resource,id)
        if not r or r.kind!='vehicle':raise HTTPException(404,'找不到車輛')
        client=json.loads(r.payload).get('client_id')
        if not client:return {'points':[],'test_data':True,'total':0}
        rows=db.scalars(select(Report).where(Report.source=='gps',Report.client_id==client,Report.created_at>=s,Report.created_at<e).order_by(Report.created_at,Report.id)).all()
        rows=[p for p in rows if valid(p.lat,p.lng)]
        total=len(rows);step=max(1,math.ceil(total/1000));sample=rows[::step]
        if rows and sample[-1].id!=rows[-1].id:sample.append(rows[-1])
        return {'points':[{**point(p),'type':'start' if i==0 else 'end' if i==len(sample)-1 else 'middle','label':'起點' if i==0 else '終點' if i==len(sample)-1 else '中繼點'} for i,p in enumerate(sample)],'client_id':client,'total':total,'test_data':True}
    @app.get('/api/findmy/{id}')
    def findmy(id:str,u=Depends(user),db=Depends(getdb)):
        try:major=int(id,16)
        except ValueError:raise HTTPException(422,'無效的十六進位 ID')
        beacon=db.scalar(select(Beacon).where(Beacon.major==major,Beacon.deleted==0))
        if not beacon:raise HTTPException(404,'找不到 Beacon')
        rows=db.scalars(select(Report).where(Report.source=='findmy',Report.major==major).order_by(Report.created_at.desc(),Report.id.desc()).limit(10)).all()
        return {'beacon':bj(beacon),'points':[point(p) for p in rows if valid(p.lat,p.lng)],'test_data':True}
    @app.get('/api/stations')
    def stations(u=Depends(user),db=Depends(getdb)):return list(db.scalars(select(Report.client_id).where(Report.source=='scan').distinct()))
    @app.get('/api/scans')
    def scans(station:str,u=Depends(user),db=Depends(getdb)):
        rows=db.scalars(select(Report).where(Report.source=='scan',Report.client_id==station).order_by(Report.record_time.desc(),Report.created_at.desc(),Report.id.desc())).all()
        seen=set();result=[]
        for p in rows:
            if p.major in seen:continue
            seen.add(p.major);b=db.scalar(select(Beacon).where(Beacon.major==p.major,Beacon.deleted==0))
            result.append({'id':p.major,'major':p.major,'minor':p.minor,'name':b.owner if b else '未知設備','rssi':p.rssi,'power':p.power,'time':iso(p.record_time),'created_at':iso(p.created_at),'status':'online' if p.record_time>now()-timedelta(minutes=5) else 'offline'})
        return result
    @app.get('/api/holidays')
    def holidays(u=Depends(user),db=Depends(getdb)):
        path=os.getenv('AMS_HOLIDAYS_FILE')
        try:return json.loads(Path(path).read_text()) if path else json.loads(db.get(Marker,'holiday').value)
        except (OSError,ValueError) as e:raise HTTPException(503,'假日來源讀取失敗') from e
    @app.post('/api/notifications/check')
    def check_notifications(u=Depends(user),db=Depends(getdb)):
        db.execute(select(Sequence).where(Sequence.key=='global').with_for_update()).scalar_one()
        result=notification_check(db);db.commit();return result
    @app.get('/api/notifications')
    def notifications(u=Depends(admin),db=Depends(getdb)):
        return [{'id':n.id,'content':json.loads(n.payload),'success':bool(n.success),'error':n.error,'time':iso(n.created_at),'test_data':True} for n in db.scalars(select(Notification).order_by(Notification.created_at.desc()))]
