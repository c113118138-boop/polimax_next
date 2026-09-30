"""Back up PostgreSQL and POLIMAX persistent files under the application write lock."""
import hashlib
import json
import os
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from database import configuration
from settings import settings
from retention import archive_url


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    os.umask(0o077)
    data, url, native = configuration(ROOT)
    if not native or url.get_backend_name() != 'postgresql':
        raise SystemExit('PostgreSQL mode required')
    values = settings(ROOT)
    parent = Path(values.get('AMS_BACKUP_DIR') or ROOT / '.backups' / 'scheduled')
    if not parent.is_absolute():
        parent = ROOT / parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(parent, 0o700)
    destination = parent / datetime.now().strftime('%Y%m%d-%H%M%S')
    destination.mkdir(mode=0o700)
    db_path = destination / 'postgresql.dump'
    expired_path = destination / 'expired.dump'
    files_path = destination / 'persistent.tar'
    key_name = 'polimax:' + hashlib.sha256(str(url.database).encode()).hexdigest()[:32]
    lock_key = int(hashlib.sha256(key_name.encode()).hexdigest()[:15], 16)
    engine = create_engine(url, pool_pre_ping=True, connect_args={'connect_timeout': 10})
    try:
        with engine.connect() as connection:
            connection.execute(text("SET statement_timeout = '60s'"))
            connection.execute(text('SELECT pg_advisory_lock(:key)'), {'key': lock_key})
            connection.commit()
            try:
                env = {**os.environ, 'PGPASSWORD': url.password}
                subprocess.run([
                    'pg_dump', '-h', url.host, '-p', str(url.port), '-U', url.username,
                    '-d', url.database, '-Fc', '--no-owner', '--no-acl', '-f', str(db_path),
                ], env=env, check=True, capture_output=True, text=True)
                # The same source advisory lock excludes the archive worker, so
                # these dumps cannot straddle an archive-and-delete batch.
                expired_url = archive_url(url, ROOT)
                archive_enabled = values.get('AMS_ARCHIVE_ENABLED', '0') == '1'
                if archive_enabled:
                    subprocess.run([
                        'pg_dump', '-h', expired_url.host, '-p', str(expired_url.port), '-U', expired_url.username,
                        '-d', expired_url.database, '-Fc', '--no-owner', '--no-acl', '-f', str(expired_path),
                    ], env=env, check=True, capture_output=True, text=True)
                with tarfile.open(files_path, 'w') as archive:
                    for relative in ('.data/responses', '.data/files', '.data/permissions', '.data/findmy', 'env', '.env'):
                        path = ROOT / relative
                        if path.exists():
                            archive.add(path, arcname=relative)
                manifest = {
                    'database': url.database,
                    'created_at': datetime.now().isoformat(timespec='seconds'),
                    'postgresql.dump': digest(db_path),
                    'archive_database': expired_url.database if archive_enabled else None,
                    'persistent.tar': digest(files_path),
                    'scope': 'database snapshot and application-locked persistent files',
                }
                if archive_enabled:
                    manifest['expired.dump'] = digest(expired_path)
                (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            finally:
                connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': lock_key})
                connection.commit()
    finally:
        engine.dispose()
    print('BACKUP_COMPLETE', destination)


if __name__ == '__main__':
    main()
