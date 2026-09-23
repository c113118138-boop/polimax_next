#!/usr/bin/env bash
# Run only after all POLIMAX writers and the GPS cleanup timer are stopped.
set -euo pipefail
umask 077
# Refuse a mixed-time backup while the production services are running.
for unit in polimax-next@5173.service polimax-next@5174.service \
    pmx-tracking@Indoor_Beacon_Agent.service \
    pmx-tracking@Outdoor_Beacon_Agent.service \
    pmx-tracking@Outdoor_GPS_Agent.service; do
    if systemctl --user is-active --quiet "$unit"; then
        echo "Refusing backup while $unit is active" >&2
        exit 2
    fi
done
root=/home/c113118138/polimax_next
backup_parent=/home/c113118138/migration_backups
mkdir -p -m 700 "$backup_parent"
backup_dir="$backup_parent/cutover-$(date +%Y%m%d-%H%M%S)"
mkdir -m 700 "$backup_dir"
echo "Backup directory: $backup_dir"
sudo mysqldump --single-transaction --skip-lock-tables --routines --events --triggers mqtt_data > "$backup_dir/mysql.sql"
tar -C "$root" -cf "$backup_dir/data.tar" .data env
if [[ -f "$root/.env" ]]; then
    tar -C "$root" -rf "$backup_dir/data.tar" .env
fi
sha256sum "$backup_dir/mysql.sql" "$backup_dir/data.tar" > "$backup_dir/SHA256SUMS"
echo "Backup complete: $backup_dir"
