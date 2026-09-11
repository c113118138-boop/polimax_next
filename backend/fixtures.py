"""Versioned, additive fixtures for an offline demonstration of every core flow."""
import base64
import json
from datetime import timedelta
from sqlalchemy import select
from fastapi import HTTPException

def seed(c):
    from integrations import Marker
    with c['Session'].begin() as db:
        if db.get(Marker,'acceptance-fixtures-v1'):return
        db.add(Marker(key='acceptance-fixtures-v1',value='test data'))
        Resource,Form,Occupancy,Attachment=[c[k] for k in ('Resource','Form','Occupancy','Attachment')]
        cars=db.scalars(select(Resource).where(Resource.kind=='vehicle',Resource.deleted==0).order_by(Resource.id)).all()
        if not cars:return
        u=c['USERS']['admin'];now=c['now']();day=now.replace(hour=9,minute=0,second=0,microsecond=0)
        for i,reason in enumerate(c['REASONS']):
            car=cars[i%len(cars)];start=day+timedelta(days=10+i);end=start+timedelta(hours=2)
            slots=[{'resource_id':car.id,'start':c['iso'](start),'end':c['iso'](end)}]
            if i==5:slots[0]['end']=c['iso'](end+timedelta(days=1))
            if i==6:slots.append({'resource_id':car.id,'start':c['iso'](start+timedelta(hours=4)),'end':c['iso'](end+timedelta(hours=4))})
            content={'title':f'測試：{reason}','reason':reason,'applicant':u['name'],'application_date':now.date().isoformat(),'total_people':2,'employees':['林品安','陳予晴'],'details':[{'name':f'DEMO-{i+1:03} {reason}','city':'新竹市','district':'東區','leader':'林品安','sales':['陳予晴'],'notes':'虛構測試明細'}],'slots':slots,'purposes':['量測'],'notes':'依附錄 D 補足的虛構示範資料','resource_snapshots':[c['resource_json'](car)]}
            # Additive migration: move fixture slots if existing user bookings occupy them.
            for attempt in range(366):
                try:
                    c['validate_booking'](db,c['BookingInput'](kind='A',content=content))
                    break
                except HTTPException as error:
                    if error.status_code!=409:raise
                    for slot in slots:
                        slot['start']=c['iso'](c['parse'](slot['start'])+timedelta(days=1))
                        slot['end']=c['iso'](c['parse'](slot['end'])+timedelta(days=1))
            else:raise RuntimeError('無法安排測試資料，既有預約保持不變')
            status=c['STATES'][i%5];f=Form(id=c['number'](db,'A'),kind='A',owner=u['id'],payload=c['dump'](content),status=status);db.add(f);db.flush()
            for s in slots:db.add(Occupancy(form_id=f.id,resource_id=car.id,start=c['parse'](s['start']),end=c['parse'](s['end'])))
            c['event'](db,f,'建立測試預約',u)
            for kind,threshold in [('B',1),('C',3)]:
                if i%5<threshold:continue
                data={'driver':'林品安','codriver':'陳予晴','employees':['林品安','陳予晴'],'place':'測試廠區','resource_id':car.id,'mileage':100 if kind=='B' else 130,'confirmed':True,'checks':c['stages'].CHECKS_B if kind=='B' else c['stages'].CHECKS_C,'tires':'正常','interior':'正常','exterior':'正常','equipment':'正常','notes':'虛構階段資料'}
                c['validate_stage'](db,f,kind,'start',data);data['submitted_at']=c['iso'](now)
                payload={'start':data}
                if i%5>threshold:payload['arrival']={'mileage':120 if kind=='B' else 155,'confirmed':True,'anomalies':[],'submitted_at':c['iso'](now),'notes':'測試抵達'}
                db.add(Form(id=c['number'](db,kind),kind=kind,owner=u['id'],parent_id=f.id,payload=c['dump'](payload)))
            for n in range(1,i%5+1):c['event'](db,f,c['STATES'][n-1]+' → '+c['STATES'][n],u)
        for label,kind,payload in [('TEST-DELETED','vehicle',{'model':'測試已刪除車','owner':'測試','purchase_date':now.date().isoformat(),'amount':0,'passengers':1}),('EQ-DISABLED','equipment',{'name':'測試停用儀器','location':'X-01','state':'停用','quantity':1})]:
            if not db.scalar(select(Resource).where(Resource.label==label)):db.add(Resource(label=label,kind=kind,payload=c['dump'](payload),deleted=int(kind=='vehicle')))
        for id,name,mime,content in [('demo-image','示範圖片.png','image/png',base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')),('demo-document','示範文件.txt','text/plain','POLIMAX 虛構附件測試'.encode())]:
            (c['DATA']/id).write_bytes(content)
            db.add(Attachment(id=id,name=name,mime=mime,size=len(content),owner=u['id']))
        files=[{'id':'demo-image','name':'示範圖片.png','mime':'image/png'},{'id':'demo-document','name':'示範文件.txt','mime':'text/plain'}]
        for category,data in [('cost',{'type':'保養','reason':'示範保養費','amount':1000}),('maintenance',{'type':'驗車','date':now.date().isoformat()}),('garage',{'notes':'測試保養廠'}),('manager',{'name':'測試管理人'})]:db.add(c['Record'](resource_id=cars[0].id,category=category,payload=c['dump']({**data,'attachments':files})))
