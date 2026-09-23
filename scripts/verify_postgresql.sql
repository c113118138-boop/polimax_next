-- Read-only verification of the 2026-09-21 test import.
SELECT current_database() AS database, current_user AS role,
       (SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public') AS tables,
       (SELECT count(*) FROM pg_catalog.pg_views WHERE schemaname = 'public') AS views,
       (SELECT count(*) FROM pg_catalog.pg_indexes WHERE schemaname = 'public') AS indexes;

SELECT 'BeaconList' AS table_name, count(*) AS rows FROM "BeaconList"
UNION ALL SELECT 'CarList', count(*) FROM "CarList"
UNION ALL SELECT 'EquipmentList', count(*) FROM "EquipmentList"
UNION ALL SELECT 'form_flows', count(*) FROM form_flows
UNION ALL SELECT 'formio_responses', count(*) FROM formio_responses
UNION ALL SELECT 'gps_readings', count(*) FROM gps_readings
ORDER BY table_name;

SELECT 'Findmy_latest' AS view_name, count(*) AS rows FROM "Findmy_latest"
UNION ALL SELECT 'car_realtime', count(*) FROM car_realtime
UNION ALL SELECT 'latest_scanned_devices', count(*) FROM latest_scanned_devices
ORDER BY view_name;
