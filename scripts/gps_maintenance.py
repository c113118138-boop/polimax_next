"""GPS/Beacon/equipment location retention. Defaults to a read-only preview; --apply deletes expired rows."""
import argparse
import json
import sys
from datetime import timedelta, datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, MetaData, Table, delete, inspect, Index

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from database import configuration
from legacy_store import now
from gps_history import expired_ids, RETENTION_RULES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--ensure-indexes', action='store_true', help='Create missing GPS query indexes (DDL)')
    args = parser.parse_args()
    _, url, mysql = configuration(ROOT)
    if url.get_backend_name() not in ('mysql', 'postgresql'):
        parser.error('GPS maintenance requires a native SQL database')
    engine = create_engine(url)
    table = Table('gps_readings', MetaData(), autoload_with=engine)
    if args.ensure_indexes:
        with engine.begin() as connection:
            existing = [tuple(i['column_names']) for i in inspect(connection).get_indexes(table.name)]
            for name, columns in [('idx_gps_client_created', ('client_id', 'created_at', 'id')),
                                  ('idx_gps_client_record', ('client_id', 'record_time', 'id'))]:
                if not any(cols[:len(columns)] == columns for cols in existing):
                    Index(name, *(table.c[col] for col in columns)).create(connection)
    # Scan timestamps may be TIMESTAMP: normalize the MySQL session timezone.
    available = set(inspect(engine).get_table_names())
    for name, rule in RETENTION_RULES.items():
        if name not in available:
            print(json.dumps({'table': name, 'status': 'missing_table_skipped'}))
            continue
        table = Table(name, MetaData(), autoload_with=engine)
        # Legacy FindMy importer writes UTC into DATETIME. new_reports has no
        # timezone metadata: UTC cutoff conservatively retains up to 8h extra
        # if its upstream actually writes Taipei wall time.
        clock = datetime.now(timezone.utc).replace(tzinfo=None) if name in ('FindMy', 'new_reports') else now()
        cutoff = clock - timedelta(days=90)
        deleted = 0
        for _ in range(100 if args.apply else 1):
            with engine.begin() as connection:
                if engine.dialect.name == 'mysql':
                    connection.exec_driver_sql("SET time_zone = '+08:00'")
                else:
                    connection.exec_driver_sql("SET TIME ZONE 'Asia/Taipei'")
                ids = expired_ids(connection, table, cutoff, 1000, **rule)
                if not args.apply:
                    print(json.dumps({'mode': 'preview', 'table': name, 'cutoff': str(cutoff),
                        'eligible_in_first_batch': len(ids), 'batch_limit': 1000,
                        'preserve_latest_per_device': True}))
                    break
                if not ids:
                    break
                deleted += connection.execute(delete(table).where(table.c[rule.get('id_column', 'id')].in_(ids))).rowcount
        if args.apply:
            print(json.dumps({'mode': 'apply', 'table': name, 'cutoff': str(cutoff), 'deleted': deleted}))
    engine.dispose()


if __name__ == '__main__':
    main()
