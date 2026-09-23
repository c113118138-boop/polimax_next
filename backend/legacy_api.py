"""The new UI's API over the existing POLIMAX storage contract."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
import httpx
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, Depends, Request, Response, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text, update
from sqlalchemy.exc import SQLAlchemyError
import permissions
from sso import SSO, settings
from legacy_store import Store, REASONS, E_REASONS, STATES, CHECKS_B, CHECKS_C, iso, now, dump, fail

USERS={
 'admin':{'id':'demo-admin','name':'林品安','email':'admin@example.test','role':'admin','role_label':'測試管理員'},
 'borrower':{'id':'demo-borrower','name':'陳予晴','email':'borrower@example.test','role':'borrower','role_label':'測試借用人'},
 'draft':{'id':'demo-draft','name':'測試草稿員','email':'draft@example.test','role':'draft','role_label':'可新增但不可送出'},
 'viewer':{'id':'demo-viewer','name':'周以恆','email':'viewer@example.test','role':'viewer','role_label':'測試唯讀使用者'},
}
class LoginInput(BaseModel): role:str
class ResourceInput(BaseModel):
    kind:str
    label:str=Field(default='',max_length=200)
    data:dict
class BookingInput(BaseModel):
    kind:str
    content:dict
    revision:int|None=None
class RecordInput(BaseModel): category:str;data:dict
class StageInput(BaseModel): expected_status:str;content:dict;revision:int
class EditStage(BaseModel): content:dict;revision:int

def create_app(root,data,url):
    auth_config=settings(root)
    test_auth=auth_config.get("AMS_AUTH_MODE", "sso") == "test"
    sso=SSO(root,data)
    engine=create_engine(url,pool_pre_ping=True,hide_parameters=True,isolation_level='READ COMMITTED',connect_args={'connect_timeout':10})
    database_label='PostgreSQL' if engine.dialect.name=='postgresql' else 'MySQL'
    data.mkdir(parents=True,exist_ok=True)
    key_path=data/'session.key'
    try:
        with key_path.open('xb') as output:
            os.chmod(key_path,0o600);output.write(secrets.token_bytes(32))
    except FileExistsError:pass
    key=key_path.read_bytes()
    @asynccontextmanager
    async def lifespan(app):
        # Reflect only. Application credentials never require CREATE or ALTER.
        app.state.store=Store(engine,root,data)
        app.state.policy=permissions.source() if test_auth else None
        try:
            with sso.session_cleanup():
                yield
        finally:
            engine.dispose()
    app=FastAPI(title='POLIMAX API',lifespan=lifespan)
    app.state.engine=engine
    app.state.sso=sso
    if not test_auth:sso.install(app)
    @app.get("/api/auth/config")
    def auth_settings():
        return {"mode":"test" if test_auth else "sso", "configured":test_auth or sso.configured, "login_url":"/api/auth/sso"}
    def policy():return getattr(app.state,'policy',None) or permissions.source()
    def current(request:Request):
        if not test_auth:return sso.current(request)
        token=request.cookies.get('ams_preview_session','')
        try:
            payload,signature=token.rsplit('.',1)
            expected=hmac.new(key,payload.encode(),hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature,expected):raise ValueError()
            record=json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))
            if record['expires']<time.time() or record['role'] not in USERS:raise ValueError()
        except (ValueError,KeyError,TypeError):fail('登入已失效，請重新登入',401)
        user=dict(USERS[record['role']]);user['permissions']=permissions.effective_policy(policy(),user)
        return user
    def check(user,doc,*ops,body=None,old=None,owner=None):
        permissions.require(user,doc,*ops)
        if owner is not None and owner!=user['id'] and any(user['permissions']['owner_only'].get(doc,{}).get(op) for op in ops):fail('僅能操作自己的資料',403)
        if body is not None:permissions.check_fields(body,old or {},user['permissions']['fields'].get(doc,{}))
    def redact(user,doc,value):return permissions.redact(value,user['permissions']['fields'].get(doc,{}))
    def store():return app.state.store
    @app.middleware('http')
    async def errors(request,call_next):
        if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('x-ams-client')!='preview':
            return JSONResponse({'detail':'缺少有效的操作來源標記'},status_code=403)
        try:response=await call_next(request)
        except SQLAlchemyError:
            response=JSONResponse({'detail':database_label+' 操作失敗，變更未儲存；請檢查連線或欄位限制。'},status_code=503)
        except OSError:
            response=JSONResponse({'detail':'無法讀寫舊表單或附件目錄，變更未完成。'},status_code=503)
        response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff'
        return response
    @app.get('/api/health')
    def health():
        with engine.connect() as c:c.execute(text('SELECT 1'))
        return {'ok':True,'database':database_label,'mode':'legacy','test_data':False,'storage':'existing_tables_and_legacy_json','schema_changes_required':False}
    @app.post('/api/auth/login')
    def login(body:LoginInput,response:Response):
        if not test_auth or auth_config.get('PREVIEW_LOGIN_ENABLED','0')!='1':fail('本地測試登入已關閉',403)
        if body.role not in USERS:fail('無效使用者')
        payload=base64.urlsafe_b64encode(dump({'role':body.role,'expires':time.time()+43200,'nonce':secrets.token_hex(8)}).encode()).decode().rstrip('=')
        signature=hmac.new(key,payload.encode(),hashlib.sha256).hexdigest()
        response.set_cookie('ams_preview_session',payload+'.'+signature,httponly=True,samesite='lax',max_age=43200)
        user=dict(USERS[body.role]);user['permissions']=permissions.effective_policy(policy(),user);return user
    @app.get('/api/auth/me')
    def me(user=Depends(current)):return user
    @app.post('/api/auth/logout')
    def logout(request:Request,response:Response):
        if not test_auth:return sso.logout(request,response)
        response.delete_cookie('ams_preview_session');return {'ok':True}
    @app.get('/api/permissions')
    def get_permissions(user=Depends(current)):return user['permissions']
    @app.get('/api/permissions/health')
    def policy_health(user=Depends(current)):
        check(user,'Administration','read')
        return {'version':user['permissions']['version'],'source':'local-policy' if test_auth or sso.config.get('AMS_POLICY_FILE') else 'project-AMS-snapshot','test_data':False,'available':True}
    @app.post('/api/permissions/sync')
    def sync(user=Depends(current)):
        check(user,'Administration','write')
        if not test_auth:return {'version':sso.with_permissions(user)['permissions']['version']}
        app.state.policy=permissions.source();return {'version':policy()['version']}
    @app.get('/api/options')
    def options(user=Depends(current)):
        import integrations
        employees=[user['name']]
        return {**integrations.options(),'employees':employees,'reasons':REASONS,'equipment_reasons':E_REASONS,'test_data':False}
    @app.get('/api/resources')
    def resources(user=Depends(current)):
        result=[]
        with store().session() as repo:
            for r in repo.resources():
                doc='EquipmentManagement' if r['kind']=='equipment' else 'VehicleManagement'
                if user['permissions']['forms'][doc]['read']:result.append(redact(user,doc,r))
        return result
    @app.post('/api/resources')
    def add_resource(body:ResourceInput,user=Depends(current)):
        doc='EquipmentManagement' if body.kind=='equipment' else 'VehicleManagement';check(user,doc,'create',body=body.data)
        with store().session(True) as repo:result=repo.save_resource(body.model_dump())
        return result
    @app.put('/api/resources/{rid}')
    def edit_resource(rid:int,body:ResourceInput,user=Depends(current)):
        with store().session(True) as repo:
            old=repo.resource(rid);doc='EquipmentManagement' if old['kind']=='equipment' else 'VehicleManagement'
            check(user,doc,'write',body=body.data,old=old);result=repo.save_resource(body.model_dump(),rid)
        return result
    @app.delete('/api/resources/{rid}')
    def delete_resource(rid:int,user=Depends(current)):
        with store().session(True) as repo:
            old=repo.resource(rid);check(user,'EquipmentManagement' if old['kind']=='equipment' else 'VehicleManagement','delete');repo.delete_resource(rid)
        return {'ok':True}
    @app.get('/api/resources/{rid}/records')
    def records(rid:int,user=Depends(current)):
        check(user,'VehicleManagement','read')
        with store().session() as repo:result=repo.records(rid)
        return [redact(user,'Insurance' if r['category']=='insurance' else 'Cost',r) for r in result]
    @app.post('/api/resources/{rid}/records')
    def add_record(rid:int,body:RecordInput,user=Depends(current)):
        check(user,'Insurance' if body.category=='insurance' else 'Cost','create',body=body.data)
        with store().session(True) as repo:result=repo.save_record(rid,body.model_dump())
        return result
    @app.put('/api/records/{ident}')
    def edit_record(ident:int,body:RecordInput,user=Depends(current)):
        with store().session(True) as repo:
            cat,_,fields,row=repo.record_location(ident);check(user,'Insurance' if cat=='insurance' else 'Cost','write',body=body.data,old=repo.decode_fields(row,fields))
            result=repo.save_record(None,body.model_dump(),ident)
        return result
    @app.delete('/api/records/{ident}')
    def delete_record(ident:int,user=Depends(current)):
        with store().session(True) as repo:
            cat,_,_,_=repo.record_location(ident);check(user,'Insurance' if cat=='insurance' else 'Cost','delete');repo.delete_record(ident)
        return {'ok':True}
    @app.get('/api/bookings')
    def bookings(user=Depends(current)):
        with store().session() as repo:result=repo.bookings()
        return [redact(user,permissions.KINDS[r['kind']],r) for r in result if user['permissions']['forms'][permissions.KINDS[r['kind']]]['read']]
    @app.post('/api/bookings/check')
    def check_booking(body:BookingInput,user=Depends(current)):
        check(user,permissions.KINDS.get(body.kind,'Lending_form'),'create')
        with store().session(True) as repo:repo.validate_booking(body.model_dump())
        return {'ok':True}
    @app.post('/api/bookings')
    def add_booking(body:BookingInput,user=Depends(current)):
        check(user,permissions.KINDS.get(body.kind,'Lending_form'),'create','submit',body=body.content,old={'applicant':user['name'],'application_date':now().date().isoformat()})
        with store().session(True) as repo:result=repo.save_booking(body.model_dump(),user)
        return result
    @app.get('/api/bookings/{fid}')
    def booking(fid:str,user=Depends(current)):
        with store().session() as repo:
            result=repo.detail(fid);doc=permissions.KINDS[result['kind']];check(user,doc,'read',owner=result['owner'])
        return redact(user,doc,result)
    @app.put('/api/bookings/{fid}')
    def edit_booking(fid:str,body:BookingInput,user=Depends(current)):
        with store().session(True) as repo:
            old=repo.booking(fid);check(user,permissions.KINDS[old['kind']],'write',body=body.content,old=old['content'],owner=old['owner'])
            result=repo.save_booking(body.model_dump(),user,fid)
        return result
    @app.delete('/api/bookings/{fid}')
    def delete_booking(fid:str,user=Depends(current)):
        with store().session(True) as repo:
            old=repo.booking(fid);check(user,permissions.KINDS[old['kind']],'delete',owner=old['owner']);repo.delete_booking(fid)
        return {'ok':True}
    @app.post('/api/bookings/{fid}/advance')
    def advance(fid:str,body:StageInput,user=Depends(current)):
        with store().session(True) as repo:
            old=repo.booking(fid);doc={'PENDING':'departure_form','DEPARTURE':'departure_arrive','DEPARTURE_ARRIVED':'back_form','RETURN':'back_arrive'}.get(old['status'],'back_arrive')
            check(user,doc,'write' if old['status'] in ('DEPARTURE','RETURN') else 'create',owner=old['owner'])
            result=repo.advance(fid,body.model_dump(),user)
        return result
    @app.get('/api/stages')
    def stages(kind:str='B',user=Depends(current)):
        doc=permissions.KINDS.get(kind,'departure_form');check(user,doc,'read')
        with store().session() as repo:result=repo.stages(kind)
        return redact(user,doc,result)
    @app.get('/api/stages/{fid}')
    def stage(fid:str,user=Depends(current)):
        with store().session() as repo:result=repo.stage(fid)
        doc=permissions.KINDS[result['kind']];check(user,doc,'read');return redact(user,doc,result)
    @app.put('/api/stages/{fid}')
    def edit_stage(fid:str,body:EditStage,user=Depends(current)):
        with store().session(True) as repo:
            old=repo.stage(fid);check(user,permissions.KINDS[old['kind']],'write',body=body.content,old=old['content'],owner=old['owner']);result=repo.edit_stage(fid,body.model_dump(),user)
        return result
    @app.delete('/api/stages/{fid}')
    def delete_stage(fid:str,user=Depends(current)):
        with store().session(True) as repo:
            old=repo.stage(fid);check(user,permissions.KINDS[old['kind']],'delete',owner=old['owner']);raw=repo.raw(fid);raw['is_deleted']=True;repo.save_json(fid,raw)
        return {'ok':True}
    @app.post('/api/files')
    async def upload(request:Request,user=Depends(current)):
        if not any(v.get('create') for v in user['permissions']['forms'].values()):fail('沒有上傳權限',403)
        ident=str(uuid.uuid4());path=store().files/ident;size=0
        limit=1024**3 if request.headers.get('x-file-purpose')=='stage-photo' else 10*1024*1024
        try:
            with path.open('xb') as out:
                os.chmod(path,0o600)
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>limit:fail('附件超過上限',413)
                    out.write(chunk)
                out.flush();os.fsync(out.fileno())
            meta={'id':ident,'name':Path(unquote(request.headers.get('x-file-name','attachment'))).name[:255],'mime':request.headers.get('content-type','application/octet-stream'),'size':size,'owner':user['id']}
            # Files and metadata belong to this deployment; never call the old service.
            meta['uuid']=ident
            metadata=store().files/(ident+'.json')
            temporary=metadata.with_suffix('.tmp')
            try:
                with temporary.open('x',encoding='utf-8') as out:
                    json.dump(meta,out,ensure_ascii=False);out.flush();os.fsync(out.fileno())
                os.replace(temporary,metadata)
            finally:temporary.unlink(missing_ok=True)
            return meta
        except BaseException:path.unlink(missing_ok=True);raise
    @app.get('/api/files/{ident}')
    def file(ident:str,preview:bool=False,user=Depends(current)):
        import re
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',ident):fail('無效附件識別碼',404)
        meta_path=store().files/(ident+'.json');path=store().files/ident
        if not path.exists():fail('附件尚未搬入新版或不存在',404)
        if not meta_path.exists():fail('找不到附件資訊',404)
        meta=json.loads(meta_path.read_text());safe=meta['mime'] in ('image/jpeg','image/png','image/webp','image/gif')
        return FileResponse(path,filename=meta['name'],media_type=meta['mime'] if safe else 'application/octet-stream',content_disposition_type='inline' if preview and safe else 'attachment')
    from legacy_integrations import install
    install(app,store,current,check)
    @app.get('/{path:path}')
    def frontend(path:str):
        if path.startswith('api/'):fail('找不到 API',404)
        dist=(root/'dist').resolve();target=(dist/path).resolve()
        if dist not in target.parents and target!=dist:fail('找不到檔案',404)
        if target.is_file():return FileResponse(target)
        if (dist/'index.html').is_file():return FileResponse(dist/'index.html')
        fail('前端尚未建置',503)
    return app
