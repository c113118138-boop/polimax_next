"""SSO contract tests use a mock IdP; no real credentials or accounts are used."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from unittest.mock import patch
import httpx
from fastapi import FastAPI,Request,Response
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from sso import SSO
import permissions

class SSOTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name);self.root=root
        policy=permissions.default_policy();policy['user_roles']={'verified-id':['borrower']}
        (root/'policy.json').write_text(json.dumps(policy))
        (root/'env').write_text('SSO_SERVER=https://idp.test\nSSO_CLIENT_ID=client\nSSO_CLIENT_SECRET=secret\nPUBLIC_WEB_URL=http://testserver\nAMS_POLICY_FILE='+str(root/'policy.json'))
        self.sso=SSO(root,root);self.calls=[];self.reject_access=False;self.identity='verified-id'
        original=httpx.Client
        self.transport=httpx.MockTransport(self.provider)
        self.mock=patch('sso.httpx.Client',lambda **kw:original(transport=self.transport,**kw));self.mock.start()
        app=FastAPI();self.sso.install(app)
        @app.get('/me')
        def me(request:Request):return self.sso.current(request)
        @app.post('/logout')
        def logout(request:Request,response:Response):return self.sso.logout(request,response)
        self.client=TestClient(app)
    def tearDown(self):self.client.close();self.mock.stop();self.temp.cleanup()
    def provider(self,request):
        self.calls.append(request)
        if request.url.path=='/token':return httpx.Response(200,json={'access_token':'new-token','refresh_token':'refresh-token'})
        if request.url.path=='/userinfo':
            if self.reject_access:
                self.reject_access=False;return httpx.Response(401)
            return httpx.Response(200,json={'sub':self.identity,'email':'staff@example.test','name':'王小明'})
        if request.url.path=='/logout':return httpx.Response(200,json={'ok':True})
        return httpx.Response(404)
    def start(self,return_to='/vehicles'):
        response=self.client.get('/api/auth/sso',params={'return_to':return_to},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        params=parse_qs(urlsplit(response.headers['location']).query)
        self.assertEqual(params['redirect_uri'],['http://testserver/api/callback'])
        self.assertNotIn('secret',response.headers['location'])
        return params['state'][0]
    def login(self):
        state=self.start();r=self.client.get('/api/callback',params={'state':state,'code':'authorization-code'},follow_redirects=False)
        self.assertEqual(r.headers['location'],'http://testserver/vehicles')
        return state
    def test_login_permissions_and_server_tokens(self):
        self.login();r=self.client.get('/me');self.assertEqual(r.status_code,200,r.text)
        user=r.json();self.assertEqual(user['id'],'verified-id');self.assertEqual(user['name'],'王小明')
        self.assertEqual(user['permissions']['roles'],['borrower'])
        self.assertFalse(user['permissions']['forms']['VehicleManagement']['create'])
        self.assertNotIn('access_token',r.text)
        self.assertNotIn('new-token',str(self.client.cookies))
    def test_state_replay_and_mismatch(self):
        state=self.login();count=len(self.calls)
        replay=self.client.get('/api/callback',params={'state':state,'code':'x'},follow_redirects=False)
        self.assertIn('sso_error',replay.headers['location']);self.assertEqual(len(self.calls),count)
        self.start();bad=self.client.get('/api/callback',params={'state':'f'*64,'code':'x'},follow_redirects=False)
        self.assertIn('sso_error',bad.headers['location']);self.assertEqual(len(self.calls),count)
    def test_expired_state_and_safe_redirect(self):
        state=self.start('//evil.test');path=self.sso.path(state,'state');r=self.sso.read(path)
        self.assertEqual(r['return_to'],'/');r['expires']=0;self.sso.write(path,r)
        response=self.client.get('/api/callback',params={'state':state,'code':'x'},follow_redirects=False)
        self.assertIn('sso_error',response.headers['location']);self.assertEqual(self.calls,[])
    def test_refresh_and_logout_revocation(self):
        self.login();token=self.client.cookies.get(self.sso.cookie);path=self.sso.path(token,'session');record=self.sso.read(path)
        record['checked_at']=0;self.sso.write(path,record);self.reject_access=True
        self.assertEqual(self.client.get('/me').status_code,200)
        posts=[parse_qs(r.content.decode()) for r in self.calls if r.url.path=='/token']
        self.assertEqual(posts[-1]['grant_type'],['refresh_token'])
        response=self.client.post('/logout');self.assertEqual(response.status_code,200)
        self.assertIn('logout_url',response.json());self.assertFalse(path.exists())
        self.client.cookies.set(self.sso.cookie,token)
        self.assertEqual(self.client.get('/me').status_code,401)
    def test_changed_identity_rejected(self):
        self.login();path=self.sso.path(self.client.cookies.get(self.sso.cookie),'session');r=self.sso.read(path);r['checked_at']=0;self.sso.write(path,r)
        self.identity='different-id';self.assertEqual(self.client.get('/me').status_code,401)
    def test_existing_snapshot_boolean_roles(self):
        self.sso.config.pop('AMS_POLICY_FILE')
        payload={'meta':{'version':4},'data':{'users':[{'name':'staff@example.test','full_name':'員工','enabled':True}],
            'roles':[{'name':'業務','activate':True}], 'userRoles':[{'user':'staff@example.test','role':'業務'}],
            'rolePermissions':[{'role':'業務','parent':'Lending_form','module':'AMS','permlevel':0,'read':True,'create':True,'submit':True}],
            'docFields':[],'uiPermissions':[],'userPermissions':[]}}
        (self.root/'snapshot.json').write_text(json.dumps(payload));(self.root/'latest.json').write_text(json.dumps({'file':'snapshot.json'}))
        self.sso.config['AMS_SSO_POLICY_MANIFEST']=str(self.root/'latest.json')
        user=self.sso.with_permissions({'id':'verified-id','email':'staff@example.test','name':'王小明'})
        self.assertEqual(user['permissions']['roles'],['業務'])
        self.assertTrue(user['permissions']['forms']['Lending_form']['submit'])
        self.assertFalse(user['permissions']['forms']['VehicleManagement']['delete'])
        payload['data']['users'][0]['enabled']=False;(self.root/'snapshot.json').write_text(json.dumps(payload))
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):self.sso.with_permissions({'id':'verified-id','email':'staff@example.test','name':'王小明'})

if __name__=='__main__':unittest.main(verbosity=2)
