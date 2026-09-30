"""Fetch Apple FindMy reports and store them in the POLIMAX PostgreSQL DB."""
import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))
from database import configuration  # noqa: E402

from fetch_reports_async import fetch_reports  # noqa: E402

LOGGER = logging.getLogger(__name__)
_engine = None


def postgres_engine():
    """Lazily create a guarded connection to the canonical PostgreSQL DB."""
    global _engine
    if _engine is None:
        _, url, enabled = configuration(PROJECT_ROOT)
        if (not enabled or url.drivername != "postgresql+psycopg"
                or url.database != "polimax_PostgreSQL"):
            raise RuntimeError("FindMy 匯入僅允許寫入 polimax_PostgreSQL")
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def utc_naive(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def insert_reports(beacon_id, owner, reports):
    """Atomically and idempotently append reports to both PostgreSQL consumers."""
    major = str(int(beacon_id, 16))
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    findmy_rows = []
    history_rows = []
    for report in reports:
        if report.get("latitude") is None or report.get("longitude") is None:
            continue
        timestamp = utc_naive(report["timestamp"])
        findmy_rows.append({
            "major": major,
            "owner": owner,
            "ble_mac": report["ble_mac"],
            "longitude": report["longitude"],
            "latitude": report["latitude"],
            "timestamp": timestamp,
            "created_at": created_at,
            "uid": None,
        })
        history_rows.append({
            "sheet_id": beacon_id,
            "latitude": report["latitude"],
            "longitude": report["longitude"],
            "timestamp": timestamp,
        })
    if not findmy_rows:
        return 0
    with postgres_engine().begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": 1886219127})
        inserted = _insert_missing(connection, '"FindMy"', findmy_rows,
                                   ("major", "ble_mac", "timestamp", "longitude", "latitude"))
        _insert_missing(connection, "new_reports", history_rows,
                        ("sheet_id", "timestamp", "longitude", "latitude"))
    return inserted


def _insert_missing(connection, table_name, rows, key_columns):
    """Bulk insert a batch while ignoring previously stored natural report keys."""
    if not rows:
        return 0
    columns = tuple(rows[0])
    values = []
    params = {}
    for index, row in enumerate(rows):
        names = []
        for column in columns:
            name = f"v{index}_{column}"
            names.append(f":{name}")
            params[name] = row[column]
        values.append(f"({', '.join(names)})")
    incoming_columns = ", ".join(columns)
    key_sql = ", ".join(f"incoming.{name}" for name in key_columns)
    selected = ", ".join(f"incoming.{name}" for name in columns)
    equality = " AND ".join(f"stored.{name} = incoming.{name}" for name in key_columns)
    order = ", ".join(f"incoming.{name}" for name in key_columns)
    statement = text(f"""
        INSERT INTO {table_name} ({incoming_columns})
        SELECT DISTINCT ON ({key_sql}) {selected}
        FROM (VALUES {', '.join(values)}) AS incoming ({incoming_columns})
        WHERE NOT EXISTS (
            SELECT 1 FROM {table_name} AS stored WHERE {equality}
        )
        ORDER BY {order}
    """)
    return connection.execute(statement, params).rowcount


def configured_beacons():
    with postgres_engine().connect() as connection:
        return connection.execute(text("""
            SELECT id, priv_b64, owner
            FROM "BeaconList"
            WHERE programmed = 'y' AND coalesce(priv_b64, '') <> ''
            ORDER BY id
        """)).mappings().all()


async def update_findmy():
    beacons = configured_beacons()
    LOGGER.info("FindMy 匯入開始；已啟用裝置數：%d", len(beacons))
    inserted = 0
    failed = 0
    for beacon in beacons:
        try:
            reports = await fetch_reports(beacon["priv_b64"])
            count = insert_reports(beacon["id"], beacon["owner"], reports)
            inserted += count
            LOGGER.info("FindMy 裝置回報已存入 PostgreSQL；新增筆數：%d", count)
        except Exception:
            failed += 1
            # Avoid logging private keys, report contents, owner names, or coordinates.
            LOGGER.error("FindMy 單一裝置匯入失敗")
    LOGGER.info("FindMy 匯入結束；成功新增 %d 筆，失敗裝置 %d 個", inserted, failed)
    if failed:
        raise RuntimeError(f"FindMy 匯入有 {failed} 個裝置失敗")
    return inserted


async def scheduler(interval: int = 3600):
    while True:
        try:
            await update_findmy()
        except Exception:
            LOGGER.error("FindMy 排程執行失敗")
        await asyncio.sleep(interval)


async def manual_update():
    await update_findmy()
    return {"status": "OK"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="持續每小時執行；預設單次執行")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(scheduler() if args.loop else update_findmy())
