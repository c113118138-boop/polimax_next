"""Prompt locally for PostgreSQL password and create a temporary libpq passfile."""
import getpass
import os
import subprocess
from pathlib import Path

path = Path('/tmp/polimax_pg_cutover_passfile')
if path.exists():
    raise SystemExit('Passfile already exists; inspect before replacing it')
password = getpass.getpass('polimax_admin PostgreSQL password: ')
if '\n' in password or '\r' in password:
    raise SystemExit('Password contains a line break')
escaped = password.replace('\\', '\\\\').replace(':', '\\:')
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as output:
    output.write('127.0.0.1:5432:polimax_PostgreSQL:polimax_admin:' + escaped + '\n')
env = {**os.environ, 'PGPASSFILE': str(path)}
result = subprocess.run(['psql', '-h', '127.0.0.1', '-U', 'polimax_admin', '-d', 'polimax_PostgreSQL', '-w', '-Atqc', 'SELECT 1'], env=env, capture_output=True, text=True)
if result.returncode != 0 or result.stdout.strip() != '1':
    path.unlink()
    raise SystemExit('PostgreSQL login failed; passfile removed')
print('PostgreSQL login verified; temporary passfile ready at', path)
