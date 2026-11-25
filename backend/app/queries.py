"""Zeitreihen und CSV-Rohdaten für die Dachstation."""
from collections.abc import AsyncIterator
from math import isfinite

from . import db
from .periods import DAY, FIVE_MINUTES, HOUR, Period, bucket_expression

# Jede Angabe verbindet eine API-Messgröße mit ihren Rollup-Spalten.
_METRICS = {
    "temperature_c": ("temp", ("avg", "min", "max"), 2),
    "wind_ms": ("wind", ("avg", "max"), 2),
    "twilight_lux": ("twilight", ("avg", "max"), 0),
    "west_klux": ("west", ("avg",), 2),
    "south_klux": ("south", ("avg", "max"), 2),
    "east_klux": ("east", ("avg",), 2),
}
ROLLUP_COLUMNS = tuple(
    f"{prefix}_{operation}" for prefix, operations, _ in _METRICS.values() for operation in operations
) + ("rain_any",)
RAW_AGGREGATES = ", ".join(
    f"{operation}({metric}) AS {prefix}_{operation}"
    for metric, (prefix, operations, _) in _METRICS.items() for operation in operations
) + ", bool_or(rain) AS rain_any"


def rounded(value: float | None, digits: int = 2) -> float | None:
    if value is None or not isfinite(value):
        return None
    return round(float(value), digits)


async def fetch_series(sensor_id: str, period: Period) -> dict:
    if period.seconds == FIVE_MINUTES:
        source, table, column = "raw", "readings", "time"
        bucket = bucket_expression(FIVE_MINUTES)
        aggregate_fields = RAW_AGGREGATES
        group = "GROUP BY 1"
    else:
        source = "hourly" if period.seconds == HOUR else "daily"
        table, column = f"readings_{source}", "bucket"
        bucket = "bucket::timestamptz"
        aggregate_fields = ", ".join(ROLLUP_COLUMNS)
        group = ""

    where, tail = period.where(column, 2, daily=period.seconds == DAY)
    sql = f"""
        SELECT (extract(epoch FROM {bucket}) * 1000)::bigint AS t,
               {aggregate_fields}
        FROM {table}
        WHERE sensor_id = $1 AND {where}
        {group}
        ORDER BY 1
    """
    async with db.pool().acquire() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            rows = await conn.fetch(sql, sensor_id, *tail)
            stats = await _fetch_stats(conn, sensor_id, source, table, where, tail)

    measurements = {
        metric: {
            operation: [rounded(row[f"{prefix}_{operation}"], digits) for row in rows]
            for operation in operations
        }
        for metric, (prefix, operations, digits) in _METRICS.items()
    }
    return {
        "range": period.name,
        "source": source,
        "bucket_seconds": period.seconds,
        "count": len(rows),
        "stats": stats,
        "t": [row["t"] for row in rows],
        **measurements,
        "rain": [int(bool(row["rain_any"])) for row in rows],
    }


async def _fetch_stats(conn, sensor_id, source, table, where, tail) -> dict:
    if source == "raw":
        fields = """
            min(temperature_c) tmin, max(temperature_c) tmax, avg(temperature_c) tavg,
            min(wind_ms) wmin, max(wind_ms) wmax, avg(wind_ms) wavg,
            min(south_klux) smin, max(south_klux) smax, avg(south_klux) savg
        """
    else:
        fields = """
            min(temp_min) tmin, max(temp_max) tmax, avg(temp_avg) tavg,
            min(wind_avg) wmin, max(wind_max) wmax, avg(wind_avg) wavg,
            min(south_avg) smin, max(south_max) smax, avg(south_avg) savg
        """
    row = await conn.fetchrow(f"SELECT {fields} FROM {table} WHERE sensor_id = $1 AND {where}", sensor_id, *tail)
    return {
        metric: {name: rounded(row[prefix + name]) for name in ("min", "max", "avg")}
        for metric, prefix in (("temperature_c", "t"), ("wind_ms", "w"), ("south_klux", "s"))
    }


async def fetch_latest(sensor_id: str) -> dict | None:
    async with db.pool().acquire() as conn:
        row = await conn.fetchrow("""
            SELECT (extract(epoch FROM time) * 1000)::bigint AS t,
                   temperature_c, wind_ms, twilight_lux, west_klux, south_klux, east_klux, rain
            FROM readings WHERE sensor_id = $1
            ORDER BY time DESC LIMIT 1
        """, sensor_id)
    if not row:
        return None
    return {
        "t": row["t"],
        **{field: rounded(row[field], digits) for field, (_, _, digits) in _METRICS.items()},
        "rain": int(bool(row["rain"])),
    }


async def stream_raw_for_export(sensor_id: str, period: Period) -> AsyncIterator:
    """Liest Rohmessungen blockweise aus einem konsistenten DB-Snapshot."""
    where, tail = period.where("time", 2)
    sql = f"""
        SELECT time, temperature_c, wind_ms, twilight_lux, west_klux, south_klux, east_klux, rain
        FROM readings WHERE sensor_id = $1 AND {where} ORDER BY time
    """
    async with db.pool().acquire() as conn:
        async with conn.transaction(readonly=True):
            async for row in conn.cursor(sql, sensor_id, *tail, prefetch=512):
                yield row
