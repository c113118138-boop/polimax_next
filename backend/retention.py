"""PostgreSQL archive-before-delete, with explicit business completion decisions.

The source application lock and row locks span archive commit, read-back and
source deletion. The two databases deliberately do not pretend to be one
transaction: a crash can leave a verified extra copy, never a missing original.
"""
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import geoalchemy2  # Registers PostGIS types for SQLAlchemy reflection.
from sqlalchemy import (MetaData, Table, Column, String, Text, DateTime, LargeBinary,
                        Integer, Index, select, insert, delete, text, inspect, func, cast)
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from gps_history import RETENTION_RULES, expired_ids
from settings import settings, local_path

TZ = timezone(timedelta(hours=8))
LOCATIONS = {**RETENTION_RULES, 'sensor_readings': {
    'group_columns': ('client_id', 'major'), 'latest_columns': ('created_at', 'timestamp')}}
BUSINESS = ('cost', 'insurance_records', 'vehicle_records', 'garage_files')
MANUAL = (*BUSINESS, 'formio_responses', 'device_alert', 'vehicle_alerts2')
EVENTS = {'alert_logs': 'created_at', 'notification': 'created_at'}
TABLES = (*LOCATIONS, *EVENTS, 'device_alert', 'vehicle_alerts2', 'vehicle_status',
          *BUSINESS, 'formio_responses', 'form_flows')
FOLDERS = {'A': '主表', 'B': '發車紀錄表', 'C': '回程紀錄表', 'D': '工作間預約表', 'E': '儀器借用表'}
meta = MetaData()
decisions = Table('polimax_retention_decisions', meta,
    Column('table_name', String(80), primary_key=True), Column('record_key', String(100), primary_key=True),
    Column('completed_at', DateTime, nullable=False), Column('fingerprint', String(64), nullable=False),
    Column('actor', Text, nullable=False), Column('note', Text, nullable=False),
    Column('marked_at', DateTime, nullable=False))
cursor = Table('polimax_retention_cursor', meta,
    Column('table_name', String(80), primary_key=True), Column('last_key', Text))
archive_meta = MetaData()
batches = Table('polimax_archive_batches', archive_meta,
    Column('id', String(36), primary_key=True), Column('source_database', Text, nullable=False),
    Column('table_name', String(80), nullable=False), Column('record_key', String(100)),
    Column('created_at', DateTime, nullable=False), Column('cutoff', DateTime, nullable=False),
    Column('row_count', Integer, nullable=False), Column('payload', JSONB, nullable=False),
    Column('verified_at', DateTime))
blobs = Table('polimax_archive_files', archive_meta,
    Column('sha256', String(64), primary_key=True), Column('content', LargeBinary, nullable=False))
Index('polimax_archive_history_idx', batches.c.table_name, batches.c.created_at, batches.c.id)
Index('polimax_archive_key_idx', batches.c.table_name, batches.c.record_key)


def now():
    return datetime.now(TZ).replace(tzinfo=None)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(',', ':'))


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def archive_url(source_url, root):
    target = settings(root).get('AMS_ARCHIVE_DATABASE', 'polimax_PostgreSQL_Expired')
    if source_url.get_backend_name() != 'postgresql' or target == source_url.database:
        raise ValueError('Archive requires a distinct PostgreSQL database on the same server')
    return source_url.set(database=target)


def source_lock(connection, database):
    name = 'polimax:' + hashlib.sha256(database.encode()).hexdigest()[:32]
    key = int(hashlib.sha256(name.encode()).hexdigest()[:15], 16)
    connection.execute(text("SET LOCAL lock_timeout = '10s'"))
    connection.execute(text("SET LOCAL statement_timeout = '120s'"))
    if not connection.execute(text('SELECT pg_try_advisory_xact_lock(:k)'), {'k': key}).scalar():
        raise RuntimeError('Application or backup is busy; retry later')


def reflect(connection):
    available = set(inspect(connection).get_table_names())
    return {name: Table(name, MetaData(), autoload_with=connection)
            for name in TABLES if name in available}


def initialize(source, target):
    if source.url.database == target.url.database:
        raise ValueError('Source and archive must differ')
    with source.begin() as c:
        tables = reflect(c)
        decisions.create(c, checkfirst=True)
        cursor.create(c, checkfirst=True)
    with target.begin() as c:
        archive_meta.create_all(c)
        existing = inspect(c)
        for name, table in tables.items():
            # Preserve names/types/keys, but no identity defaults, triggers or live FKs.
            # Historical child rows must survive changes to the live master tables.
            copy = Table(name, MetaData(), *(Column(col.name, col.type,
                primary_key=col.primary_key, nullable=col.nullable) for col in table.columns))
            copy.create(c, checkfirst=True)
            columns = {col['name']: str(col['type']) for col in existing.get_columns(name)}
            expected = {col.name: str(col.type) for col in table.columns}
            if columns != expected:
                raise RuntimeError('Archive schema differs: ' + name)
    return tables


def references(value, found, attachment=False):
    if isinstance(value, list):
        for item in value:
            references(item, found, attachment)
    elif isinstance(value, dict):
        ident = value.get('uuid') or value.get('file_uuid')
        if not ident and isinstance(value.get('data'), dict):
            ident = value['data'].get('uuid')
        if not ident and attachment:
            ident = value.get('id')
        if isinstance(ident, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', ident):
            found.add(ident)
        for key, item in value.items():
            references(item, found, 'file' in key.lower() or 'uuid' in key.lower() or key == 'attachments')
    elif isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (dict, list)):
                references(parsed, found, attachment)
                return
        except ValueError:
            pass
        match = re.search(r'/(?:files|file|preview)/([a-zA-Z0-9_-]{1,100})(?:[/?#]|$)', value)
        if match:
            found.add(match[1])
        elif attachment:
            for ident in re.split(r'[,，;；\n]', value):
                ident = ident.strip()
                if re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', ident):
                    found.add(ident)
                elif ident:
                    raise ValueError('Unresolved attachment reference')


def bundle(connection, tables, name, key, root, data, lock=False):
    """Read a whole form family or business record, plus immutable file bytes."""
    table = tables[name]
    column = table.c.form_id if name == 'formio_responses' else list(table.primary_key)[0]
    value = key if name == 'formio_responses' else int(key)
    query = select(table).where(column == value).order_by(*table.primary_key)
    rows = [dict(r) for r in connection.execute(query.with_for_update() if lock else query).mappings()]
    if not rows:
        raise ValueError('Record not found')
    groups = {name: rows}
    files = {}
    payloads = []
    config = settings(root)
    response_dir = local_path(root, config.get('AMS_RESPONSES_DIR') or config.get('AMS_LEGACY_RESPONSES_DIR') or str(data / 'responses'))

    def add(path, logical):
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or unsafe file: ' + logical)
        files[logical] = path
        return path

    if name == 'formio_responses':
        if not re.fullmatch(r'\d{5}[ADE]\d{4,}', key):
            raise ValueError('Unsupported form ID')
        flow = tables['form_flows']
        q = select(flow).where(flow.c.form_id == key).order_by(flow.c.id)
        groups['form_flows'] = [dict(r) for r in connection.execute(q.with_for_update() if lock else q).mappings()]
        path = response_dir / FOLDERS[key[5]] / (key + '.json')
        payloads.append(json.loads(add(path, 'responses/' + str(path.relative_to(response_dir))).read_text()))
        for version in sorted(path.parent.glob(key + '_*.bak.json')):
            payloads.append(json.loads(add(version, 'responses/' + str(version.relative_to(response_dir))).read_text()))
        # Include every B/C version referring to this parent, even soft-deleted stages.
        for kind in ('B', 'C'):
            for path in sorted((response_dir / FOLDERS[kind]).glob('*.json')):
                raw = json.loads(path.read_text())
                content = raw.get('content', raw) if isinstance(raw, dict) else {}
                if isinstance(content, dict) and content.get('parent_form_id') == key:
                    payloads.append(raw)
                    add(path, 'responses/' + str(path.relative_to(response_dir)))
    found = set()
    references(groups, found)
    for raw in payloads:
        references(raw, found)
    for ident in sorted(found):
        add(data / 'files' / ident, 'files/' + ident)
        add(data / 'files' / (ident + '.json'), 'files/' + ident + '.json')
    manifest = {logical: file_digest(path) for logical, path in files.items()}
    return groups, files, fingerprint({'rows': groups, 'files': manifest})


def timestamp(value):
    if not value:
        return None
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.astimezone(TZ).replace(tzinfo=None) if result.tzinfo else result
    except (ValueError, TypeError):
        return None


def eligible(connection, name, key, groups, digest, cutoff):
    rows = groups[name]
    # Unknown dates are deliberately ineligible; do not interpret NULL as old.
    dates = [timestamp(r.get('created_at') or r.get('create_at')) for r in rows]
    dates += [timestamp(r['updated_at']) for r in rows if r.get('updated_at')]
    if any(d is None or d >= cutoff for d in dates):
        return False
    if name == 'insurance_records':
        expiry = timestamp(rows[0].get('validity_period'))
        if expiry is None or expiry >= cutoff:
            return False
    if name == 'vehicle_records':
        end = timestamp(rows[0].get('record_date'))
        if end is None or end >= cutoff:
            return False
    if name == 'vehicle_alerts2' and rows[0].get('notification_sent') != '是':
        return False
    if name == 'formio_responses':
        ends = [timestamp(r.get('end')) for r in rows]
        if any(d is None or d >= cutoff for d in ends):
            return False
        flows = groups.get('form_flows', [])
        last = max(flows, key=lambda r: r['id'], default={})
        if key[5] == 'A':
            closed = timestamp(last.get('updated_at'))
            return last.get('status') in ('returned', 'RETURN_ARRIVED') and closed is not None and closed < cutoff
    decision = connection.execute(select(decisions).where(
        decisions.c.table_name == name, decisions.c.record_key == key)).mappings().first()
    return bool(decision and decision['completed_at'] < cutoff and decision['fingerprint'] == digest)


def mark_completed(connection, tables, name, key, completed_at, note, actor, root, data):
    if name not in MANUAL or not note.strip():
        raise ValueError('Choose a supported record and provide a completion note')
    stamp = timestamp(completed_at)
    if stamp is None or stamp > now():
        raise ValueError('Completion date must not be in the future')
    groups, _, digest = bundle(connection, tables, name, key, root, data, lock=True)
    record_dates = [timestamp(r.get('created_at') or r.get('create_at')) for r in groups[name]]
    if any(d is None or stamp < d for d in record_dates):
        raise ValueError('Completion must not predate record creation')
    values = dict(table_name=name, record_key=key, completed_at=stamp, fingerprint=digest,
                  actor=actor, note=note.strip(), marked_at=now())
    statement = pg_insert(decisions).values(**values)
    connection.execute(statement.on_conflict_do_update(
        index_elements=['table_name', 'record_key'], set_=values))


def transfer(connection, target, tables, groups, files, source_database, cutoff, name, key=None,
             after_archive=None):
    """Caller owns source transaction/locks. Commit target, verify, then delete exact PKs."""
    batch = str(uuid.uuid4())
    manifest = {}
    with target.begin() as dest:
        for table_name, rows in groups.items():
            table = tables[table_name]
            for row in rows:
                statement = pg_insert(table).values(**row).on_conflict_do_nothing()
                dest.execute(statement)
        # Chunk large stage photos so a one-gigabyte attachment never becomes a
        # one-gigabyte Python object or PostgreSQL bytea value.
        for logical, path in files.items():
            chunks, digest, size = [], hashlib.sha256(), 0
            with path.open('rb') as stream:
                for content in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                    chunk_hash = hashlib.sha256(content).hexdigest()
                    digest.update(content)
                    size += len(content)
                    chunks.append(chunk_hash)
                    dest.execute(pg_insert(blobs).values(sha256=chunk_hash, content=content).on_conflict_do_nothing())
            manifest[logical] = {'sha256': digest.hexdigest(), 'chunks': chunks, 'size': size}
        completion = None
        if key:
            decision = connection.execute(select(decisions).where(
                decisions.c.table_name == name, decisions.c.record_key == key)).mappings().first()
            completion = json.loads(canonical(dict(decision))) if decision else None
        payload = {'rows': json.loads(canonical(groups)), 'files': manifest, 'completion': completion}
        dest.execute(insert(batches).values(id=batch, source_database=source_database, table_name=name,
            record_key=key, created_at=now(), cutoff=cutoff, row_count=sum(map(len, groups.values())), payload=payload))
    # New connection/transaction: verify committed rows, not an in-memory insert result.
    with target.begin() as dest:
        for table_name, rows in groups.items():
            table = tables[table_name]
            for row in rows:
                actual = dest.execute(select(table).where(*(col == row[col.name] for col in table.primary_key))).mappings().one()
                if canonical(dict(actual)) != canonical(row):
                    raise RuntimeError('Archive conflict: ' + table_name)
        for logical, path in files.items():
            digest, size = hashlib.sha256(), 0
            for chunk_hash in manifest[logical]['chunks']:
                actual = bytes(dest.execute(select(blobs.c.content).where(blobs.c.sha256 == chunk_hash)).scalar_one())
                if hashlib.sha256(actual).hexdigest() != chunk_hash:
                    raise RuntimeError('Archive chunk verification failed')
                digest.update(actual)
                size += len(actual)
            if digest.hexdigest() != file_digest(path) or size != manifest[logical]['size']:
                raise RuntimeError('Archive file verification failed: ' + logical)
        actual = dest.execute(select(batches.c.payload).where(batches.c.id == batch)).scalar_one()
        if actual != payload:
            raise RuntimeError('Archive manifest verification failed')
        dest.execute(batches.update().where(batches.c.id == batch).values(verified_at=now()))
    if after_archive:
        after_archive()  # failure-injection point used by integration tests
    for table_name in sorted(groups, key=lambda n: n != 'form_flows'):
        table = tables[table_name]
        for row in groups[table_name]:
            # Full row equality guards callers and unexpected concurrent changes as well.
            result = connection.execute(delete(table).where(*(col.is_not_distinct_from(row[col.name]) for col in table.columns)))
            if result.rowcount != 1:
                raise RuntimeError('Source changed during archive; source transaction rolled back')
    if key:
        connection.execute(delete(decisions).where(decisions.c.table_name == name, decisions.c.record_key == key))
    return batch


def candidate_ids(connection, tables, name, cutoff, limit, after_key=None):
    table = tables[name]
    if name in LOCATIONS:
        return expired_ids(connection, table, cutoff, limit, **LOCATIONS[name])
    pk = list(table.primary_key)[0]
    if name in EVENTS:
        return list(connection.execute(select(pk).where(table.c[EVENTS[name]] < cutoff).order_by(pk).limit(limit)).scalars())
    if name == 'vehicle_status':
        # Latest state stays live. Old duplicate states may be archived.
        return expired_ids(connection, table, cutoff, limit, group_columns=('client_id', 'license_plate'),
                           time_column='update_at', latest_columns=('update_at',))
    if name == 'formio_responses':
        # Visit all keys so an incomplete older form cannot starve later forms.
        q = select(table.c.form_id).where(table.c.end < cutoff).group_by(table.c.form_id).order_by(table.c.form_id)
        if after_key is not None:
            q = q.where(table.c.form_id > after_key)
        return list(connection.execute(q.limit(limit)).scalars())
    q = select(pk).where(table.c.create_at < cutoff).order_by(pk)
    if after_key is not None:
        q = q.where(pk > cast(after_key, pk.type))
    return list(connection.execute(q.limit(limit)).scalars())


def run(source, target, root, data, apply=False, batch_size=500, max_batches=100, only=None):
    reports = []
    selected = [n for n in TABLES if n != 'form_flows' and (not only or n in only)]
    with source.connect() as c:
        tables = reflect(c)
    cutoff = now() - timedelta(days=90)
    for name in selected:
        if name not in tables:
            reports.append({'table': name, 'status': 'missing_table'})
            continue
        special = name in MANUAL
        count = 0
        blocked = []
        # UTC fields retain the pre-existing conservative cutoff.
        table_cutoff = cutoff - timedelta(hours=8) if name in ('FindMy', 'new_reports') else cutoff
        with source.begin() as c:
            saved_cursor = c.execute(select(cursor.c.last_key).where(cursor.c.table_name == name)).scalar_one_or_none() if special else None
            ids = candidate_ids(c, tables, name, table_cutoff, batch_size, saved_cursor)
            if special and saved_cursor is not None and not ids:
                c.execute(cursor.delete().where(cursor.c.table_name == name))
                ids = candidate_ids(c, tables, name, table_cutoff, batch_size)
        chunks = [[i] for i in ids] if special else [None] * max_batches
        processed = 0
        for chunk in chunks:
            if processed >= max_batches:
                break
            with source.begin() as c:
                if apply:
                    source_lock(c, source.url.database)
                if special:
                    key = str(chunk[0])
                    if apply:
                        c.execute(pg_insert(cursor).values(table_name=name, last_key=key)
                            .on_conflict_do_update(index_elements=['table_name'], set_={'last_key': key}))
                    processed += 1
                    try:
                        groups, files, digest = bundle(c, tables, name, key, root, data, lock=apply)
                        if not eligible(c, name, key, groups, digest, cutoff):
                            continue
                        if name == 'formio_responses' and key[5] == 'A' and any(
                            datetime.fromtimestamp(path.stat().st_mtime, TZ).replace(tzinfo=None) >= cutoff
                            for logical, path in files.items() if logical.startswith('responses/')):
                            # Stage edits live only in JSON and do not update SQL dates.
                            continue
                    except (ValueError, OSError) as exc:
                        blocked.append({'key': key, 'reason': str(exc)})
                        continue
                else:
                    ids = candidate_ids(c, tables, name, table_cutoff, batch_size)
                    if not ids:
                        break
                    table = tables[name]
                    pk = list(table.primary_key)[0]
                    q = select(table).where(pk.in_(ids)).order_by(pk)
                    rows = [dict(r) for r in c.execute(q.with_for_update() if apply else q).mappings()]
                    # Re-evaluate after row locks; a sender may have corrected old data.
                    current = set(candidate_ids(c, tables, name, table_cutoff, batch_size))
                    rows = [r for r in rows if r[pk.name] in current]
                    groups, files, key = {name: rows}, {}, None
                    if not rows:
                        break
                if apply:
                    def recheck():
                        if special:
                            _, _, current_digest = bundle(c, tables, name, key, root, data, lock=True)
                            if current_digest != digest:
                                raise RuntimeError('Business record or files changed during archive')
                    transfer(c, target, tables, groups, files, source.url.database, table_cutoff, name, key, recheck)
                count += sum(len(rows) for rows in groups.values())
                if not special:
                    processed += 1
            if not special and not apply:
                break
        reports.append({'table': name, 'mode': 'apply' if apply else 'preview',
                        'rows': count, 'batches': processed, 'blocked': blocked,
                        'preview_is_bounded': not apply})
    return reports
