"""Administrative archive browsing and explicit business completion records."""
from urllib.parse import quote
from fastapi import Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, select, delete, or_, String, cast
from retention import (TABLES, MANUAL, batches, blobs, decisions, archive_url, reflect,
                       mark_completed)
from legacy_store import fail
from settings import settings

LABELS = {'gps_readings': 'GPS 定位', 'new_reports': 'FindMy 回報', 'FindMy': 'FindMy 定位',
    'Outdoor_Beacon_readings': '戶外 Beacon', 'sensor_readings': '室內掃描',
    'alert_logs': 'RFID 事件', 'notification': '通知紀錄', 'device_alert': '設備告警',
    'vehicle_alerts2': '車輛告警', 'vehicle_status': '車輛狀態歷史',
    'cost': '費用', 'insurance_records': '保險', 'vehicle_records': '維修',
    'garage_files': '車庫文件', 'formio_responses': '借用與預約表單', 'form_flows': '借用流程'}
DOCS = {name: ['Administration'] for name in TABLES}
DOCS.update({name: ['Cost', 'VehicleManagement'] for name in ('cost', 'vehicle_records', 'garage_files')})
DOCS['insurance_records'] = ['Insurance', 'VehicleManagement']
DOCS['formio_responses'] = ['Lending_form', 'Room_form', 'Equipment_form', 'departure_form', 'back_form', 'departure_arrive', 'back_arrive']
DOCS['form_flows'] = DOCS['formio_responses']
DOCS.update(gps_readings=['carMap'], new_reports=['FindMy'], FindMy=['FindMy'],
            Outdoor_Beacon_readings=['Latest_Device'], sensor_readings=['Latest_Device'])


class Completion(BaseModel):
    completed_at: str
    note: str = Field(min_length=1, max_length=2000)


def install(app, store, current, check):
    @app.get('/api/archive/status')
    def status(user=Depends(current)):
        check(user, 'Administration', 'read')
        return {'enabled': settings(store().root).get('AMS_ARCHIVE_ENABLED', '0') == '1'}

    def authorize(user, name, write=False):
        if name not in TABLES:
            fail('無效資料類型', 404)
        check(user, 'Administration', 'write' if write else 'read')
        # Raw historical values have legacy field names. Fail closed for scoped
        # accounts rather than bypassing field or owner restrictions via raw SQL.
        for doc in set(['Administration', *DOCS[name]]):
            check(user, doc, 'read')
            if write:
                check(user, doc, 'write')
            p = user['permissions']
            if (p.get('owner_only', {}).get(doc, {}).get('read') or
                p.get('allow_list', {}).get(doc) or
                any(not rule.get('read', 0) for rule in p.get('fields', {}).get(doc, {}).values())):
                fail('歷史原始資料需具備完整資料讀取權限', 403)

    def target():
        return create_engine(archive_url(store().engine.url, store().root),
                             hide_parameters=True, connect_args={'connect_timeout': 10})

    @app.get('/api/archive/catalog')
    def catalog(user=Depends(current)):
        check(user, 'Administration', 'read')
        return [{'name': name, 'label': LABELS[name], 'manual': name in MANUAL}
                for name in TABLES if name != 'form_flows']

    @app.get('/api/archive/live/{name}')
    def live(name: str, page: int = Query(0, ge=0), search: str = Query('', max_length=100), user=Depends(current)):
        authorize(user, name)
        if name not in MANUAL:
            fail('此類型使用自動保留規則')
        with store().session() as repo:
            table = reflect(repo.c)[name]
            key = table.c.form_id if name == 'formio_responses' else list(table.primary_key)[0]
            q = select(table)
            columns = [c for c in table.c if c.name in ('form_id', 'plate', 'license_plate', 'client_id')]
            if search:
                q = q.where(or_(cast(key, String).contains(search, autoescape=True),
                    *(c.contains(search, autoescape=True) for c in columns)))
            rows = [dict(r) for r in repo.c.execute(q.order_by(key).limit(51).offset(page * 50)).mappings()]
            result = []
            for row in rows[:50]:
                record_key = str(row[key.name])
                decision = repo.c.execute(select(decisions).where(decisions.c.table_name == name,
                    decisions.c.record_key == record_key)).mappings().first()
                result.append({'key': record_key, 'row': row, 'completion': dict(decision) if decision else None})
            return {'items': result, 'has_more': len(rows) > 50}

    @app.put('/api/archive/live/{name}/{key}/completion')
    def complete(name: str, key: str, body: Completion, user=Depends(current)):
        authorize(user, name, True)
        try:
            with store().session(True) as repo:
                mark_completed(repo.c, reflect(repo.c), name, key, body.completed_at, body.note,
                               str(user['id']), store().root, store().data)
        except ValueError as exc:
            fail(str(exc))
        return {'ok': True}

    @app.delete('/api/archive/live/{name}/{key}/completion')
    def reopen(name: str, key: str, user=Depends(current)):
        authorize(user, name, True)
        with store().session(True) as repo:
            repo.c.execute(delete(decisions).where(decisions.c.table_name == name, decisions.c.record_key == key))
        return {'ok': True}

    @app.get('/api/archive/history')
    def history(name: str, key: str = Query('', max_length=100), page: int = Query(0, ge=0), user=Depends(current)):
        authorize(user, name)
        engine = target()
        try:
            with engine.connect() as c:
                q = select(batches.c.id, batches.c.table_name, batches.c.record_key,
                    batches.c.created_at, batches.c.row_count).where(
                    batches.c.table_name == name, batches.c.verified_at.is_not(None))
                if key:
                    q = q.where(batches.c.record_key == key)
                rows = [dict(r) for r in c.execute(q.order_by(batches.c.created_at.desc(), batches.c.id)
                    .limit(51).offset(page * 50)).mappings()]
                return {'items': rows[:50], 'has_more': len(rows) > 50}
        finally:
            engine.dispose()

    def get_batch(c, ident, user):
        row = c.execute(select(batches).where(batches.c.id == ident, batches.c.verified_at.is_not(None))).mappings().first()
        if not row:
            fail('找不到已驗證的封存紀錄', 404)
        authorize(user, row['table_name'])
        return dict(row)

    @app.get('/api/archive/history/{ident}')
    def detail(ident: str, user=Depends(current)):
        check(user, 'Administration', 'read')
        engine = target()
        try:
            with engine.connect() as c:
                result = get_batch(c, ident, user)
                # Response JSON is part of the form; expose a download for exact bytes.
                return result
        finally:
            engine.dispose()

    @app.get('/api/archive/history/{ident}/file')
    def file(ident: str, path: str, user=Depends(current)):
        check(user, 'Administration', 'read')
        engine = target()
        try:
            with engine.connect() as c:
                batch = get_batch(c, ident, user)
                manifest = batch['payload']['files'].get(path)
                if manifest is None:
                    fail('附件不屬於此封存紀錄', 404)
        except BaseException:
            engine.dispose()
            raise

        def content():
            try:
                with engine.connect() as c:
                    for digest in manifest['chunks']:
                        yield bytes(c.execute(select(blobs.c.content).where(blobs.c.sha256 == digest)).scalar_one())
            finally:
                engine.dispose()
        return StreamingResponse(content(), media_type='application/octet-stream', headers={
            'Content-Disposition': "attachment; filename*=UTF-8''" + quote(path.rsplit('/', 1)[-1], safe='')})
