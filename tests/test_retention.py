"""Real PostgreSQL tests, exclusively in a disposable Unix-socket cluster.

Never loads project credentials or connects to the production cluster.
"""
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, text, select, insert, update, URL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import retention as r

SCHEMA = '''
CREATE TABLE gps_readings (id integer PRIMARY KEY, client_id text, created_at timestamp, record_time timestamp, latitude numeric(10,8));
CREATE TABLE sensor_readings (id integer PRIMARY KEY, client_id text, major integer, created_at timestamp, timestamp timestamp);
CREATE TABLE notification (id integer PRIMARY KEY, created_at timestamp, content text);
CREATE TABLE cost (sn integer PRIMARY KEY, plate text, create_at timestamp, notes text, upload_file text);
CREATE TABLE insurance_records (sn integer PRIMARY KEY, create_at timestamp, validity_period text);
CREATE TABLE formio_responses (sn integer PRIMARY KEY, form_id text, created_at timestamp, updated_at timestamp, "end" timestamp, is_deleted integer);
CREATE TABLE form_flows (id integer PRIMARY KEY, form_id text, created_at timestamp, updated_at timestamp, status text);
CREATE TABLE "CarList" ("ID" integer PRIMARY KEY, created_at timestamp);
'''


class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='polimax-retention-test-')
        cls.base = Path(cls.temp.name)
        cls.pg = Path(os.getenv('POSTGRES_TEST_BIN', '/usr/lib/postgresql/16/bin'))
        subprocess.run([str(cls.pg / 'initdb'), '-D', str(cls.base / 'pg'), '-A', 'trust', '--no-locale', '-E', 'UTF8'], check=True, capture_output=True)
        subprocess.run([str(cls.pg / 'pg_ctl'), '-D', str(cls.base / 'pg'), '-l', str(cls.base / 'postgres.log'),
                        '-o', f"-k {cls.base} -h '' -p 15439 -F", '-w', 'start'], check=True, capture_output=True)
        cls.addClassCleanup(cls.stop)
        admin_url = URL.create('postgresql+psycopg', username=os.getenv('USER'), host=str(cls.base), port=15439, database='postgres')
        admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
        with admin.connect() as c:
            c.exec_driver_sql('CREATE DATABASE source')
            c.exec_driver_sql('CREATE DATABASE archive')
        admin.dispose()
        cls.source = create_engine(admin_url.set(database='source'))
        cls.target = create_engine(admin_url.set(database='archive'))

    @classmethod
    def stop(cls):
        if hasattr(cls, 'source'):
            cls.source.dispose(); cls.target.dispose()
        subprocess.run([str(cls.pg / 'pg_ctl'), '-D', str(cls.base / 'pg'), '-m', 'immediate', '-w', 'stop'], check=True, capture_output=True)
        cls.temp.cleanup()

    def setUp(self):
        for engine in (self.source, self.target):
            with engine.begin() as c:
                c.exec_driver_sql('DROP SCHEMA public CASCADE')
                c.exec_driver_sql('CREATE SCHEMA public')
        with self.source.begin() as c:
            c.exec_driver_sql(SCHEMA)
        self.files = tempfile.TemporaryDirectory(dir=self.base)
        self.addCleanup(self.files.cleanup)
        self.root = Path(self.files.name)
        self.data = self.root / '.data'
        (self.data / 'files').mkdir(parents=True)
        self.tables = r.initialize(self.source, self.target)
        self.old = r.now() - timedelta(days=150)
        self.recent = r.now() - timedelta(days=2)

    def add(self, name, **values):
        with self.source.begin() as c:
            c.execute(insert(self.tables[name]).values(**values))

    def rows(self, engine, name):
        with engine.connect() as c:
            return [dict(row) for row in c.execute(select(self.tables[name]).order_by(*self.tables[name].primary_key)).mappings()]

    def run_archive(self, names, apply=True, **kwargs):
        return r.run(self.source, self.target, self.root, self.data, apply=apply, only=names, **kwargs)

    def seed_gps(self):
        for ident, stamp in [(1, self.old), (2, self.old + timedelta(days=1)), (3, self.recent)]:
            self.add('gps_readings', id=ident, client_id='device', created_at=stamp, record_time=stamp, latitude='25.12345678')
        self.add('gps_readings', id=4, client_id='offline', created_at=self.old, record_time=self.old)
        self.add('gps_readings', id=5, client_id='unknown', created_at=None, record_time=self.old)

    def test_preview_then_archive_keeps_latest_and_unknown(self):
        self.seed_gps()
        self.assertEqual(self.run_archive(['gps_readings'], False)[0]['rows'], 2)
        self.assertEqual(len(self.rows(self.source, 'gps_readings')), 5)
        self.assertEqual(self.rows(self.target, 'gps_readings'), [])
        self.run_archive(['gps_readings'])
        self.assertEqual([row['id'] for row in self.rows(self.source, 'gps_readings')], [3, 4, 5])
        self.assertEqual([row['id'] for row in self.rows(self.target, 'gps_readings')], [1, 2])
        self.assertEqual(self.run_archive(['gps_readings'])[0]['rows'], 0)

    def test_sensor_preserves_latest_received_and_latest_recorded(self):
        for ident, received, recorded in [(1, 0, 0), (2, 3, 1), (3, 2, 4)]:
            self.add('sensor_readings', id=ident, client_id='station', major=10,
                     created_at=self.old + timedelta(days=received), timestamp=self.old + timedelta(days=recorded))
        self.run_archive(['sensor_readings'])
        self.assertEqual([row['id'] for row in self.rows(self.source, 'sensor_readings')], [2, 3])

    def test_conflicting_archive_does_not_delete_source(self):
        self.seed_gps()
        with self.target.begin() as c:
            c.execute(insert(self.tables['gps_readings']).values(id=1, client_id='wrong'))
        with self.assertRaisesRegex(RuntimeError, 'Archive conflict'):
            self.run_archive(['gps_readings'])
        self.assertEqual(len(self.rows(self.source, 'gps_readings')), 5)
        with self.target.connect() as c:
            self.assertEqual(c.execute(select(r.batches.c.verified_at)).scalar(), None)

    def test_failure_after_archive_commit_is_retryable(self):
        self.seed_gps()
        with self.assertRaisesRegex(RuntimeError, 'simulated crash'):
            with self.source.begin() as c:
                r.source_lock(c, 'source')
                rows = [dict(row) for row in c.execute(select(self.tables['gps_readings']).where(self.tables['gps_readings'].c.id == 1).with_for_update()).mappings()]
                def crash(): raise RuntimeError('simulated crash')
                r.transfer(c, self.target, self.tables, {'gps_readings': rows}, {}, 'source', self.recent, 'gps_readings', after_archive=crash)
        self.assertEqual(len(self.rows(self.source, 'gps_readings')), 5)
        self.assertEqual(len(self.rows(self.target, 'gps_readings')), 1)
        self.run_archive(['gps_readings'])
        self.assertEqual(len(self.rows(self.target, 'gps_readings')), 2)

    def test_changed_source_guard_rolls_back(self):
        self.seed_gps()
        with self.assertRaisesRegex(RuntimeError, 'Source changed'):
            with self.source.begin() as c:
                rows = [dict(row) for row in c.execute(select(self.tables['gps_readings']).where(self.tables['gps_readings'].c.id == 1)).mappings()]
                def change(): c.execute(update(self.tables['gps_readings']).where(self.tables['gps_readings'].c.id == 1).values(client_id='changed'))
                r.transfer(c, self.target, self.tables, {'gps_readings': rows}, {}, 'source', self.recent, 'gps_readings', after_archive=change)
        self.assertEqual(self.rows(self.source, 'gps_readings')[0]['client_id'], 'device')

    def mark(self, name, key):
        with self.source.begin() as c:
            r.mark_completed(c, self.tables, name, str(key), self.old + timedelta(days=2), 'verified completion', 'test', self.root, self.data)

    def test_business_requires_completion_and_invalidates_on_edit(self):
        self.add('cost', sn=1, plate='CAR', create_at=self.old, notes='original')
        self.assertEqual(self.run_archive(['cost'])[0]['rows'], 0)
        self.mark('cost', 1)
        with self.source.begin() as c:
            c.execute(update(self.tables['cost']).values(notes='edited'))
        self.assertEqual(self.run_archive(['cost'])[0]['rows'], 0)
        self.mark('cost', 1)
        self.run_archive(['cost'])
        self.assertEqual(self.rows(self.source, 'cost'), [])
        self.assertEqual(self.rows(self.target, 'cost')[0]['notes'], 'edited')

    def test_business_archive_cursor_advances_past_incomplete_records(self):
        for ident in range(1, 5):
            self.add('cost', sn=ident, plate='CAR', create_at=self.old, notes=str(ident))
        self.mark('cost', 4)
        for _ in range(3):
            self.run_archive(['cost'], batch_size=2, max_batches=1)
            self.assertEqual(len(self.rows(self.source, 'cost')), 4)
        self.run_archive(['cost'], batch_size=2, max_batches=1)
        self.assertEqual([row['sn'] for row in self.rows(self.source, 'cost')], [1, 2, 3])
        self.assertEqual([row['sn'] for row in self.rows(self.target, 'cost')], [4])

    def test_active_insurance_is_retained_even_if_marked_complete(self):
        self.add('insurance_records', sn=1, create_at=self.old, validity_period=str(self.recent.date()))
        self.mark('insurance_records', 1)
        self.assertEqual(self.run_archive(['insurance_records'])[0]['rows'], 0)

    def test_missing_attachment_blocks_business_record(self):
        self.add('cost', sn=1, create_at=self.old, upload_file='missing-file')
        result = self.run_archive(['cost'])[0]
        self.assertEqual(result['rows'], 0)
        self.assertIn('Missing', result['blocked'][0]['reason'])
        self.assertEqual(len(self.rows(self.source, 'cost')), 1)

    def test_chunked_attachment_bytes_survive_and_source_files_remain(self):
        data = b'0123456789' * 900000
        (self.data / 'files' / 'photo').write_bytes(data)
        (self.data / 'files' / 'photo.json').write_text('{"name":"photo.bin"}')
        self.add('cost', sn=1, create_at=self.old, upload_file='photo')
        self.mark('cost', 1)
        self.run_archive(['cost'])
        with self.target.connect() as c:
            manifest = c.execute(select(r.batches.c.payload)).scalar_one()['files']['files/photo']
            restored = b''.join(bytes(c.execute(select(r.blobs.c.content).where(r.blobs.c.sha256 == digest)).scalar_one()) for digest in manifest['chunks'])
        self.assertEqual(restored, data)
        self.assertTrue((self.data / 'files' / 'photo').exists())

    def test_closed_form_archives_family_and_retains_unreturned(self):
        for seq, status in [(1, 'RETURN_ARRIVED'), (2, 'PENDING')]:
            fid = f'11401A{seq:04}'
            self.add('formio_responses', sn=seq, form_id=fid, created_at=self.old, updated_at=self.old, end=self.old, is_deleted=0)
            self.add('form_flows', id=seq, form_id=fid, created_at=self.old, updated_at=self.old, status=status)
            folder = self.data / 'responses' / '主表'; folder.mkdir(parents=True, exist_ok=True)
            (folder / (fid + '.json')).write_text(json.dumps({'form_id': fid}))
        folder = self.data / 'responses' / '回程紀錄表'; folder.mkdir(parents=True)
        (folder / '11401C0001.json').write_text('{"content":{"parent_form_id":"11401A0001"}}')
        (self.data / 'responses' / '主表' / '11401A0001_20260101.bak.json').write_text('{"content":{"notes":"old version"}}')
        for path in (self.data / 'responses').rglob('*.json'):
            os.utime(path, (self.old.timestamp(), self.old.timestamp()))
        self.run_archive(['formio_responses'])
        self.assertEqual([row['sn'] for row in self.rows(self.source, 'formio_responses')], [2])
        self.assertEqual([row['id'] for row in self.rows(self.source, 'form_flows')], [2])
        with self.target.connect() as c:
            manifest = c.execute(select(r.batches.c.payload)).scalar_one()
            self.assertIn('responses/回程紀錄表/11401C0001.json', manifest['files'])
            self.assertIn('responses/主表/11401A0001_20260101.bak.json', manifest['files'])

    def test_unavailable_archive_retains_source(self):
        self.seed_gps()
        broken = create_engine(self.target.url.set(database='does_not_exist'))
        try:
            with self.assertRaises(Exception):
                r.run(self.source, broken, self.root, self.data, apply=True, only=['gps_readings'])
            self.assertEqual(len(self.rows(self.source, 'gps_readings')), 5)
        finally:
            broken.dispose()

    def test_master_tables_never_selected(self):
        with self.source.begin() as c:
            c.execute(text('INSERT INTO "CarList" VALUES (1, :date)'), {'date': self.old})
        self.run_archive(['CarList'])
        with self.source.connect() as c:
            self.assertEqual(c.execute(text('SELECT count(*) FROM "CarList"')).scalar(), 1)

    def test_source_application_lock_excludes_cleanup(self):
        self.seed_gps()
        with self.source.begin() as c:
            r.source_lock(c, 'source')
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                self.run_archive(['gps_readings'])
        self.assertEqual(len(self.rows(self.source, 'gps_readings')), 5)

    def test_recently_edited_closed_form_stays_live(self):
        fid = '11401A0001'
        self.add('formio_responses', sn=1, form_id=fid, created_at=self.old, updated_at=self.old, end=self.old)
        self.add('form_flows', id=1, form_id=fid, created_at=self.old, updated_at=self.old, status='RETURN_ARRIVED')
        folder = self.data / 'responses' / '主表'; folder.mkdir(parents=True)
        (folder / (fid + '.json')).write_text('{}')
        self.assertEqual(self.run_archive(['formio_responses'])[0]['rows'], 0)

    def test_equipment_requires_explicit_return_and_future_booking_stays(self):
        fid = '11401E0001'
        self.add('formio_responses', sn=1, form_id=fid, created_at=self.old, updated_at=self.old, end=self.old)
        folder = self.data / 'responses' / '儀器借用表'; folder.mkdir(parents=True)
        (folder / (fid + '.json')).write_text('{}')
        self.assertEqual(self.run_archive(['formio_responses'])[0]['rows'], 0)
        self.mark('formio_responses', fid)
        self.assertEqual(self.run_archive(['formio_responses'])[0]['rows'], 1)
        fid = '11401E0002'
        self.add('formio_responses', sn=2, form_id=fid, created_at=self.old, updated_at=self.old, end=r.now()+timedelta(days=1))
        (folder / (fid + '.json')).write_text('{}')
        self.mark('formio_responses', fid)
        self.assertEqual(self.run_archive(['formio_responses'])[0]['rows'], 0)

    def test_archive_restore_recreates_rows_files_and_audit(self):
        self.seed_gps(); self.run_archive(['gps_readings'])
        dump = self.root / 'archive.dump'
        args = ['-h', str(self.base), '-p', '15439', '-U', os.getenv('USER')]
        subprocess.run([str(self.pg / 'pg_dump'), *args, '-d', 'archive', '-Fc', '-f', str(dump)], check=True, capture_output=True)
        with self.target.begin() as c:
            c.exec_driver_sql('DROP SCHEMA public CASCADE')
            c.exec_driver_sql('CREATE SCHEMA public')
        subprocess.run([str(self.pg / 'pg_restore'), *args, '-d', 'archive', '--no-owner', '--no-acl', str(dump)], check=True, capture_output=True)
        self.assertEqual(len(self.rows(self.target, 'gps_readings')), 2)
        with self.target.connect() as c:
            self.assertIsNotNone(c.execute(select(r.batches.c.verified_at)).scalar_one())

    def test_database_creation_sql_is_repeatable(self):
        admin = create_engine(self.source.url.set(database='postgres'), isolation_level='AUTOCOMMIT')
        try:
            with admin.connect() as c:
                c.exec_driver_sql('CREATE ROLE polimax_admin LOGIN')
            args = [str(self.pg / 'psql'), '-X', '-h', str(self.base), '-p', '15439', '-U', os.getenv('USER'),
                    '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-f', str(ROOT / 'deploy/create_archive_database.sql')]
            subprocess.run(args, check=True, capture_output=True)
            subprocess.run(args, check=True, capture_output=True)
            with admin.connect() as c:
                self.assertEqual(c.execute(text("SELECT count(*) FROM pg_database WHERE datname='polimax_PostgreSQL_Expired'")).scalar(), 1)
        finally:
            admin.dispose()

    def test_full_backup_contains_both_databases_and_manifest(self):
        self.seed_gps(); self.run_archive(['gps_readings'])
        spec = importlib.util.spec_from_file_location('archive_backup_test', ROOT / 'scripts/backup_postgresql.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        parent = self.root / 'backups'
        config = {'AMS_BACKUP_DIR': str(parent), 'AMS_ARCHIVE_ENABLED': '1'}
        with patch.object(module, 'ROOT', self.root), patch.object(module, 'configuration',
            return_value=(self.data, self.source.url.set(password='unused-test-password'), True)), \
            patch.object(module, 'settings', return_value=config), \
            patch.dict(os.environ, {'AMS_ARCHIVE_DATABASE': 'archive'}):
            module.main()
        output = next(parent.iterdir())
        manifest = json.loads((output / 'manifest.json').read_text())
        for name in ('postgresql.dump', 'expired.dump', 'persistent.tar'):
            self.assertEqual(manifest[name], module.digest(output / name))
        self.assertEqual(manifest['archive_database'], 'archive')
        for name in ('postgresql.dump', 'expired.dump'):
            subprocess.run([str(self.pg / 'pg_restore'), '--list', str(output / name)], check=True, capture_output=True)

    def test_archive_api_permissions_completion_and_file_download(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import permissions
        from archive_api import install
        self.add('cost', sn=1, create_at=self.old, notes='private', upload_file='photo')
        (self.data / 'files' / 'photo').write_bytes(b'file bytes')
        (self.data / 'files' / 'photo.json').write_text('{}')
        self.mark('cost', 1); self.run_archive(['cost'])
        with self.target.connect() as c:
            batch = c.execute(select(r.batches.c.id)).scalar_one()
        user = {'id': 'demo-admin'}
        user['permissions'] = permissions.effective_policy(permissions.default_policy(), user)
        @contextmanager
        def session(write=False):
            with self.source.begin() as c:
                if write: r.source_lock(c, 'source')
                yield SimpleNamespace(c=c)
        store = SimpleNamespace(engine=self.source, root=self.root, data=self.data, session=session)
        def check(u, doc, *ops): permissions.require(u, doc, *ops)
        app = FastAPI(); install(app, lambda: store, lambda: user, check)
        with patch.dict(os.environ, {'AMS_ARCHIVE_DATABASE': 'archive'}), TestClient(app) as client:
            self.assertEqual(client.get('/api/archive/history?name=cost').status_code, 200)
            response = client.get(f'/api/archive/history/{batch}/file', params={'path': 'files/photo'})
            self.assertEqual(response.content, b'file bytes')
            self.assertEqual(client.get(f'/api/archive/history/{batch}/file', params={'path': '../env'}).status_code, 404)
            user['permissions']['fields']['Cost']['notes'] = {'read': 0, 'write': 0}
            self.assertEqual(client.get('/api/archive/history?name=cost').status_code, 403)
            self.assertEqual(client.get(f'/api/archive/history/{batch}/file', params={'path': 'files/photo'}).status_code, 403)
            user['permissions'] = permissions.effective_policy(permissions.default_policy(), {'id': 'demo-viewer'})
            self.assertEqual(client.get('/api/archive/catalog').status_code, 403)
            self.assertEqual(client.put('/api/archive/live/cost/1/completion', json={'completed_at': str(self.old), 'note': 'test'}).status_code, 403)


if __name__ == '__main__':
    unittest.main(verbosity=2)
