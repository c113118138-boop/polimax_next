"""Bounded GPS trajectory results and retention queries."""
from sqlalchemy import select, func, or_


def trajectory_rows(connection, table, client_id, start, end, limit):
    valid = (table.c.client_id == client_id, table.c.created_at >= start,
             table.c.created_at < end, table.c.latitude.between(-90, 90),
             table.c.longitude.between(-180, 180), func.abs(table.c.latitude) > 0.001,
             func.abs(table.c.longitude) > 0.001)
    ranked = select(table, func.row_number().over(order_by=(table.c.created_at, table.c.id)).label('_n'),
                    func.count().over().label('_total')).where(*valid).subquery()
    stride = func.ceil((ranked.c._total - 1) / (limit - 1))
    query = select(ranked).where(or_(ranked.c._total <= limit,
                                    ranked.c._n == ranked.c._total,
                                    (ranked.c._n - 1) % func.nullif(stride, 0) == 0)).order_by(ranked.c._n)
    rows = connection.execute(query).mappings().all()
    return rows, int(rows[0]['_total']) if rows else 0


def expired_ids(connection, table, cutoff, batch_size, *, group_columns=('client_id',),
                time_column='created_at', latest_columns=('record_time',), id_column='id'):
    newer = table.alias('newer')
    predicates = [table.c[time_column] < cutoff]
    predicates.extend(table.c[key].is_not(None) for key in group_columns)
    for latest in latest_columns:
        old_time, new_time = table.c[latest], newer.c[latest]
        has_newer = select(newer.c[id_column]).where(
            *(newer.c[key] == table.c[key] for key in group_columns),
            or_(new_time > old_time,
                old_time.is_(None) & new_time.is_not(None),
                (new_time == old_time) & (newer.c[id_column] > table.c[id_column]),
                new_time.is_(None) & old_time.is_(None) & (newer.c[id_column] > table.c[id_column]))).exists()
        predicates.append(has_newer)
    return list(connection.execute(select(table.c[id_column]).where(*predicates)
                .order_by(table.c[time_column], table.c[id_column]).limit(batch_size)).scalars())


RETENTION_RULES = {
    'gps_readings': {},
    'new_reports': {'group_columns': ('sheet_id',), 'time_column': 'timestamp', 'latest_columns': ('timestamp',)},
    'Outdoor_Beacon_readings': {'group_columns': ('client_id', 'major', 'minor'), 'latest_columns': ('created_at', 'record_time')},
    'FindMy': {'group_columns': ('major',), 'id_column': 'ID', 'latest_columns': ('timestamp', 'created_at')},
}
