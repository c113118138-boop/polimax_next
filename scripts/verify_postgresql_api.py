"""Read-only FastAPI check against a PostgreSQL database; prompts for password."""
import argparse
import getpass
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', default='5432')
    parser.add_argument('--database', default='polimax_PostgreSQL')
    parser.add_argument('--user', default='polimax_admin')
    args = parser.parse_args()
    password = os.environ.get('POSTGRES_PASSWORD') or getpass.getpass('PostgreSQL password: ')
    with tempfile.TemporaryDirectory(prefix='polimax-pg-api-') as folder:
        data = Path(folder)
        shutil.copytree(ROOT / '.data' / 'responses', data / 'responses')
        os.environ.update({
            'AMS_DATABASE_MODE': 'postgresql',
            'POSTGRES_HOST': args.host,
            'POSTGRES_PORT': args.port,
            'POSTGRES_DATABASE': args.database,
            'POSTGRES_USER': args.user,
            'POSTGRES_PASSWORD': password,
            'AMS_DATA_DIR': str(data),
            'AMS_RESPONSES_DIR': str(data / 'responses'),
            'AMS_AUTH_MODE': 'test',
            'PREVIEW_LOGIN_ENABLED': '1',
        })
        sys.path.insert(0, str(ROOT / 'backend'))
        from fastapi.testclient import TestClient
        import app
        with TestClient(app.app) as client:
            health = client.get('/api/health')
            health.raise_for_status()
            assert health.json()['database'] == 'PostgreSQL'
            login = client.post('/api/auth/login', json={'role': 'admin'}, headers={'x-ams-client': 'preview'})
            login.raise_for_status()
            resources = client.get('/api/resources')
            resources.raise_for_status()
            bookings = client.get('/api/bookings')
            bookings.raise_for_status()
            values = bookings.json()
            if values:
                detail = client.get('/api/bookings/' + values[0]['id'])
                detail.raise_for_status()
            print(json.dumps({
                'database': health.json()['database'],
                'resources': len(resources.json()),
                'bookings': len(values),
                'booking_detail': 'ok' if values else 'no_bookings',
                'writes': 'none',
            }, ensure_ascii=False))


if __name__ == '__main__':
    main()
