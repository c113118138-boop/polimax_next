"""POLIMAX API with MySQL persistence and an explicit isolated demo mode."""
import hashlib
import json
import os
import secrets
import math
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import (Column, DateTime, Integer, String, Text, UniqueConstraint,
                        URL, create_engine, select, inspect, text)
from sqlalchemy.exc import SQLAlchemyError
from database import configuration
from sqlalchemy.orm import declarative_base, sessionmaker

ROOT = Path(__file__).resolve().parents[1]

TZ = timezone(timedelta(hours=8))
def now(): return datetime.now(TZ).replace(tzinfo=None)
DATA, url, MYSQL = configuration(ROOT)
DATA.mkdir(parents=True, exist_ok=True)
engine = create_engine(url, pool_pre_ping=True, hide_parameters=True,
                       connect_args={'timeout':30,'check_same_thread':False} if str(url).startswith('sqlite:') else {'connect_timeout':10},
                       **({'isolation_level':'READ COMMITTED'} if str(url).startswith('mysql') else {}))
# SQLite ignores SELECT FOR UPDATE. Explicit BEGIN IMMEDIATE serializes transactions
# across connections AND workers before any read/check/write, including sequence reads.
if engine.dialect.name == 'sqlite':
    from sqlalchemy import event as sa_event
    @sa_event.listens_for(engine, 'connect')
    def sqlite_connect(connection, _):
        connection.isolation_level = None
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=30000')
    @sa_event.listens_for(engine, 'begin')
    def sqlite_begin(connection):
        connection.exec_driver_sql('BEGIN IMMEDIATE')
Session = sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()
PREFIX = 'ams_preview_'
class Resource(Base):
    __tablename__ = PREFIX+'resources'
    id = Column(Integer, primary_key=True)
    kind = Column(String(24), nullable=False)
    label = Column(String(200), nullable=False, unique=True)
    payload = Column(Text, nullable=False)
    deleted = Column(Integer, default=0, nullable=False)

class Form(Base):
    __tablename__ = PREFIX+'forms'
    id = Column(String(40), primary_key=True)
    kind = Column(String(2), nullable=False)
    owner = Column(String(100), nullable=False)
    payload = Column(Text, nullable=False)
    status = Column(String(30), default='PENDING', nullable=False)
    parent_id = Column(String(40))
    previous_id = Column(String(40))
    revision = Column(Integer, default=1, nullable=False)
    deleted = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now)

class Occupancy(Base):
    __tablename__ = PREFIX+'occupancies'
    id = Column(Integer, primary_key=True)
    form_id = Column(String(40), nullable=False, index=True)
    resource_id = Column(Integer, nullable=False, index=True)
    start = Column(DateTime, nullable=False, index=True)
    end = Column(DateTime, nullable=False)
    active = Column(Integer, default=1, nullable=False)

class Sequence(Base):
    __tablename__ = PREFIX+'sequences'
    key = Column(String(20), primary_key=True)
    value = Column(Integer, default=0, nullable=False)

class Revision(Base):
    __tablename__ = PREFIX+'revisions'
    id = Column(Integer, primary_key=True)
    form_id = Column(String(40), index=True)
    payload = Column(Text, nullable=False)
    actor = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=now)

class Event(Base):
    __tablename__ = PREFIX+'events'
    id = Column(Integer, primary_key=True)
    form_id = Column(String(40), index=True)
    action = Column(String(100), nullable=False)
    actor = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=now)

class Record(Base):
    __tablename__ = PREFIX+'records'
    id = Column(Integer, primary_key=True)
    resource_id = Column(Integer, index=True, nullable=False)
    category = Column(String(30), nullable=False)
    payload = Column(Text, nullable=False)
    deleted = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=now)

class Attachment(Base):
    __tablename__ = PREFIX+'attachments'
    id = Column(String(40), primary_key=True)
    name = Column(String(255), nullable=False)
    mime = Column(String(150), nullable=False)
    owner = Column(String(100), nullable=False)
    size = Column(Integer, nullable=False)

class Login(Base):
    __tablename__ = PREFIX+'sessions'
    token = Column(String(64), primary_key=True)
    role = Column(String(20), nullable=False)
    expires = Column(DateTime, nullable=False)

USERS = {
    'admin': {'id':'demo-admin','name':'林品安','email':'admin@example.test','role':'admin','role_label':'測試管理員'},
    'borrower': {'id':'demo-borrower','name':'陳予晴','email':'borrower@example.test','role':'borrower','role_label':'測試借用人'},
    'draft': {'id':'demo-draft','name':'測試草稿員','email':'draft@example.test','role':'draft','role_label':'可新增但不可送出'},
    'viewer': {'id':'demo-viewer','name':'周以恆','email':'viewer@example.test','role':'viewer','role_label':'測試唯讀使用者'},
}
STATES = ['PENDING','DEPARTURE','DEPARTURE_ARRIVED','RETURN','RETURN_ARRIVED']
STATE_LABELS = ['已預約','已發車','發車已抵達','已開始回程','已完成']
REASONS = ['工案','材料送貨','新開發案','客戶拜訪','成交案回訪','參展','其他']
E_REASONS = ['開案','成案（施工前量測）','成案（完工量測）','成案（服務回訪）','儀器設備保養／校正','儀器設備維修','其它']
def dump(value): return json.dumps(value, ensure_ascii=False)
def iso(value): return value.isoformat(timespec='seconds')+'+08:00' if value else None
def parse(value):
    try:
        d = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return d.astimezone(TZ).replace(tzinfo=None) if d.tzinfo else d
    except (ValueError,TypeError): raise HTTPException(422,'請填寫有效的日期與時間')
def fail(msg, code=422): raise HTTPException(code,msg)
def getdb(request:Request):
    yield request.state.db
def user(request: Request, db=Depends(getdb)):
    token = request.cookies.get('ams_preview_session','')
    s = db.get(Login, hashlib.sha256(token.encode()).hexdigest())
    if not s or s.expires < now(): fail('登入已失效，請重新登入',401)
    u = dict(USERS[s.role])
    u['permissions'] = permissions.effective(db, u)
    return u
def writer(u=Depends(user)):
    if not any(p.get('create') or p.get('write') for p in u['permissions']['forms'].values()): fail('權限不足：需要 create／write／submit 權限',403)
    return u
def admin(u=Depends(user)):
    return u
def public_payload(payload): return {k:v for k,v in json.loads(payload).items() if not k.startswith('_')}
def resource_json(r): return {**public_payload(r.payload),'id':r.id,'kind':r.kind,'label':r.label}
def form_json(f, db):
    slots = db.scalars(select(Occupancy).where(Occupancy.form_id==f.id,Occupancy.active==1).order_by(Occupancy.id)).all()
    return {'id':f.id,'kind':f.kind,'owner':f.owner,'content':public_payload(f.payload),'status':f.status,
            'contact_person':','.join(json.loads(f.payload).get('employees',[])) or json.loads(f.payload).get('applicant',''),'revision':f.revision,'parent_id':f.parent_id,'previous_id':f.previous_id,
            'created_at':iso(f.created_at),'updated_at':iso(f.updated_at),
            'slots':[{'resource_id':s.resource_id,'start':iso(s.start),'end':iso(s.end)} for s in slots]}
def snapshot(db,f,u): db.add(Revision(form_id=f.id,payload=dump(form_json(f,db)),actor=u['name']))
def event(db,f,action,u): db.add(Event(form_id=f.id,action=action,actor=u['name']))
def getform(db,id):
    f=db.get(Form,id)
    if not f or f.deleted: fail('找不到這張有效申請',404)
    return f
def number(db,kind):
    # All form transactions hold the persistent global sequence row first.
    lock=db.execute(select(Sequence).where(Sequence.key=='global').with_for_update()).scalar_one()
    t=now(); key=f'{t.year-1911}{t.month:02}{kind}'
    seq=db.get(Sequence,key)
    if not seq: seq=Sequence(key=key,value=0); db.add(seq)
    seq.value+=1; db.flush()
    return f'{key}{seq.value:04}'

def seed():
    Base.metadata.create_all(engine)
    DATA.mkdir(parents=True,exist_ok=True)
    with Session.begin() as db:
        if db.get(Sequence,'global'): return
        db.add(Sequence(key='global',value=0)); db.flush()
        for label,model,owner,seats in [('TEST-001','Toyota Corolla Cross','林品安',5),('TEST-002','Toyota Town Ace','陳予晴',5),('TEST-003','Ford Transit','周以恆',8)]:
            db.add(Resource(kind='vehicle',label=label,payload=dump({'model':model,'owner':owner,'holder':owner,'purchase_date':'2025-04-15','amount':950000,'passengers':seats,'client_id':'PLM-'+label,'notes':'虛構測試車輛','equipment':['備胎','跨接電纜']})))
        for label,name,holder in [('EQ-001','雷射測距儀','陳予晴'),('EQ-002','塗層厚度計','林品安'),('EQ-003','數位振動分析儀','周以恆')]:
            db.add(Resource(kind='equipment',label=label,payload=dump({'name':name,'location':'A-01','holder':holder,'brand':'DEMO','quantity':1,'state':'列管','accessories':[{'name':'主機','quantity':1},{'name':'電池','quantity':2}]})))
        for floor,area,units in [('1F','批覆區',['1-1','1-2']),('1F','拆組裝區',['1-1','1-2']),('1F','裝載區',['整區']),('1F','汞浦試壓區',['整區']),('1F','噴砂室',['整區']),('1F','研磨與氣動除鏽區',['6-1','6-2','6-3']),('1F','產品說明室',['整區']),('2F','會議室',['整間']),('2F','會客室',['整間'])]:
            for unit in units: db.add(Resource(kind='room',label=f'{floor} {area} {unit}',payload=dump({'floor':floor,'area':area,'unit':unit})))
        db.flush(); resources=db.scalars(select(Resource)).all()
        day=now().replace(hour=0,minute=0,second=0,microsecond=0)
        examples=[(0,0,9,12,'工案','新竹廠區設備量測'),(1,0,13,17,'客戶拜訪','客戶現場需求討論'),(2,1,9,16,'材料送貨','工件配送與現場確認'),(0,2,8,12,'參展','產業設備展'),(1,-1,9,15,'其他','廠務用品採買'),(6,0,10,12,'作業區租用','設備拆裝作業'),(3,1,9,17,'開案','現場精密量測')]
        for i,(idx,offset,h1,h2,reason,title) in enumerate(examples):
            r=resources[idx]; kind={'vehicle':'A','room':'D','equipment':'E'}[r.kind]
            start=day+timedelta(days=offset,hours=h1); end=day+timedelta(days=offset,hours=h2)
            content={'applicant':'林品安','application_date':day.date().isoformat(),'total_people':2,'reason':reason,'title':title,'city':'新竹市','district':'東區','employees':['林品安','陳予晴'],'details':[{'name':title,'city':'新竹市','district':'東區'}],'purposes':['量測'],'notes':'此筆為虛構測試資料','slots':[{'resource_id':r.id,'start':start.isoformat(),'end':end.isoformat(),'detail_index':0}]}
            fid=number(db,kind); f=Form(id=fid,kind=kind,owner='demo-admin',payload=dump(content)); db.add(f); db.flush()
            db.add(Occupancy(form_id=fid,resource_id=r.id,start=start,end=end)); event(db,f,'建立預約',USERS['admin'])
        db.add(Record(resource_id=resources[0].id,category='insurance',payload=dump({'company':'測試產物保險','expiry':(day+timedelta(days=21)).date().isoformat(),'phone':'03-000-0000','notes':'測試保單，不會發送真實通知','attachments':[]})))

@asynccontextmanager
async def lifespan(app):
    seed()
    with Session.begin() as db:
        permissions.seed(db)
        integrations.seed(db)
    import fixtures
    fixtures.seed(globals())
    yield
app=FastAPI(title='POLIMAX Preview API',lifespan=lifespan)

@app.middleware('http')
async def security(request:Request,call_next):
    from fastapi.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool
    with Session() as db:
        request.state.db = db
        try:
            if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('x-ams-client')!='preview':
                fail('缺少有效的操作來源標記',403)
            if request.url.path.startswith('/api/') and request.url.path not in ('/api/health','/api/auth/login','/api/auth/logout'):
                u = await run_in_threadpool(user,request,db)
                await permissions.authorize(request,db,u)
            response=await call_next(request)
            if 'application/json' in response.headers.get('content-type','') and hasattr(request.state,'permission_user'):
                raw=b''.join([chunk async for chunk in response.body_iterator])
                payload=json.loads(raw)
                doc=getattr(request.state,'permission_doc',None)
                if doc:
                    payload=permissions.redact(payload,request.state.permission_user['permissions']['fields'].get(doc,{}))
                headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-type')}
                response=JSONResponse(payload,status_code=response.status_code,headers=headers)
        except HTTPException as e:
            db.rollback()
            response=JSONResponse({'detail':e.detail},status_code=e.status_code)
        except SQLAlchemyError:
            db.rollback()
            response=JSONResponse({'detail':'資料庫操作失敗，變更未儲存；請確認連線、欄位限制與帳號權限。'},status_code=503)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Cache-Control']='no-store'
        return response

@app.get('/api/auth/config')
def auth_settings(): return {'mode':'demo','configured':True}

@app.get('/api/health')
def health():
    with engine.connect() as connection:
        connection.execute(text('SELECT 1'))
    return {'ok':True,'mode':'mysql' if MYSQL else 'preview','database':'MySQL' if engine.dialect.name=='mysql' else engine.dialect.name,'test_data':not MYSQL}
class LoginInput(BaseModel): role:str
@app.post('/api/auth/login')
def login(body:LoginInput,response:Response,db=Depends(getdb)):
    if os.getenv('PREVIEW_LOGIN_ENABLED','1')!='1': fail('測試登入已關閉',403)
    if body.role not in USERS: fail('無效的測試身分')
    token=secrets.token_urlsafe(32)
    db.add(Login(token=hashlib.sha256(token.encode()).hexdigest(),role=body.role,expires=now()+timedelta(hours=12)));db.commit()
    response.set_cookie('ams_preview_session',token,httponly=True,samesite='lax',max_age=43200)
    u=dict(USERS[body.role]);u['permissions']=permissions.effective(db,u);return u
@app.get('/api/auth/me')
def me(u=Depends(user)): return u
@app.post('/api/auth/logout')
def logout(request:Request,response:Response,db=Depends(getdb)):
    token=hashlib.sha256(request.cookies.get('ams_preview_session','').encode()).hexdigest()
    s=db.get(Login,token)
    if s: db.delete(s);db.commit()
    response.delete_cookie('ams_preview_session');return {'ok':True}
def employee_names(db):
    if not MYSQL:
        return [x['name'] for x in USERS.values()]
    names = {str(name) for f in db.scalars(select(Form).where(Form.deleted==0)) for name in json.loads(f.payload).get('employees',[])}
    for resource in db.scalars(select(Resource).where(Resource.deleted==0)):
        payload = json.loads(resource.payload)
        for key in ('holder', 'owner', 'contact_person'):
            if payload.get(key): names.add(str(payload[key]))
    return sorted(names)

@app.get('/api/options')
def options(u=Depends(user),db=Depends(getdb)):
    return {**integrations.options(),'employees':[u['name']],'reasons':REASONS,'equipment_reasons':E_REASONS,'test_data':not MYSQL}

@app.get('/api/resources')
def resources(u=Depends(user),db=Depends(getdb)):
    return [resource_json(r) for r in db.scalars(select(Resource).where(Resource.deleted==0).order_by(Resource.id))]
class ResourceInput(BaseModel):
    kind:str
    label:str=Field(default='',max_length=200)
    data:dict
def validate_resource(body):
    body.data = {k:v for k,v in body.data.items() if not k.startswith('_')}
    if body.kind not in ('vehicle','equipment'): fail('無效的資產類型')
    if body.kind=='vehicle' and not body.label.strip():fail('請填寫車牌')
    required=['model','owner','purchase_date','amount','passengers'] if body.kind=='vehicle' else ['name','location']
    for key in required:
        if body.data.get(key) in (None,''):fail(f'必要資料尚未填寫：{key}')
    if body.kind=='vehicle':parse(body.data['purchase_date'])
    if body.kind=='equipment' and body.data.get('state','列管') not in ('列管','不列管','停用'):fail('無效的列管狀態')
    for key in ('amount','passengers','quantity','estimated_amount'):
        if body.data.get(key) not in ('',None):
            try:
                if not math.isfinite(float(body.data[key])) or float(body.data[key])<0:raise ValueError()
            except (ValueError,TypeError):fail(f'{key} 必須為非負數')
@app.post('/api/resources')
def addresource(body:ResourceInput,u=Depends(admin),db=Depends(getdb)):
    validate_resource(body)
    db.execute(select(Sequence).where(Sequence.key=='global').with_for_update()).scalar_one()
    label=body.label.strip() or 'EQ-'+uuid.uuid4().hex[:12]
    if db.scalar(select(Resource).where(Resource.label==label)):fail('此識別已存在，請使用不同車牌或編碼',409)
    r=Resource(kind=body.kind,label=label,payload=dump(body.data));db.add(r);db.commit();return resource_json(r)
@app.put('/api/resources/{id}')
def editresource(id:int,body:ResourceInput,u=Depends(admin),db=Depends(getdb)):
    validate_resource(body)
    r=db.scalar(select(Resource).where(Resource.id==id,Resource.deleted==0).with_for_update())
    if not r:fail('找不到資產',404)
    if r.kind!=body.kind:fail('不可更改資產類型')
    duplicate=db.scalar(select(Resource).where(Resource.label==body.label.strip(),Resource.id!=id))
    if duplicate:fail('此識別已存在',409)
    r.label=body.label.strip() or 'EQ-'+uuid.uuid4().hex[:12];r.payload=dump({**json.loads(r.payload),**body.data});db.commit();return resource_json(r)
@app.delete('/api/resources/{id}')
def deleteresource(id:int,u=Depends(admin),db=Depends(getdb)):
    r=db.scalar(select(Resource).where(Resource.id==id).with_for_update())
    if not r:fail('找不到資產',404)
    if r.kind=='room':fail('固定作業區不可刪除')
    r.deleted=1;db.commit();return {'ok':True}

class BookingInput(BaseModel):
    kind:str
    content:dict
    revision:int|None=None
def validate_booking(db,body,exclude=None):
    if body.kind not in ('A','D','E'):fail('無效的預約類型')
    body.content = {k:v for k,v in body.content.items() if not k.startswith('_')}
    c=body.content
    if not isinstance(c.get('slots'),list) or not isinstance(c.get('details',[]),list) or not isinstance(c.get('employees',[]),list):fail('時段、明細與人員須為集合')
    if any(not isinstance(d,dict) for d in c.get('details',[])+c['slots']):fail('時段與明細格式錯誤')
    if body.kind=='D': c['title']=c.get('title') or '作業區租用';c['reason']='作業區租用'
    if not c.get('title','').strip():fail('請填寫申請緣由')
    if body.kind in ('A','E'):
        if c.get('reason') not in (REASONS if body.kind=='A' else E_REASONS):fail('請選擇使用需求')
        if not c.get('employees'):fail('請選擇使用人員')
    if body.kind=='A':
        try:
            if int(c.get('total_people',0))<1:raise ValueError()
        except (ValueError,TypeError):fail('使用人數至少為 1')
        details=c.get('details',[])
        if not details:fail('請新增至少一筆需求明細')
        for d in details:
            if not d.get('city') or (c['reason']!='材料送貨' and not d.get('name','').strip()):fail('每筆需求明細須填寫內容與縣市')
        if len(details)!=1 and len(details)!=len(c.get('slots',[])):fail('明細與時段須一對一，或一筆明細對應多個時段')
    if body.kind=='E' and not c.get('details'):fail('請填寫儀器借用明細')
    for d in c.get('details',[]):
        if body.kind=='E' and not d.get('name','').strip():fail('請填寫案件、廠商或其他地點')
        if d.get('district') and d['district'] not in integrations.options()['cities'].get(d.get('city'),[]):fail('行政區不屬於所選縣市')
    if '其他' in c.get('purposes',[]) and not c.get('other_purpose','').strip():fail('請填寫其他用途說明')
    if '其他加工' in c.get('purposes',[]) and not c.get('other_processing','').strip():fail('請填寫其他加工說明')
    slots=c.get('slots',[])
    if not slots:fail('請新增至少一個資源與時段')
    normalized=[]
    try: ids=sorted(set(int(s['resource_id']) for s in slots))
    except (ValueError,KeyError,TypeError):fail('請選擇有效資源')
    rs=db.scalars(select(Resource).where(Resource.id.in_(ids)).order_by(Resource.id).with_for_update()).all()
    allowed={r.id:r for r in rs if not r.deleted and r.kind=={'A':'vehicle','D':'room','E':'equipment'}[body.kind] and json.loads(r.payload).get('state')!='停用'}
    for slot in slots:
        rid=int(slot['resource_id'])
        if rid not in allowed:fail('資源已刪除、停用或類型不符')
        s,e=parse(slot.get('start')),parse(slot.get('end'))
        if s>e or (body.kind!='A' and s==e):fail('結束時間必須晚於開始時間（車輛允許相同時間點）')
        for prev in normalized:
            if prev[0]==rid and s<=prev[2] and e>=prev[1]:fail(f'{allowed[rid].label}：本張申請內的時段重疊，首尾相接也算衝突',409)
        q=select(Occupancy).where(Occupancy.active==1,Occupancy.resource_id==rid,Occupancy.start<=e,Occupancy.end>=s)
        if exclude:q=q.where(Occupancy.form_id!=exclude)
        conflict=db.scalar(q)
        if conflict:fail(f'{allowed[rid].label} 要求 {s:%m/%d %H:%M}–{e:%m/%d %H:%M}，與 {conflict.form_id} 的 {conflict.start:%m/%d %H:%M}–{conflict.end:%m/%d %H:%M} 衝突（含相接邊界）',409)
        normalized.append((rid,s,e))
    c['resource_snapshots']=[resource_json(allowed[rid]) for rid in ids]
    return normalized

@app.get('/api/bookings')
def bookings(u=Depends(user),db=Depends(getdb)):
    return [form_json(f,db) for f in db.scalars(select(Form).where(Form.deleted==0,Form.kind.in_(['A','D','E'])).order_by(Form.created_at.desc()))]
@app.post('/api/bookings/check')
def check(body:BookingInput,u=Depends(writer),db=Depends(getdb)):
    validate_booking(db,body);return {'ok':True}
@app.post('/api/bookings')
def createbooking(body:BookingInput,u=Depends(writer),db=Depends(getdb)):
    fid=number(db,body.kind);slots=validate_booking(db,body)
    content={**body.content,'applicant':u['name'],'application_date':now().date().isoformat()}
    f=Form(id=fid,kind=body.kind,owner=u['id'],payload=dump(content));db.add(f);db.flush()
    for rid,s,e in slots:db.add(Occupancy(form_id=fid,resource_id=rid,start=s,end=e))
    event(db,f,'建立預約',u);db.commit();return form_json(f,db)
@app.get('/api/bookings/{id}')
def booking(id:str,u=Depends(user),db=Depends(getdb)):
    f=getform(db,id); result=form_json(f,db)
    result['stages']=[form_json(s,db) for s in db.scalars(select(Form).where(Form.parent_id==id,Form.deleted==0))]
    result['history']=[{'action':e.action,'actor':e.actor,'time':iso(e.created_at)} for e in db.scalars(select(Event).where(Event.form_id==id).order_by(Event.id))]
    result['versions']=[{'id':v.id,'actor':v.actor,'time':iso(v.created_at),'data':json.loads(v.payload)} for v in db.scalars(select(Revision).where(Revision.form_id==id).order_by(Revision.id.desc()))]
    result['incomplete']=any(not any(s['kind']==k and (not arrival or s['content'].get('arrival')) for s in result['stages']) for k,arrival in [('B',False)]*(f.status!='PENDING')+[('B',True)]*(f.status in STATES[2:])+[('C',False)]*(f.status in STATES[3:])+[('C',True)]*(f.status==STATES[4])) if f.kind=='A' else False
    if f.previous_id:
        old=db.get(Form,f.previous_id)
        if old: result['previous_version']=form_json(old,db)
    return result
@app.put('/api/bookings/{id}')
def editbooking(id:str,body:BookingInput,u=Depends(writer),db=Depends(getdb)):
    db.execute(select(Sequence).where(Sequence.key=='global').with_for_update()).scalar_one()
    f=getform(db,id)
    if f.kind!=body.kind:fail('不可變更表單類型')
    if body.revision!=f.revision:fail('資料已被更新，請重新開啟後編輯',409)
    if f.kind=='A' and f.status!='PENDING':fail('已發車的主單不可重新安排預約',409)
    slots=validate_booking(db,body,id);snapshot(db,f,u)
    content={**json.loads(f.payload),**body.content}
    content['applicant']=json.loads(f.payload)['applicant']
    content['application_date']=json.loads(f.payload)['application_date']
    for s in db.scalars(select(Occupancy).where(Occupancy.form_id==id)):s.active=0
    if f.kind=='A':
        f.deleted=1
        new=Form(id=number(db,'A'),kind='A',owner=f.owner,previous_id=f.id,payload=dump(content));db.add(new);db.flush()
        event(db,f,'被新版本 '+new.id+' 取代',u);f=new
    else:f.payload=dump(content);f.revision+=1;f.updated_at=now()
    for rid,s,e in slots:db.add(Occupancy(form_id=f.id,resource_id=rid,start=s,end=e))
    event(db,f,'修改預約',u);db.commit();return form_json(f,db)
@app.delete('/api/bookings/{id}')
def deletebooking(id:str,u=Depends(admin),db=Depends(getdb)):
    db.execute(select(Sequence).where(Sequence.key=='global').with_for_update()).scalar_one()
    f=getform(db,id);snapshot(db,f,u);f.deleted=1
    for s in db.scalars(select(Occupancy).where(Occupancy.form_id==id)):s.active=0
    event(db,f,'取消預約',u);db.commit();return {'ok':True}

class StageInput(BaseModel):
    expected_status:str
    content:dict
    revision:int
@app.post('/api/bookings/{id}/advance')
def advance(id:str,body:StageInput,u=Depends(writer),db=Depends(getdb)):
    db.execute(select(Sequence).where(Sequence.key=='global').with_for_update()).scalar_one()
    f=getform(db,id)
    if f.kind!='A' or f.status not in STATES[:-1]:fail('此申請沒有可執行的車輛階段',409)
    if f.status!=body.expected_status or f.revision!=body.revision:fail('流程已更新，請重新開啟後操作',409)
    idx=STATES.index(f.status);kind='B' if idx<2 else 'C';data=body.content
    validate_stage(db,f,kind,'start' if idx in (0,2) else 'arrival',data)
    mileage=float(data['mileage'])
    if idx>=2 and not db.scalar(select(Form).where(Form.parent_id==id,Form.kind=='B',Form.deleted==0)):fail('缺少發車紀錄，資料不完整',409)
    stage=db.scalar(select(Form).where(Form.parent_id==id,Form.kind==kind,Form.deleted==0))
    if idx in (1,3):
        if not stage:fail('缺少正確的發車或回程表，無法抵達',409)
        stored=json.loads(stage.payload)
        if mileage<float(stored['start']['mileage']):fail('結束里程不得小於開始里程')
        snapshot(db,stage,u);stored['arrival']={**data,'submitted_at':iso(now())};stage.payload=dump(stored);stage.revision+=1;stage.updated_at=now()
    else:
        if stage:fail('此階段已存在，請重新整理',409)
        stage=Form(id=number(db,kind),kind=kind,owner=u['id'],parent_id=id,payload=dump({'start':{**data,'submitted_at':iso(now())}}));db.add(stage)
    snapshot(db,f,u);f.status=STATES[idx+1];f.revision+=1;f.updated_at=now();event(db,f,STATE_LABELS[idx]+' → '+STATE_LABELS[idx+1],u)
    db.commit();return form_json(f,db)

@app.get('/api/resources/{id}/records')
def records(id:int,u=Depends(user),db=Depends(getdb)):
    return [{**public_payload(r.payload),'id':r.id,'category':r.category,'created_at':iso(r.created_at)} for r in db.scalars(select(Record).where(Record.resource_id==id,Record.deleted==0).order_by(Record.id.desc()))]
class RecordInput(BaseModel):category:str;data:dict
def validrecord(body):
    body.data = {k:v for k,v in body.data.items() if not k.startswith('_')}
    fields={'insurance':['company','expiry'],'cost':['type','reason','amount'],'maintenance':['type','date'],'garage':[],'manager':['name']}
    if body.category not in fields:fail('無效的記錄類別')
    for key in fields[body.category]:
        if body.data.get(key) in ('',None):fail(f'請填寫必要欄位：{key}')
    if body.category=='insurance':parse(body.data['expiry'])
    if body.category=='maintenance':parse(body.data['date'])
    if body.category=='cost' and body.data.get('type') not in ('insurance','maintenance','repair','保費','保養','維修'):fail('無效的成本類型')
    if body.category=='maintenance' and body.data.get('type') not in ('inspection','maintenance','repair','驗車','定期保養','維修'):fail('無效的維護類型')
    if body.category=='cost':
        try:
            if not math.isfinite(float(body.data['amount'])) or float(body.data['amount'])<0:raise ValueError()
        except (TypeError,ValueError):fail('金額必須為非負數')
@app.post('/api/resources/{id}/records')
def addrecord(id:int,body:RecordInput,u=Depends(admin),db=Depends(getdb)):
    r=db.get(Resource,id)
    if not r or r.deleted or r.kind!='vehicle':fail('找不到有效車輛',404)
    validrecord(body);r=Record(resource_id=id,category=body.category,payload=dump(body.data));db.add(r);db.commit();return {'id':r.id}
@app.put('/api/records/{id}')
def editrecord(id:int,body:RecordInput,u=Depends(admin),db=Depends(getdb)):
    r=db.get(Record,id)
    if not r or r.deleted:fail('找不到記錄',404)
    validrecord(body)
    if r.category!=body.category:fail('不可變更記錄類別')
    r.payload=dump({**json.loads(r.payload),**body.data});db.commit();return {'ok':True}
@app.delete('/api/records/{id}')
def deleterecord(id:int,u=Depends(admin),db=Depends(getdb)):
    r=db.get(Record,id)
    if not r:fail('找不到記錄',404)
    r.deleted=1;db.commit();return {'ok':True}

@app.post('/api/files')
async def upload(request:Request,u=Depends(writer),db=Depends(getdb)):
    # Raw streaming upload keeps filenames separate from disk paths.
    id=str(uuid.uuid4());path=DATA/id;size=0;limit=1024**3 if request.headers.get('x-file-purpose')=='stage-photo' else 10*1024*1024
    try:
        with path.open('wb') as out:
            async for chunk in request.stream():
                size+=len(chunk)
                if size>limit:fail('檔案超過上限：照片 1 GB、一般附件 10 MB',413)
                out.write(chunk)
        from urllib.parse import unquote
        name=Path(unquote(request.headers.get('x-file-name','attachment'))).name[:255]
        mime=request.headers.get('content-type','application/octet-stream')[:150]
        a=Attachment(id=id,name=name,mime=mime,size=size,owner=u['id']);db.add(a);db.commit()
        return {'id':id,'name':name,'size':size,'mime':mime}
    except Exception:
        path.unlink(missing_ok=True);raise
@app.get('/api/files/{id}')
def download(id:str,preview:bool=False,u=Depends(user),db=Depends(getdb)):
    a=db.get(Attachment,id)
    if not a or not (DATA/a.id).exists():fail('找不到附件',404)
    safe=a.mime in ('image/jpeg','image/png','image/webp','image/gif')
    return FileResponse(DATA/a.id,filename=a.name,media_type=a.mime if safe else 'application/octet-stream',content_disposition_type='inline' if preview and safe else 'attachment')

# Feature modules share the same request transaction and stable resource identifiers.
import permissions
import integrations
import stages
permissions.install(globals())
stages.install(globals())
integrations.install(globals())

# The built frontend and API can run on one origin without the Vite dev server.
@app.get('/{path:path}')
def frontend(path:str):
    if path.startswith('api/'):
        fail('找不到 API',404)
    dist=(ROOT/'dist').resolve()
    target=(dist/path).resolve()
    if dist not in target.parents and target!=dist:fail('找不到檔案',404)
    if target.is_file():return FileResponse(target)
    if (dist/'index.html').is_file():return FileResponse(dist/'index.html')
    fail('前端尚未建置，請先執行 npm run build',503)
