"""Backend-only database configuration. Never fall back after a MySQL error."""
import os
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import URL


def configuration(root: Path):
    data = Path(os.getenv('PREVIEW_DATA_DIR', str(root / '.data')))
    mode = os.getenv('AMS_DATABASE_MODE', 'mysql')
    if mode not in ('mysql', 'demo'):
        raise RuntimeError('AMS_DATABASE_MODE must be mysql or demo')
    if mode == 'demo':
        return data, os.getenv('PREVIEW_DATABASE_URL') or f'sqlite:///{data / "preview.sqlite3"}', False
    values = {**dotenv_values(root / 'env'), **dotenv_values(root / '.env'), **os.environ}
    required = ('MYSQL_HOST', 'MYSQL_DATABASE', 'MYSQL_USER', 'MYSQL_PASSWORD')
    if any(not values.get(key) for key in required):
        raise RuntimeError('請在 polimax_next/env 設定 MYSQL_HOST、MYSQL_DATABASE、MYSQL_USER、MYSQL_PASSWORD')
    url = URL.create('mysql+pymysql', username=values['MYSQL_USER'],
                     password=values['MYSQL_PASSWORD'], host=values['MYSQL_HOST'],
                     port=int(values.get('MYSQL_PORT', '3306')),
                     database=values['MYSQL_DATABASE'],
                     query={'charset': values.get('MYSQL_CHARSET', 'utf8mb4')})
    return data, url, True
