-- Converted from the three views in the 2026-09-21 MySQL schema dump.
-- Source timestamps are stored as naive Taipei wall time.
BEGIN;

CREATE VIEW "Findmy_latest" AS
SELECT "ID", major, owner, ble_mac, longitude, latitude, "timestamp", created_at, uid
FROM "FindMy"
WHERE created_at >= (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei') - INTERVAL '7 days';

CREATE VIEW car_realtime AS
SELECT id, "SN", client_id, speed1, speed2, speed3, battery,
       latitude, longitude, record_time, created_at
FROM gps_readings
WHERE created_at >= (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei') - INTERVAL '7 days'
ORDER BY created_at DESC;

CREATE VIEW latest_scanned_devices AS
SELECT id, short_id, client_id, major, minor, "ChargePower", "timestamp", rssi, created_at
FROM (
    SELECT short_id, id, client_id, "ChargePower", major, minor, rssi,
           "timestamp", created_at,
           ROW_NUMBER() OVER (PARTITION BY client_id, major ORDER BY created_at DESC) AS rn
    FROM sensor_readings
) AS ranked_data
WHERE rn = 1;

COMMIT;
