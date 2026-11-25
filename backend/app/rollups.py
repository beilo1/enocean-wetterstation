"""Erzeugt und aktualisiert die gespeicherten Stunden- und Tageswerte."""
import asyncio
import logging

from . import config, db
from .queries import RAW_AGGREGATES, ROLLUP_COLUMNS

logger = logging.getLogger(__name__)
_COLUMNS = (*ROLLUP_COLUMNS, "n")
_ROLLUPS = (
    ("readings_hourly", "date_trunc('hour', time)", "date_trunc('hour', now() - interval '3 hours')"),
    ("readings_daily", "date_trunc('day', time)::date", "date_trunc('day', now() - interval '2 days')"),
)


def _upsert_sql(table: str, bucket: str, cutoff: str | None) -> str:
    where = f"WHERE time >= {cutoff}" if cutoff else ""
    assignments = ", ".join(f"{name} = EXCLUDED.{name}" for name in _COLUMNS)
    old_values = ", ".join(f"stored.{name}" for name in _COLUMNS)
    new_values = ", ".join(f"EXCLUDED.{name}" for name in _COLUMNS)
    return f"""
        INSERT INTO {table} AS stored (bucket, sensor_id, {', '.join(_COLUMNS)})
        SELECT {bucket}, sensor_id, {RAW_AGGREGATES}, count(*)
        FROM readings {where}
        GROUP BY 1, sensor_id
        ON CONFLICT (sensor_id, bucket) DO UPDATE SET {assignments}
        WHERE ({old_values}) IS DISTINCT FROM ({new_values})
    """


async def ensure_backfilled() -> None:
    """Fehlende Rollup-Tabellen aus Rohmessungen befüllen."""
    async with db.pool().acquire() as conn:
        for table, bucket, _ in _ROLLUPS:
            if not await conn.fetchval(f"SELECT EXISTS (SELECT 1 FROM {table})"):
                await conn.execute(_upsert_sql(table, bucket, None))


async def refresh_recent() -> None:
    """Kürzlich abgeschlossene und laufende Aggregate aktualisieren."""
    async with db.pool().acquire() as conn:
        for table, bucket, cutoff in _ROLLUPS:
            await conn.execute(_upsert_sql(table, bucket, cutoff))


async def run_periodic() -> None:
    while True:
        try:
            await refresh_recent()
        except Exception:
            logger.exception("Rollup-Aktualisierung fehlgeschlagen")
        await asyncio.sleep(config.ROLLUP_REFRESH_SECONDS)
