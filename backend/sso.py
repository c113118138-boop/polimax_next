"""SSO authorization-code login with server-side credentials and existing AMS roles."""
import fcntl
import hashlib
import json
import logging
import os
import secrets
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from threading import Event, Thread
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
from dotenv import dotenv_values
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
import permissions
from settings import local_path


def settings(root):
    return {**dotenv_values(root/'env'), **dotenv_values(root/'.env'), **os.environ}

def enabled(value): return value in (True, 1, '1', 'true', 'True')

class RedactSSOQueries(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args=list(record.args)
            if isinstance(args[2],str) and args[2].split('?')[0] in ('/api/callback','/api/auth/sso/callback'):
                args[2]=args[2].split('?')[0];record.args=tuple(args)
        return True

def safe_return(value):
    return value if isinstance(value,str) and value.startswith('/') and not value.startswith('//') and not any(c in value for c in ('\\','\r','\n')) and len(value)<2000 else '/'

class SSO:
    def __init__(self,root,data):
        self.root=root;self.config=settings(root)
        logging.getLogger('uvicorn.access').addFilter(RedactSSOQueries())
        self.server=self.config.get('SSO_SERVER','').rstrip('/')
        self.public=self.config.get('PUBLIC_WEB_URL','').rstrip('/')
        self.callback=self.config.get('SSO_REDIRECT_URI') or self.public+'/api/callback'
        self.client_id=self.config.get('SSO_CLIENT_ID','');self.secret=self.config.get('SSO_CLIENT_SECRET','')
        self.secure=urlsplit(self.public).scheme=='https'
        self.directory=data/'sso';self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        os.chmod(self.directory,0o700)
        self.cookie='polimax_session';self.state_cookie='polimax_sso_state'
    @staticmethod
    def next_cleanup_at(now):
        local = datetime.fromtimestamp(now, ZoneInfo('Asia/Taipei'))
        return (local.replace(hour=0, minute=0, second=0, microsecond=0)
                + timedelta(days=1)).timestamp()

    def cleanup_expired_sessions(self, now=None):
        cutoff = time.time() if now is None else now
        removed = 0
        for path in self.directory.glob('session-*.json'):
            # Use the same lock as current()/logout(); keep lock files so
            # concurrent processes never lock different inodes for a session.
            try:
                with path.with_suffix('.lock').open('a') as handle:
                    os.chmod(handle.name, 0o600)
                    fcntl.flock(handle, fcntl.LOCK_EX)
                    if not path.exists():
                        continue
                    record = json.loads(path.read_text())
                    expiry = record.get('expires')
                    if isinstance(expiry, (int, float)) and expiry <= cutoff:
                        path.unlink(missing_ok=True)
                        removed += 1
            except (OSError, ValueError, TypeError, AttributeError):
                logging.getLogger(__name__).warning('Could not clean session file %s', path.name)
        return removed

    @contextmanager
    def session_cleanup(self):
        stop = Event()

        def run():
            deadline = self.next_cleanup_at(time.time())
            while not stop.wait(min(60, max(0, deadline - time.time()))):
                if time.time() < deadline:
                    continue
                try:
                    count = self.cleanup_expired_sessions()
                    logging.getLogger(__name__).info('Expired session cleanup: %d removed', count)
                except Exception:
                    logging.getLogger(__name__).exception('Session cleanup failed')
                deadline = self.next_cleanup_at(time.time())

        worker = Thread(target=run, name='sso-session-cleanup', daemon=True)
        worker.start()
        try:
            yield
        finally:
            stop.set()
            worker.join(timeout=5)

    @property
    def configured(self):
        return bool(self.client_id and self.secret and urlsplit(self.server).scheme in ('http','https') and urlsplit(self.public).netloc)
    def path(self,token,kind):
        if not isinstance(token,str) or len(token)!=64 or any(c not in '0123456789abcdef' for c in token):raise HTTPException(401,'請重新登入')
        return self.directory/(kind+'-'+hashlib.sha256(token.encode()).hexdigest()+'.json')
    def write(self,path,record):
        temp=path.with_name('.'+secrets.token_hex(16))
        try:
            with temp.open('x',encoding='utf-8') as out:
                os.chmod(temp,0o600);json.dump(record,out,ensure_ascii=False);out.flush();os.fsync(out.fileno())
            os.replace(temp,path)
        finally:temp.unlink(missing_ok=True)
    def read(self,path):
        try:return json.loads(path.read_text())
        except (OSError,ValueError):raise HTTPException(401,'登入已失效，請重新登入')
    def cookie_set(self,response,name,value,age):
        response.set_cookie(name,value,max_age=age,httponly=True,secure=self.secure,samesite='lax',path='/')
    def start(self,return_to='/'):
        if not self.configured:raise HTTPException(503,'SSO 設定不完整')
        state=secrets.token_hex(32)
        self.write(self.path(state,'state'),{'expires':time.time()+600,'return_to':safe_return(return_to)})
        params={'response_type':'code','client_id':self.client_id,'redirect_uri':self.callback,'scope':'openid','state':state}
        response=RedirectResponse(self.server+'/authorize?'+urlencode(params),status_code=303)
        self.cookie_set(response,self.state_cookie,state,600)
        return response
    def request_tokens(self,**body):
        try:
            with httpx.Client(timeout=15,follow_redirects=False) as client:
                result=client.post(self.server+'/token',data={**body,'client_id':self.client_id,'client_secret':self.secret})
            result.raise_for_status();data=result.json()
            if not isinstance(data,dict):raise ValueError()
            if not isinstance(data.get('access_token'),str) or not data['access_token']:raise ValueError()
            return data
        except (httpx.HTTPError,ValueError,TypeError):raise HTTPException(502,'SSO 驗證暫時失敗，請重新登入')
    def userinfo(self,token):
        try:
            with httpx.Client(timeout=15,follow_redirects=False) as client:
                response=client.get(self.server+'/userinfo',headers={'Authorization':'Bearer '+token})
            if response.status_code in (401,403):raise HTTPException(401,'SSO 登入已失效')
            response.raise_for_status();data=response.json()
            if not isinstance(data,dict):raise ValueError()
            ident=data.get('sub') or data.get('id') or data.get('email') or data.get('username')
            if not ident:raise ValueError()
            return {'id':str(ident),'name':str(data.get('name') or data.get('full_name') or data.get('username') or data.get('email') or ident),'email':str(data.get('email') or ''),'username':str(data.get('username') or '')}
        except (httpx.HTTPError,ValueError,TypeError):raise HTTPException(502,'無法取得 SSO 使用者資料')
    def with_permissions(self,identity):
        config=self.config
        if config.get('AMS_POLICY_FILE'):
            try:policy=permissions.validate(json.loads(local_path(self.root, config['AMS_POLICY_FILE']).read_text()))
            except (OSError,ValueError):raise HTTPException(503,'無法讀取 AMS 權限政策')
            import copy
            policy=copy.deepcopy(policy)
            roles=[]
            for key in (identity['id'],identity['email'],identity.get('username','')):roles.extend(policy['user_roles'].get(key,[]))
            policy['user_roles'][identity['id']]=list(dict.fromkeys(roles))
        else:
            manifest=local_path(self.root, config.get('AMS_SSO_POLICY_MANIFEST') or str(self.directory.parent/'permissions/latest-AMS.json'))
            try:
                meta=json.loads(manifest.read_text());snapshot=json.loads((manifest.parent/Path(meta['file']).name).read_text())
                source=snapshot['data']
            except (OSError,ValueError,KeyError,TypeError):raise HTTPException(503,'原 AMS 權限快照無法讀取')
            aliases={identity['id'],identity['email'],identity.get('username','')}-{''}
            enabled_users={str(u['name']):u for u in source.get('users',[]) if enabled(u.get('enabled',0))}
            matches=aliases & enabled_users.keys()
            if not matches:raise HTTPException(403,'此 SSO 帳號尚未在 AMS 啟用')
            active={r['name'] for r in source.get('roles',[]) if enabled(r.get('activate',0))}
            roles=list(dict.fromkeys(r['role'] for r in source.get('userRoles',[]) if r['user'] in matches and r['role'] in active))
            policy={'module':'AMS','version':snapshot['meta']['version'],'roles':{},'user_roles':{identity['id']:roles},'ui':{}}
            for role in roles:
                docs={}
                for row in source.get('rolePermissions',[]):
                    if row.get('module')!='AMS' or row.get('role')!=role:continue
                    doc=docs.setdefault(row['parent'],{'levels':{},'fields':{}})
                    doc['levels'][str(row.get('permlevel',0))]={op:int(enabled(row.get(op,0))) for op in permissions.OPS+['if_owner']}
                for row in source.get('docFields',[]):
                    if row.get('module')!='AMS' or row['parent'] not in docs:continue
                    field={'permlevel':row.get('permlevel',0)}
                    name=row['fieldname'];docs[row['parent']]['fields'][name]=field
                    alias={'applicantID':'applicant','RequireOption_Memo':'notes','panelTableText':'mileage','page2Table8Text':'mileage','page1Text':'mileage','car_type':'model','license_plate':'label','equipment_name':'name','equipment_loc':'location'}.get(name)
                    if alias:docs[row['parent']]['fields'][alias]=field
                for doc in permissions.KINDS.values():
                    if doc in docs:docs[doc]['fields'].update({'applicant':{'read':1,'write':0},'application_date':{'read':1,'write':0}})
                policy['roles'][role]=docs
                policy['ui'][role]={str(r['component_id']):r['permission_state'] for r in source.get('uiPermissions',[]) if r.get('rolename')==role and r.get('module')=='AMS'}
            # Existing user restrictions cannot be silently widened by the adapter.
            if any(str(row.get('user','')) in matches for row in source.get('userPermissions',[])):
                raise HTTPException(403,'此帳號含個別資料限制，請先完成 AMS 限制設定對應')
            if identity['name'] in aliases:
                identity={**identity,'name':next((enabled_users[k].get('full_name') for k in matches if enabled_users[k].get('full_name')),identity['name'])}
        effective=permissions.effective_policy(policy,identity)
        return {**identity,'role':','.join(effective['roles']),'role_label':'、'.join(effective['roles']) or '未授權','permissions':effective,'auth_source':'sso'}
    def callback_response(self,request,code=None,state=None,error=None):
        try:
            expected=request.cookies.get(self.state_cookie,'')
            if not state or not expected or not secrets.compare_digest(state,expected):raise HTTPException(400,'SSO 狀態驗證失敗')
            path=self.path(state,'state');used=path.with_suffix('.used')
            try:os.rename(path,used)
            except OSError:raise HTTPException(400,'SSO 授權已使用或已過期')
            try:record=self.read(used)
            finally:used.unlink(missing_ok=True)
            if record['expires']<time.time() or error or not code:raise HTTPException(400,'SSO 登入取消或授權已過期')
            tokens=self.request_tokens(grant_type='authorization_code',code=code,redirect_uri=self.callback)
            identity=self.userinfo(tokens['access_token']);self.with_permissions(identity)
            token=secrets.token_hex(32)
            self.write(self.path(token,'session'),{'identity':identity,'access_token':tokens['access_token'],'refresh_token':tokens.get('refresh_token',''),'checked_at':time.time(),'expires':time.time()+43200})
            response=RedirectResponse(self.public+safe_return(record['return_to']),status_code=303)
            self.cookie_set(response,self.cookie,token,43200)
        except HTTPException as exc:
            response=RedirectResponse(self.public+'/?'+urlencode({'sso_error':exc.detail}),status_code=303)
        response.delete_cookie(self.state_cookie,path='/');response.headers['Referrer-Policy']='no-referrer'
        return response
    def current(self,request):
        token=request.cookies.get(self.cookie,'');path=self.path(token,'session')
        if not path.is_file():raise HTTPException(401,'登入已失效，請重新登入')
        lock=path.with_suffix('.lock')
        with lock.open('a') as handle:
            os.chmod(lock,0o600);fcntl.flock(handle,fcntl.LOCK_EX)
            record=self.read(path)
            if record['expires']<time.time():path.unlink(missing_ok=True);raise HTTPException(401,'登入已過期')
            if time.time()-record['checked_at']>60:
                try:identity=self.userinfo(record['access_token'])
                except HTTPException as exc:
                    if exc.status_code!=401:raise
                    if not record.get('refresh_token'):path.unlink(missing_ok=True);raise
                    try:
                        tokens=self.request_tokens(grant_type='refresh_token',refresh_token=record['refresh_token'])
                        identity=self.userinfo(tokens['access_token'])
                    except HTTPException:
                        path.unlink(missing_ok=True);raise HTTPException(401,'SSO 登入已失效，請重新登入')
                    record.update(access_token=tokens['access_token'],refresh_token=tokens.get('refresh_token') or record['refresh_token'])
                if identity['id']!=record['identity']['id']:path.unlink(missing_ok=True);raise HTTPException(401,'SSO 身分已變更，請重新登入')
                record.update(identity=identity,checked_at=time.time());self.write(path,record)
        return self.with_permissions(record['identity'])
    def logout(self,request,response):
        upstream=False
        try:
            path=self.path(request.cookies.get(self.cookie,''),'session')
            if not path.is_file():raise HTTPException(401,'登入已失效')
            with path.with_suffix('.lock').open('a') as handle:
                fcntl.flock(handle,fcntl.LOCK_EX)
                record=self.read(path);path.unlink(missing_ok=True)
            try:
                with httpx.Client(timeout=10) as client:
                    result=client.post(self.server+'/logout',headers={'Authorization':'Bearer '+record['access_token']})
                upstream=result.is_success
            except httpx.HTTPError:pass
        except HTTPException:pass
        response.delete_cookie(self.cookie,path='/');response.delete_cookie('ams_preview_session',path='/')
        response.delete_cookie(self.state_cookie,path='/')
        # Browser redirect clears the IdP's own domain cookie as in its public logout contract.
        return {'ok':True,'idp_logout_success':upstream,'logout_url':self.server+'/logout?'+urlencode({'redirect_uri':self.public+'/','client_id':self.client_id})}
    def install(self,app):
        @app.get('/api/auth/sso')
        @app.get('/api/SSO')
        @app.get('/api/Login')
        def start(request:Request,return_to:str='/'):
            if request.url.hostname != urlsplit(self.public).hostname:
                return RedirectResponse(self.public+'/api/auth/sso?'+urlencode({'return_to':safe_return(return_to)}),status_code=303)
            return self.start(return_to)
        @app.get('/api/callback')
        @app.get('/api/auth/sso/callback')
        def callback(request:Request,code:str|None=None,state:str|None=None,error:str|None=None):
            return self.callback_response(request,code,state,error)
