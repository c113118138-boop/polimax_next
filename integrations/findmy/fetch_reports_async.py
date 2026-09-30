import logging
from datetime import datetime, timedelta, timezone

from _login import get_account_async

from findmy import KeyPair

logging.basicConfig(level=logging.INFO)


def _as_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def fetch_reports(priv_key: str) -> list[dict]:
    key = KeyPair.from_b64(priv_key)
    acc = await get_account_async()

    try:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=7)
        reports = await acc.fetch_location_history(key)
        sorted_reports = sorted(
            (report for report in reports if _as_utc(report.timestamp) >= cutoff),
            key=lambda report: _as_utc(report.timestamp),
        )
        findmy_reports = [{
            "ble_mac": report.key.mac_address,
            "longitude": report.longitude,
            "latitude":report.latitude,
            "timestamp":report.timestamp
        }
            for report in sorted_reports]
        return findmy_reports
    finally:
        await acc.close()
