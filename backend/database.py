"""Backend-only database configuration; no automatic fallback on errors."""
import os
from pathlib import Path

from settings import settings, data_path
from sqlalchemy import URL


def configuration(root: Path):
    values = settings(root)
    data = data_path(root, values)
    mode = values.get('AMS_DATABASE_MODE', 'mysql')
    if mode not in ('mysql', 'postgresql', 'demo'):
        raise RuntimeError('AMS_DATABASE_MODE must be mysql, postgresql or demo')
    if mode == 'demo':
        return data, os.getenv('PREVIEW_DATABASE_URL') or f'sqlite:///{data / "preview.sqlite3"}', False
    if mode == 'postgresql':
        required = ('POSTGRES_HOST', 'POSTGRES_DATABASE', 'POSTGRES_USER', 'POSTGRES_PASSWORD')
        if any(not values.get(key) for key in required):
            raise RuntimeError('請設定 POSTGRES_HOST、POSTGRES_DATABASE、POSTGRES_USER、POSTGRES_PASSWORD')
        url = URL.create('postgresql+psycopg', username=values['POSTGRES_USER'],
                         password=values['POSTGRES_PASSWORD'], host=values['POSTGRES_HOST'],
                         port=int(values.get('POSTGRES_PORT', '5432')),
                         database=values['POSTGRES_DATABASE'])
        return data, url, True
    required = ('MYSQL_HOST', 'MYSQL_DATABASE', 'MYSQL_USER', 'MYSQL_PASSWORD')
    if any(not values.get(key) for key in required):
        raise RuntimeError('請在 polimax_next/env 設定 MYSQL_HOST、MYSQL_DATABASE、MYSQL_USER、MYSQL_PASSWORD')
    url = URL.create('mysql+pymysql', username=values['MYSQL_USER'],
                     password=values['MYSQL_PASSWORD'], host=values['MYSQL_HOST'],
                     port=int(values.get('MYSQL_PORT', '3306')),
                     database=values['MYSQL_DATABASE'],
                     query={'charset': values.get('MYSQL_CHARSET', 'utf8mb4')})
    return data, url, True
