"""
DWD-Vergleichsdaten via Bright Sky (https://brightsky.dev).

Bright Sky kapselt die offiziellen DWD-Open-Data-Dateien hinter einer
schlanken JSON-API. Wir holen einmal pro Stunde die neuesten Daten der
geographisch nächsten DWD-Station zum konfigurierten Standort und legen
sie als stündliche Werte in `dwd_readings` ab.
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import config, db

logger = logging.getLogger("dwd")

_BASE = "https://api.brightsky.dev"


def _fetch_json(url: str) -> dict:
    """Synchroner HTTPS-Aufruf (urllib aus stdlib, keine extra Dependency)."""
    req = urllib.request.Request(url, headers={"User-Agent": "wetterstation/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _station_names(sources: list[dict]) -> dict[int, str]:
    """Bevorzugt für alle Quellen derselben DWD-Station deren längsten Namen."""
    longest = {}
    for source in sources:
        station, name = source.get("dwd_station_id"), source.get("station_name")
        if station and name and len(name) > len(longest.get(station, "")):
            longest[station] = name
    return {
        source["id"]: longest.get(source.get("dwd_station_id")) or source.get("station_name") or f"DWD-{source['id']}"
        for source in sources if source.get("id") is not None
    }


async def fetch_and_store(days: int) -> int:
    """Holt die letzten `days` Tage und speichert sie. Liefert die Anzahl verarbeiteter Zeilen."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=max(1, days))
    # last_date in die Zukunft: stellt sicher, dass Bright Sky auch die
    # heutige laufende Stunde und ggf. die synop-Beobachtungen mitliefert
    # (sonst endet die Antwort u. U. bei der letzten historical-Stunde,
    # die einige Stunden hinterherhinkt).
    last_date = today + timedelta(days=1)
    params = {
        "date": start.isoformat(),
        "last_date": last_date.isoformat(),
        "tz": "UTC",
    }
    if config.DWD_STATION_ID:
        # Feste Station erzwingen – keine geografische Auto-Auswahl.
        params["dwd_station_id"] = config.DWD_STATION_ID
    else:
        params["lat"] = config.SITE_LAT
        params["lon"] = config.SITE_LON
    url = f"{_BASE}/weather?{urllib.parse.urlencode(params)}"
    try:
        payload = await asyncio.to_thread(_fetch_json, url)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(300).decode("utf-8", errors="replace")
        except Exception:
            pass
        logger.warning("DWD-Abruf: HTTP %s %s – %s", exc.code, exc.reason, body)
        return 0
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        logger.warning("DWD-Abruf: Verbindungsfehler: %s", exc)
        return 0

    rows = payload.get("weather", []) or []
    station_names = _station_names(payload.get("sources") or [])
    if not rows:
        logger.info("DWD-Abruf: Bright Sky lieferte 0 Datensätze für %s..%s",
                    start.isoformat(), last_date.isoformat())
        return 0

    to_insert: list[tuple] = []
    null_rows = 0
    latest_ts = None
    for r in rows:
        ts = r.get("timestamp")
        if not ts:
            continue
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        temp = r.get("temperature")
        wind = r.get("wind_speed")  # km/h -> m/s
        if temp is None and wind is None:
            null_rows += 1
            continue
        wind_ms = (float(wind) / 3.6) if wind is not None else None
        src_id = r.get("source_id")
        station = station_names.get(src_id, f"DWD-{src_id}") if src_id is not None else "DWD"
        to_insert.append((t, station, src_id, temp, wind_ms))
        if latest_ts is None or t > latest_ts:
            latest_ts = t

    if not to_insert:
        logger.info("DWD-Abruf: %d Datensätze geliefert, aber alle ohne Werte (DWD/Station-Lücke?)",
                    len(rows))
        return 0

    sql = """
        INSERT INTO dwd_readings (time, station, source_id, temperature_c, wind_ms)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (station, time) DO UPDATE SET
            temperature_c = EXCLUDED.temperature_c,
            wind_ms       = EXCLUDED.wind_ms,
            source_id     = EXCLUDED.source_id
        WHERE (dwd_readings.temperature_c, dwd_readings.wind_ms, dwd_readings.source_id)
              IS DISTINCT FROM (EXCLUDED.temperature_c, EXCLUDED.wind_ms, EXCLUDED.source_id)
    """
    async with db.pool().acquire() as conn:
        await conn.executemany(sql, to_insert)

    age_h = (datetime.now(timezone.utc) - latest_ts).total_seconds() / 3600 if latest_ts else None
    logger.info("DWD-Abruf: %d Zeilen verarbeitet, neuestes %s (Alter %.1f h)%s",
                len(to_insert),
                latest_ts.isoformat(timespec="minutes") if latest_ts else "–",
                age_h if age_h is not None else -1,
                f", {null_rows} ohne Werte verworfen" if null_rows else "")
    return len(to_insert)


async def ensure_initial_backfill() -> None:
    """Beim ersten Start die letzten DWD_BACKFILL_DAYS Tage holen."""
    async with db.pool().acquire() as conn:
        exists = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM dwd_readings)")
    if not exists:
        logger.info("DWD-Backfill: hole %d Tage", config.DWD_BACKFILL_DAYS)
        try:
            count = await fetch_and_store(config.DWD_BACKFILL_DAYS)
            logger.info("DWD-Backfill: %d Zeilen geschrieben", count)
        except Exception as exc:
            logger.warning("DWD-Backfill fehlgeschlagen: %s", exc)


async def run_periodic() -> None:
    """Endlosschleife: alle DWD_REFRESH_MINUTES die letzten 2 Tage neu holen."""
    interval = max(5, config.DWD_REFRESH_MINUTES) * 60
    while True:
        try:
            await fetch_and_store(days=2)
        except Exception as exc:
            logger.warning("DWD-Refresh fehlgeschlagen: %s", exc)
        await asyncio.sleep(interval)
