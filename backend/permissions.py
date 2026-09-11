"""Versioned AMS policies. Local JSON is the replaceable offline policy source."""
import json
import os
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import Column, Integer, Text, select

DOCS = ['Lending_form','Room_form','Equipment_form','departure_form','departure_arrive','back_form','back_arrive','Submission_query','Room_query','Departure_query','Back_query','HistoryRecords','carMap','CarUpdate','FindMy','Latest_Device','VehicleManagement','Carinformation','Insurance','Cost','EquipmentManagement','EquipmentList','BeaconList','CarList','Administration']
OPS = ['read','write','create','delete','submit','cancel','export','import','print']
KINDS = {'A':'Lending_form','B':'departure_form','C':'back_form','D':'Room_form','E':'Equipment_form'}

def default_policy():
    readonly = {op:int(op=='read') for op in OPS}
    borrow = {op:int(op in ('read','write','create','submit')) for op in OPS}
    forms = {d:{'levels':{'0':dict(readonly)},'fields':{}} for d in DOCS}
    admin = {d:{'levels':{'0':{op:1 for op in OPS}},'fields':{}} for d in DOCS}
    for d in set(KINDS.values()) | {'departure_arrive','back_arrive'}:
        forms[d]['levels']['0']=dict(borrow)
    viewer = {d:{'levels':{'0':dict(readonly)},'fields':{'notes':{'permlevel':1}}} for d in DOCS}
    for d in viewer: viewer[d]['levels']['1']={'read':0,'write':0}
    draft=json.loads(json.dumps(forms))
    for d in draft: draft[d]['levels']['0']['submit']=0
    for group in (forms,viewer,draft,admin):
        group['Administration']['levels']['0']={op:int(group is admin) for op in OPS}
        for d in KINDS.values():
            group[d]['fields'].update({'applicant':{'read':1,'write':0},'application_date':{'read':1,'write':0}})
    return {'module':'AMS','version':1,'roles':{'admin':admin,'borrower':forms,'viewer':viewer,'draft':draft},
            'user_roles':{'demo-admin':['admin'],'demo-borrower':['borrower'],'demo-viewer':['viewer'],'demo-draft':['draft']},
            'ui':{'admin':{'calendar.options.holidayToggle':'Enabled'},'borrower':{'calendar.options.holidayToggle':'Visible'},'viewer':{'calendar.options.holidayToggle':'Hidden'},'draft':{'calendar.options.holidayToggle':'Disabled'}}}

def validate(policy):
    if policy.get('module')!='AMS' or not isinstance(policy.get('version'),int) or policy['version']<1 or not isinstance(policy.get('roles'),dict) or not isinstance(policy.get('user_roles'),dict):
        raise HTTPException(422,'權限政策必須包含 AMS、正整數版本、roles 與 user_roles')
    for role,forms in policy['roles'].items():
        if not isinstance(forms,dict):raise HTTPException(422,'角色表單格式錯誤')
        for doc,rule in forms.items():
            if not isinstance(rule,dict) or not isinstance(rule.get('levels',{}),dict):raise HTTPException(422,'層級格式錯誤')
            for ops in rule.get('levels',{}).values():
                if not isinstance(ops,dict) or any(v not in (0,1,False,True) for k,v in ops.items() if k in OPS):raise HTTPException(422,'權限動作必須為 0 或 1')
    return policy

def source():
    path=os.getenv('AMS_POLICY_FILE')
    return validate(json.loads(Path(path).read_text())) if path else default_policy()

def synchronize(db):
    policy=source(); version=policy['version']
    active=db.scalar(select(Policy).where(Policy.active==1))
    if active and version<active.version:raise HTTPException(409,'不可回退權限版本')
    old=db.get(Policy,version)
    if old and json.loads(old.payload)!=policy:raise HTTPException(409,'既有版本內容不可覆寫，請增加版本')
    for p in db.scalars(select(Policy)):p.active=0
    if old:old.active=1
    else:db.add(Policy(version=version,payload=json.dumps(policy),active=1))
    db.flush()
    for p in db.scalars(select(Policy).order_by(Policy.version.desc())).all()[5:]:db.delete(p)
    return version

def seed(db):
    if not db.scalar(select(Policy).where(Policy.active==1)):
        try:synchronize(db)
        except (OSError,ValueError):pass

def effective(db,u):
    row=db.scalar(select(Policy).where(Policy.active==1))
    if not row:
        seed(db);row=db.scalar(select(Policy).where(Policy.active==1))
    if not row:raise HTTPException(403,'權限不足：没有有效政策快照，請同步權限')
    return effective_policy(json.loads(row.payload), u)

def effective_policy(policy, u):
    roles=policy['user_roles'].get(u['id'],[])
    result={'module':'AMS','version':policy['version'],'roles':roles,'forms':{},'fields':{},'ui':{},'levels':{},'allow_list':{},'owner_only':{}}
    for doc in DOCS:
        rules=[policy['roles'].get(r,{}).get(doc,{}) for r in roles]
        levels={str(level):{op:int(any(rule.get('levels',{}).get(str(level),{}).get(op,0) for rule in rules)) for op in OPS} for level in set(['0']+[str(k) for rule in rules for k in rule.get('levels',{})])}
        result['levels'][doc]=levels
        result['forms'][doc]=levels['0']
        fields={}
        for name in set(k for rule in rules for k in rule.get('fields',{})):
            permissions=[]
            for rule in rules:
                field=rule.get('fields',{}).get(name,{})
                base=rule.get('levels',{}).get(str(field.get('permlevel',0)),{})
                permissions.append({op:int(field.get(op,base.get(op,0))) for op in ('read','write')})
            fields[name]={op:int(any(p[op] for p in permissions)) for op in ('read','write')}
        result['fields'][doc]=fields
        dims={}
        for rule in rules:
            for key,values in rule.get('allow_list',{}).items():
                dims[key]=list(dict.fromkeys(dims.get(key,[])+values))
        result['allow_list'][doc]=dims
        result['owner_only'][doc]={op:bool([r for r in rules if r.get('levels',{}).get('0',{}).get(op)]) and all(r.get('if_owner',r.get('levels',{}).get('0',{}).get('if_owner',False)) for r in rules if r.get('levels',{}).get('0',{}).get(op)) for op in OPS}
    priority={'Disabled':0,'Hidden':1,'Visible':2,'Enabled':3}
    for key in set(k for r in roles for k in policy.get('ui',{}).get(r,{})):
        result['ui'][key]=max((policy.get('ui',{}).get(r,{}).get(key,'Disabled') for r in roles),key=lambda x:priority.get(x,0))
    return result

def require(u,doc,*ops):
    for op in ops:
        if not u['permissions']['forms'].get(doc,{}).get(op):raise HTTPException(403,f'權限不足：{doc} 缺少 {op}，請返回首頁')

def redact(value,fields):
    if isinstance(value,list):return [redact(v,fields) for v in value]
    if isinstance(value,dict):return {k:redact(v,fields) for k,v in value.items() if fields.get(k,{}).get('read',1)}
    return value

def check_fields(value,old,fields):
    if isinstance(value,list):
        for i,v in enumerate(value):check_fields(v,old[i] if isinstance(old,list) and i<len(old) else {},fields)
    elif isinstance(value,dict):
        for key,v in value.items():
            rule=fields.get(key)
            previous=old.get(key) if isinstance(old,dict) else None
            if rule and not rule.get('write',0) and v!=previous and not (previous is None and v in (None,'',[])):raise HTTPException(403,f'權限不足：欄位 {key} 為唯讀或不可見')
            check_fields(v,previous,fields)

async def authorize(request,db,u):
    path=request.url.path;method=request.method;parts=path.strip('/').split('/')
    body={}
    if method in ('POST','PUT','PATCH') and path!='/api/files':
        raw=await request.body()
        try:body=json.loads(raw) if raw else {}
        except ValueError:raise HTTPException(422,'請提供有效 JSON')
        if body is None:body={}
        if not isinstance(body,dict):raise HTTPException(422,'請提供 JSON 物件')
    f=None;doc=None;old={};ops=['read'] if method=='GET' else [{'POST':'create','PUT':'write','PATCH':'write','DELETE':'delete'}.get(method,'read')]
    if path.startswith('/api/bookings'):
        f=db.get(Form,parts[2]) if len(parts)>2 and parts[2]!='check' else None
        doc=KINDS.get(f.kind if f else body.get('kind','A'),'Lending_form')
        if f:old=json.loads(f.payload)
        else:old={'applicant':u['name'],'application_date':now().date().isoformat()}
        if path.endswith('/advance') and f:
            doc={'PENDING':'departure_form','DEPARTURE':'departure_arrive','DEPARTURE_ARRIVED':'back_form','RETURN':'back_arrive'}.get(f.status,'back_arrive')
            ops=['write'] if f.status in ('DEPARTURE','RETURN') else ['create']
        elif method=='POST' and body.get('kind') in ('A','E'):ops=['create','submit']
    elif path.startswith('/api/stages'):
        f=db.get(Form,parts[2]) if len(parts)>2 else None
        doc=KINDS.get(f.kind if f else request.query_params.get('kind','B'),'departure_form')
        if f:old=json.loads(f.payload)
    elif path.startswith('/api/resources'):
        r=db.get(Resource,int(parts[2])) if len(parts)>2 and parts[2].isdigit() else None
        doc='EquipmentManagement' if (r.kind if r else body.get('kind'))=='equipment' else 'VehicleManagement'
        if r:old=json.loads(r.payload)
        if path.endswith('/records'):doc='Insurance' if body.get('category')=='insurance' else 'Cost'
    elif path.startswith('/api/records'):
        record=db.get(Record,int(parts[2])) if len(parts)>2 and parts[2].isdigit() else None
        doc='Insurance' if record and record.category=='insurance' else 'Cost'
        if record:old=json.loads(record.payload)
    elif path.startswith('/api/beacons'):doc='BeaconList'
    elif path.startswith('/api/findmy'):doc='FindMy'
    elif path.startswith('/api/trajectory'):doc='carMap'
    elif path.startswith('/api/positions'):doc='CarUpdate'
    elif path.startswith('/api/scans') or path=='/api/stations':doc='Latest_Device'
    elif path.startswith('/api/reports') or path.endswith('/sync') or path=='/api/notifications':doc='Administration';ops=['read'] if method=='GET' else ['write']
    if doc:
        require(u,doc,*ops)
        if f and any(u['permissions'].get('owner_only',{}).get(doc,{}).get(op) for op in ops) and f.owner!=u['id']:raise HTTPException(403,'權限不足：僅允許操作自己的資料')
        if method in ('PUT','POST','PATCH'):
            fields=u['permissions']['fields'].get(doc,{})
            check_fields(body.get('content',body.get('data',body)),old,fields)
        request.state.permission_doc=doc
    request.state.permission_user=u

def install(ctx):
    global Policy
    for name in ('Base','app','Form','Resource','Record','now','getdb','user','admin','Depends','Request'):
        globals()[name]=ctx[name]
    class Policy(ctx['Base']):
        __tablename__='ams_preview_policies'
        version=Column(Integer,primary_key=True)
        payload=Column(Text,nullable=False)
        active=Column(Integer,default=0,nullable=False)
    @app.get('/api/permissions')
    def get_permissions(u=Depends(user)):return u['permissions']
    @app.post('/api/permissions/check')
    async def check(request:Request,u=Depends(user),db=Depends(getdb)):
        body=await request.json()
        username=body.get('username',u['email'])
        target=next((v for v in ctx['USERS'].values() if username in (v['email'],v['id'])),None)
        if not target:raise HTTPException(404,'找不到測試使用者')
        if target['id']!=u['id']:require(u,'Administration','read')
        effective_policy=effective(db,target);results=[]
        for check in body.get('checks',[]):
            doc=check.get('doctype','');typ=check.get('type','form')
            if check.get('module','AMS')!='AMS':raise HTTPException(422,'未知權限模組')
            if typ=='ui':
                state=effective_policy['ui'].get(check.get('key'),'Disabled')
                result={'state':state,'allow':state in ('Enabled','Visible')}
            else:
                result={'allow':all(effective_policy['forms'].get(doc,{}).get(op,0) for op in check.get('ops',['read'])),'module':'AMS','doctype':doc,'version':effective_policy['version'],'roles':effective_policy['roles'],'levels':effective_policy['levels'].get(doc,{}),'fields':effective_policy['fields'].get(doc,{}),'allow_list':effective_policy['allow_list'].get(doc,{})}
            results.append({'ok':True,'type':typ,'source':'local','result':result})
        return {'ok':True,'results':results}
    @app.get('/api/permissions/health')
    def health(u=Depends(user)):return {'ok':True,'active_version':u['permissions']['version'],'source':'local snapshot'}
    @app.post('/api/permissions/sync')
    def sync(u=Depends(admin),db=Depends(getdb)):
        try:version=synchronize(db);db.commit();return {'ok':True,'version':version}
        except (OSError,ValueError) as e:raise HTTPException(503,'政策來源無法讀取；保留最後成功版本') from e
