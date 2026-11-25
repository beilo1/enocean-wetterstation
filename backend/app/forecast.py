"""Short-term Open-Meteo forecast, shared by all dashboard clients."""
import asyncio
import json
import logging
from datetime import datetime, timezone
from math import isfinite
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import config

logger = logging.getLogger(__name__)
URL = "https://api.open-meteo.com/v1/forecast"
FIELDS = ("temperature_2m", "precipitation_probability", "precipitation", "weather_code", "is_day")
_cache: tuple[datetime, list[dict]] | None = None


def normalize(hourly: dict) -> list[dict]:
    def value(key, index):
        item = hourly.get(key) or []
        v = item[index] if isinstance(item, list) and index < len(item) else None
        return v if type(v) in (int, float) and isfinite(v) else None

    points = []
    for index, ts in enumerate(hourly.get("time") or []):
        if type(ts) is not int:
            continue
        temp, probability, precipitation, code, is_day = (value(k, index) for k in FIELDS)
        if all(v is None for v in (temp, probability, precipitation, code)):
            continue
        points.append({
            "t": ts * 1000,
            "temperature_c": temp,
            "precipitation_probability_pct": probability,
            "precipitation_mm": precipitation,
            "weather_code": code,
            "is_day": None if is_day is None else bool(is_day),
        })
    return sorted(points, key=lambda point: point["t"])


def fetch() -> list[dict]:
    params = urlencode({
        "latitude": config.SITE_LAT,
        "longitude": config.SITE_LON,
        "hourly": ",".join(FIELDS),
        "forecast_hours": config.FORECAST_HOURS + 1,
        "timeformat": "unixtime",
        "timezone": "GMT",
    })
    request = Request(f"{URL}?{params}", headers={"User-Agent": "wetterstation/2.0"})
    with urlopen(request, timeout=15) as response:
        data = json.load(response)
    hourly = data["hourly"]
    if not isinstance(hourly, dict):
        raise ValueError("Ungültige Stundenwerte")
    return normalize(hourly)


def snapshot(now: datetime | None = None) -> dict:
    status, updated, hours = "disabled", None, []
    if config.FORECAST_ENABLED:
        status = "unavailable"
        now = now or datetime.now(timezone.utc)
        if _cache:
            as_of, points = _cache
            updated = int(as_of.timestamp() * 1000)
            age = (now - as_of).total_seconds()
            if age < 6 * 3600:
                hours = [p for p in points if p["t"] > now.timestamp() * 1000][:config.FORECAST_HOURS]
                if hours:
                    status = "stale" if age >= config.FORECAST_REFRESH_MINUTES * 120 else "ok"
    return {"status": status, "updated_at": updated, "hours": hours}


async def run_periodic() -> None:
    global _cache
    while True:
        delay = config.FORECAST_REFRESH_MINUTES * 60
        try:
            points = await asyncio.to_thread(fetch)
            now = datetime.now(timezone.utc)
            if not any(p["t"] > now.timestamp() * 1000 for p in points):
                raise ValueError("Keine zukünftigen Prognosepunkte")
            _cache = (now, points)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Open-Meteo-Abruf fehlgeschlagen: %s", exc)
            delay = min(delay, 300)
        await asyncio.sleep(delay)
