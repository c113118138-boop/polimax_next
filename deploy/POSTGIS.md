# PostGIS location support

The live and archive databases both require PostGIS. Install the pinned backend
requirements (including GeoAlchemy2 and Shapely) before starting application or
maintenance processes. GeoAlchemy2 registers SQLAlchemy geography reflection;
Shapely supports binding the returned geography WKB values during archival.
The database, legacy repository and retention entry points import GeoAlchemy2.

`scripts/add_location.sql` is a one-time migration for gps_readings, new_reports
and FindMy. It has already been applied to this deployment; do not rerun it.
For a new deployment, back up both databases, enable PostGIS in both, suspend
archive jobs during migration, apply to the archive then live database and
resume only after both schemas match. Existing archive tables must exist first.
The SQL runs in a transaction and fails if the function/columns already exist.

Each table keeps latitude/longitude as its source of truth. A BEFORE INSERT OR
UPDATE trigger populates location as geography(Point,4326), longitude first.
Null or out-of-range coordinates produce NULL; device sentinel values inside
valid ranges remain subject to the existing application filters. A GiST index
supports spatial searches. These changes assume input coordinates are WGS84.

API positions and trajectories continue to expose numeric lat/lng. Archive
manifests serialize WKB using the existing canonical string serializer, and
round-trip verification still precedes source deletion. No new distance API or
map UI is introduced by this change.

Validation (creates a disposable PostgreSQL cluster; no production credentials):

```sh
.venv/bin/python -m unittest discover -s tests -p test_retention.py
```

Requires PostgreSQL 16 binaries and its PostGIS extension files. The spatial test
checks the migration, reflection, coordinate updates, invalid coordinates,
meter-based distance, positions/trajectory API responses, archive round-trip,
verification, source deletion guards and repeated-run behavior.
