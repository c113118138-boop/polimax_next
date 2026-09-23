"""Export the live MySQL schema and a non-atomic test snapshot for PostgreSQL.

The output contains business data. Keep it outside Git and protect/delete it after use.
Views require SHOW VIEW privilege; the exporter refuses to silently omit them.
"""
import argparse
import csv
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from database import configuration


def qi(value):
    return '"' + value.replace('"', '""') + '"'


def lit(value):
    return "'" + str(value).replace("'", "''") + "'"


def pg_type(row):
    kind = row.DATA_TYPE.lower()
    if kind in ('varchar', 'char'):
        # PostgreSQL CHAR pads empty strings; MySQL CHAR values can be empty.
        return 'varchar(' + str(row.CHARACTER_MAXIMUM_LENGTH) + ')'
    if kind == 'text':
        return 'text'
    if kind in ('int', 'tinyint'):
        return 'integer' if kind == 'int' else 'smallint'
    if kind == 'bigint':
        return 'bigint'
    if kind == 'decimal':
        return f'numeric({row.NUMERIC_PRECISION},{row.NUMERIC_SCALE})'
    if kind == 'double':
        return 'double precision'
    if kind == 'enum':
        return 'text'
    if kind == 'date':
        return 'date'
    if kind in ('datetime', 'timestamp'):
        # Match the application's naive Taipei wall-time convention.
        return 'timestamp without time zone'
    raise ValueError(f'Unsupported MySQL type: {row.TABLE_NAME}.{row.COLUMN_NAME} {row.COLUMN_TYPE}')


def copy_cell(value):
    if value is None:
        return r'\N'
    if isinstance(value, (date, datetime)):
        value = value.isoformat(sep=' ') if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, bytes):
        raise ValueError('Binary column found; add an explicit conversion')
    return str(value).replace('\\', r'\\').replace('\t', r'\t').replace('\n', r'\n').replace('\r', r'\r')


def export(destination):
    destination = destination.resolve()
    if any(ch in str(destination) for ch in "'\n\r"):
        raise ValueError('Output path must not contain quotes or line breaks')
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(destination, 0o700)
    _, url, mysql = configuration(ROOT)
    if url.get_backend_name() != 'mysql':
        raise RuntimeError('Source must be the configured MySQL database')
    engine = create_engine(url, pool_pre_ping=True, connect_args={'connect_timeout': 10})
    try:
        with engine.connect() as c:
            c.execute(text("SET time_zone = '+08:00'"))
            db = c.execute(text('SELECT DATABASE()')).scalar_one()
            params = {'db': db}
            tables = c.execute(text("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=:db AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"), params).scalars().all()
            views = c.execute(text("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=:db AND TABLE_TYPE='VIEW' ORDER BY TABLE_NAME"), params).scalars().all()
            columns = c.execute(text("SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE,COLUMN_TYPE,CHARACTER_MAXIMUM_LENGTH,NUMERIC_PRECISION,NUMERIC_SCALE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,ORDINAL_POSITION FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=:db AND TABLE_NAME IN (SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=:db AND TABLE_TYPE='BASE TABLE') ORDER BY TABLE_NAME,ORDINAL_POSITION"), params).all()
            indexes = c.execute(text('SELECT TABLE_NAME,INDEX_NAME,NON_UNIQUE,COLUMN_NAME,SUB_PART,SEQ_IN_INDEX FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=:db ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX'), params).all()
            fks = c.execute(text('SELECT TABLE_NAME,COLUMN_NAME,REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME,CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=:db AND REFERENCED_TABLE_NAME IS NOT NULL ORDER BY TABLE_NAME,CONSTRAINT_NAME,ORDINAL_POSITION'), params).all()
            by_table = {table: [] for table in tables}
            for row in columns:
                by_table[row.TABLE_NAME].append(row)
            by_index = {}
            for row in indexes:
                if row.SUB_PART is not None:
                    raise ValueError(f'Prefix index needs manual conversion: {row.TABLE_NAME}.{row.INDEX_NAME}')
                by_index.setdefault((row.TABLE_NAME, row.INDEX_NAME, row.NON_UNIQUE), []).append(row.COLUMN_NAME)
            schema = ['-- Generated from MySQL metadata. Test snapshot only.', 'BEGIN;', 'SET TIME ZONE '+lit('Asia/Taipei')+';']
            on_update = []
            for table in tables:
                definitions = []
                for row in by_table[table]:
                    col = qi(row.COLUMN_NAME)
                    col_type = pg_type(row)
                    extra = row.EXTRA.lower()
                    definition = f'  {col} {col_type}'
                    if 'auto_increment' in extra:
                        if col_type not in ('integer', 'bigint'):
                            raise ValueError(f'Identity type requires manual conversion: {table}.{row.COLUMN_NAME}')
                        definition += ' GENERATED BY DEFAULT AS IDENTITY'
                    elif row.COLUMN_DEFAULT is not None:
                        default = row.COLUMN_DEFAULT
                        definition += ' DEFAULT ' + ('CURRENT_TIMESTAMP' if str(default).upper() == 'CURRENT_TIMESTAMP' else lit(default))
                    if row.IS_NULLABLE == 'NO':
                        definition += ' NOT NULL'
                    if 'unsigned' in row.COLUMN_TYPE:
                        definition += f' CHECK ({col} >= 0)'
                    if row.DATA_TYPE == 'enum':
                        choices = re.findall(r"'((?:[^']|'')*)'", row.COLUMN_TYPE)
                        definition += f' CHECK ({col} IN (' + ', '.join(lit(x.replace("''", "'")) for x in choices) + '))'
                    definitions.append(definition)
                    if 'on update current_timestamp' in extra:
                        on_update.append((table, row.COLUMN_NAME))
                primary = next((cols for (t, name, _), cols in by_index.items() if t == table and name == 'PRIMARY'), None)
                if primary:
                    definitions.append('  PRIMARY KEY (' + ', '.join(qi(x) for x in primary) + ')')
                schema.append('CREATE TABLE ' + qi(table) + ' (\n' + ',\n'.join(definitions) + '\n);')
            schema.append('COMMIT;')
            (destination / 'schema.sql').write_text('\n'.join(schema) + '\n')
            post = ['BEGIN;', 'SET TIME ZONE '+lit('Asia/Taipei')+';']
            for (table, name, non_unique), cols in by_index.items():
                if name == 'PRIMARY':
                    continue
                prefix = 'CREATE INDEX' if non_unique else 'CREATE UNIQUE INDEX'
                post.append(f'{prefix} {qi(table + '_' + name)} ON {qi(table)} (' + ', '.join(qi(x) for x in cols) + ');')
            for row in fks:
                post.append(f'ALTER TABLE {qi(row.TABLE_NAME)} ADD CONSTRAINT {qi(row.CONSTRAINT_NAME)} FOREIGN KEY ({qi(row.COLUMN_NAME)}) REFERENCES {qi(row.REFERENCED_TABLE_NAME)} ({qi(row.REFERENCED_COLUMN_NAME)});')
            if on_update:
                # A dedicated function per column keeps different legacy names correct.
                for table, column in on_update:
                    fn = 'polimax_touch_' + re.sub(r'[^a-z0-9_]', '_', table.lower()) + '_' + column.lower()
                    post.append(f'CREATE FUNCTION {qi(fn)}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.{qi(column)} = CURRENT_TIMESTAMP; RETURN NEW; END $$;')
                    post.append(f'CREATE TRIGGER {qi(fn)} BEFORE UPDATE ON {qi(table)} FOR EACH ROW EXECUTE FUNCTION {qi(fn)}();')
            for table in tables:
                identity = [row.COLUMN_NAME for row in by_table[table] if 'auto_increment' in row.EXTRA.lower()]
                for column in identity:
                    post.append(f"SELECT setval(pg_get_serial_sequence({lit(qi(table))}, {lit(column)}), COALESCE((SELECT MAX({qi(column)}) FROM {qi(table)}), 1), (SELECT COUNT(*) > 0 FROM {qi(table)}));")
            post.append('COMMIT;')
            (destination / 'post_data.sql').write_text('\n'.join(post) + '\n')
            load = [r'\set ON_ERROR_STOP on', f'\\i {destination / "schema.sql"}']
            # The live source can change during this export. This is not a consistent cutover backup.
            for table in tables:
                names = [row.COLUMN_NAME for row in by_table[table]]
                path = destination / (table + '.copy')
                with path.open('x', encoding='utf-8', newline='') as f:
                    rows = c.exec_driver_sql('SELECT ' + ', '.join('`'+x.replace('`','``')+'`' for x in names) + ' FROM `'+table.replace('`','``')+'`')
                    count = 0
                    for values in rows:
                        f.write('\t'.join(copy_cell(x) for x in values) + '\n')
                        count += 1
                load.append(f"\\copy {qi(table)} (" + ', '.join(qi(x) for x in names) + f") FROM '{path}' WITH (FORMAT text, NULL '\\N')")
                print(f'{table}: {count} rows')
            load.append(f'\\i {destination / "post_data.sql"}')
            (destination / 'load.psql').write_text('\n'.join(load) + '\n')
            (destination / 'README.txt').write_text('Source: '+db+'\nViews still require separate conversion: '+', '.join(views)+'\nLive export is not a synchronized backup.\n')
            os.chmod(destination / 'schema.sql', 0o600)
            os.chmod(destination / 'post_data.sql', 0o600)
            os.chmod(destination / 'load.psql', 0o600)
            os.chmod(destination / 'README.txt', 0o600)
            for table in tables:
                os.chmod(destination / (table + '.copy'), 0o600)
            print('Output:', destination)
            print('Views requiring manual conversion:', ', '.join(views))
    finally:
        engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path, help='New private directory outside Git')
    args = parser.parse_args()
    export(args.destination)
