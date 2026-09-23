"""Deployment contracts without the old checkout, real SSO, or production writes."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from settings import settings,data_path
from database import configuration
from sso import SSO
spec=importlib.util.spec_from_file_location('migration',ROOT/'scripts/migrate_storage.py')
migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)

class StandaloneTests(unittest.TestCase):
    def test_dotenv_and_paths_from_unrelated_working_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{},clear=True):
            root=Path(directory)
            (root/'env').write_text('MYSQL_HOST=db\nMYSQL_DATABASE=ams\nMYSQL_USER=user\nMYSQL_PASSWORD=secret\nAMS_DATA_DIR=old-data\n')
            (root/'.env').write_text('AMS_DATA_DIR=persistent\n')
            data,url,mysql=configuration(root)
            self.assertEqual(data,root/'persistent');self.assertTrue(mysql)
            self.assertEqual(url.host,'db')
            with patch.dict(os.environ,{'AMS_DATA_DIR':'override'}):self.assertEqual(data_path(root),root/'override')
    def test_project_snapshot_fail_closed_and_account_revocation(self):
        from fastapi import HTTPException
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{},clear=True):
            root=Path(directory);data=root/'persistent';sso=SSO(root,data)
            identity={'id':'employee','email':'staff@example.test','name':'員工'}
            with self.assertRaises(HTTPException):sso.with_permissions(identity)
            folder=data/'permissions';folder.mkdir()
            payload={'meta':{'version':5},'data':{
                'users':[{'name':'employee','enabled':True}],
                'roles':[{'name':'reader','activate':True}],
                'userRoles':[{'user':'employee','role':'reader'}],
                'rolePermissions':[{'module':'AMS','role':'reader','parent':'Lending_form','permlevel':0,'read':1}],
                'docFields':[],'uiPermissions':[],'userPermissions':[]}}
            (folder/'snapshot.json').write_text(json.dumps(payload))
            (folder/'latest-AMS.json').write_text(json.dumps({'file':'snapshot.json'}))
            user=sso.with_permissions(identity)
            self.assertTrue(user['permissions']['forms']['Lending_form']['read'])
            self.assertFalse(user['permissions']['forms']['Lending_form']['write'])
            payload['data']['users'][0]['enabled']=False
            (folder/'snapshot.json').write_text(json.dumps(payload))
            with self.assertRaises(HTTPException):sso.with_permissions(identity)
    def test_copy_is_repeatable_but_never_overwrites_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';target=root/'destination'
            source.write_bytes(b'original')
            self.assertTrue(migration.copy_verified(source,target))
            self.assertFalse(migration.copy_verified(source,target))
            target.write_bytes(b'newer')
            with self.assertRaises(RuntimeError):migration.copy_verified(source,target)
            self.assertEqual(source.read_bytes(),b'original')
            self.assertEqual(target.read_bytes(),b'newer')
    def test_reference_scan_handles_legacy_forms_without_metadata_false_positives(self):
        found={}
        migration.references({'photo_files':[{'storage':'url','name':'photo.png','data':{'uuid':'file-123'},'url':'https://old.test/preview/file-123'}]},found)
        migration.references('[{"uuid":"file-456"}]',found,True)
        self.assertEqual(set(found),{'file-123','file-456'})

if __name__=='__main__':unittest.main(verbosity=2)
