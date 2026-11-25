"""Last rain event from the station's sampled wet/dry signal."""
from datetime import datetime, timezone

from . import config, db


_SQL = """
WITH latest AS (
    SELECT time, rain FROM readings WHERE sensor_id = $1 ORDER BY time DESC LIMIT 1
),
wet AS (
    SELECT time FROM readings
    WHERE sensor_id = $1 AND rain IS TRUE ORDER BY time DESC LIMIT 1
),
preceding AS (
    SELECT r.time, r.rain FROM readings r
    WHERE r.sensor_id = $1 AND r.rain IS NOT TRUE AND r.time < (SELECT time FROM wet)
    ORDER BY r.time DESC LIMIT 1
),
samples AS (
    SELECT r.time, lag(r.time) OVER (ORDER BY r.time DESC) AS newer
    FROM readings r
    WHERE r.sensor_id = $1 AND r.rain IS TRUE AND r.time <= (SELECT time FROM wet)
      AND r.time > coalesce((SELECT time FROM preceding), '-infinity'::timestamptz)
),
first_gap AS (
    SELECT max(newer) AS time FROM samples WHERE newer - time > make_interval(secs => $2)
),
event AS (
    SELECT min(time) AS start_time
    FROM samples
    WHERE time >= coalesce((SELECT time FROM first_gap), '-infinity'::timestamptz)
)
SELECT (SELECT time FROM latest) AS latest_time,
       (SELECT rain FROM latest) AS latest_rain,
       (SELECT time FROM wet) AS last_wet,
       (SELECT start_time FROM event) AS first_wet,
       (SELECT time FROM preceding) AS previous_time,
       (SELECT rain FROM preceding) AS previous_rain,
       (SELECT time FROM first_gap) IS NOT NULL AS split_at_gap
"""


def summarize(row, now: datetime, gap_seconds: int) -> dict:
    def epoch(dt):
        return int(dt.timestamp() * 1000) if dt else None

    latest = row["latest_time"]
    first = row["first_wet"]
    last = row["last_wet"]
    previous = row["previous_time"]
    if not latest or row["latest_rain"] is None or (now - latest).total_seconds() > gap_seconds:
        status = "unknown"
    else:
        status = "raining" if row["latest_rain"] else "dry"
    bounded_start = bool(first and previous and row["previous_rain"] is False
                         and not row["split_at_gap"] and (first - previous).total_seconds() <= gap_seconds)
    return {
        "status": status,
        "latest_at": epoch(latest),
        "first_wet_at": epoch(first),
        "last_wet_at": epoch(last),
        "duration_seconds": int((last - first).total_seconds()) if first and last else None,
        "since_last_wet_seconds": max(0, int((now - last).total_seconds())) if last else None,
        "start_bounded": bounded_start,
    }


async def latest_event(sensor_id: str) -> dict:
    gap = config.RAIN_GAP_SECONDS
    async with db.pool().acquire() as connection:
        row = await connection.fetchrow(_SQL, sensor_id, gap)
    return summarize(row, datetime.now(timezone.utc), gap)
