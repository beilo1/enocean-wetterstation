"""Jahresstatistik und Raumklima-Auswertung."""

import math
from datetime import datetime, timezone

from . import db


async def calendar_stats(sensor_id: str, year: int) -> dict:
    """Markante Tage und Zählungen aus readings_daily für ein Jahr."""
    sql = """
        SELECT bucket AS d, temp_min, temp_max, rain_any, wind_max
        FROM readings_daily
        WHERE sensor_id = $1
          AND bucket >= make_date($2, 1, 1)
          AND bucket <  make_date($2 + 1, 1, 1)
        ORDER BY bucket
    """
    async with db.pool().acquire() as conn:
        rows = await conn.fetch(sql, sensor_id, year)

    if not rows:
        return {"ok": False, "year": year, "reason": "keine Tagesdaten"}

    def fdate(d):
        return d.isoformat() if d else None

    summer_days = [r for r in rows if r["temp_max"] is not None and r["temp_max"] >= 25]
    hot_days = [r for r in rows if r["temp_max"] is not None and r["temp_max"] >= 30]
    ice_days = [r for r in rows if r["temp_max"] is not None and r["temp_max"] < 0]
    frost_days = [r for r in rows if r["temp_min"] is not None and r["temp_min"] < 0]
    rain_days = [r for r in rows if r["rain_any"]]
    tropical_nights = [r for r in rows if r["temp_min"] is not None and r["temp_min"] >= 20]

    warmest = max((r for r in rows if r["temp_max"] is not None), key=lambda r: r["temp_max"], default=None)
    coldest = min((r for r in rows if r["temp_min"] is not None), key=lambda r: r["temp_min"], default=None)
    windiest = max((r for r in rows if r["wind_max"] is not None), key=lambda r: r["wind_max"], default=None)

    return {
        "ok": True,
        "year": year,
        "days_with_data": len(rows),
        "counts": {
            "sommertage": len(summer_days),     # >= 25 °C
            "hitzetage": len(hot_days),         # >= 30 °C
            "eistage": len(ice_days),           # Max < 0 °C
            "frosttage": len(frost_days),       # Min < 0 °C
            "regentage": len(rain_days),
            "tropennaechte": len(tropical_nights),  # Min >= 20 °C
        },
        "first": {
            "erster_sommertag": fdate(summer_days[0]["d"]) if summer_days else None,
            "erster_hitzetag": fdate(hot_days[0]["d"]) if hot_days else None,
            "letzter_frosttag": fdate(frost_days[-1]["d"]) if frost_days else None,
        },
        "extremes": {
            "waermster_tag": {
                "datum": fdate(warmest["d"]) if warmest else None,
                "wert": round(warmest["temp_max"], 1) if warmest else None,
            },
            "kaeltester_tag": {
                "datum": fdate(coldest["d"]) if coldest else None,
                "wert": round(coldest["temp_min"], 1) if coldest else None,
            },
            "windigster_tag": {
                "datum": fdate(windiest["d"]) if windiest else None,
                "wert": round(windiest["wind_max"], 1) if windiest else None,
            },
        },
    }


def _dew_point(t_c: float, rh: float) -> float:
    """Taupunkt nach Magnus-Formel."""
    a, b = 17.62, 243.12
    gamma = (a * t_c) / (b + t_c) + math.log(max(1e-3, rh / 100.0))
    return (b * gamma) / (a - gamma)


def _heat_index(t_c: float, rh: float) -> float:
    """
    Hitzeindex (gefühlte Temperatur bei Wärme), Rothfusz-Regression.
    Sinnvoll ab ~26 °C; darunter geben wir die Lufttemperatur zurück.
    """
    if t_c < 26:
        return t_c
    t_f = t_c * 9 / 5 + 32
    hi = (-42.379 + 2.04901523 * t_f + 10.14333127 * rh
          - 0.22475541 * t_f * rh - 6.83783e-3 * t_f * t_f
          - 5.481717e-2 * rh * rh + 1.22874e-3 * t_f * t_f * rh
          + 8.5282e-4 * t_f * rh * rh - 1.99e-6 * t_f * t_f * rh * rh)
    return (hi - 32) * 5 / 9


async def indoor_comfort(indoor_device: str | None) -> dict:
    """
    Bewertet das aktuelle Innenraumklima auf Basis der letzten Messung:
    Taupunkt, gefühlte Temperatur (Hitzeindex) und eine Komfort-Einordnung.
    """
    device_filter = "AND device_id = $1" if indoor_device else ""
    sql = f"""
        SELECT device_name, temperature_c, humidity_pct, time
        FROM indoor_readings
        WHERE temperature_c IS NOT NULL AND humidity_pct IS NOT NULL
        {device_filter}
        ORDER BY time DESC
        LIMIT 1
    """
    async with db.pool().acquire() as conn:
        r = await conn.fetchrow(sql, indoor_device) if indoor_device else await conn.fetchrow(sql)

    if not r or r["temperature_c"] is None or r["humidity_pct"] is None:
        return {"ok": False, "reason": "keine vollständige Innenmessung"}

    t = float(r["temperature_c"])
    rh = float(r["humidity_pct"])
    dew = _dew_point(t, rh)
    feels = _heat_index(t, rh)

    # Komfort-Einordnung (grobe, gut nachvollziehbare Heuristik)
    if t < 16:
        comfort, hint = "kühl", "Es ist eher kühl – Heizen könnte angenehm sein."
    elif t > 26 and feels >= 28:
        comfort, hint = "schwül-warm", "Warm und feucht – Lüften am Morgen/Abend hilft."
    elif t > 26:
        comfort, hint = "warm", "Recht warm, aber trocken – gut erträglich."
    elif rh < 30:
        comfort, hint = "zu trocken", "Sehr trockene Luft – kann Schleimhäute reizen."
    elif rh > 65:
        comfort, hint = "zu feucht", "Hohe Luftfeuchte – Schimmel-Risiko, mehr lüften."
    else:
        comfort, hint = "behaglich", "Angenehmes Raumklima."

    age_s = int((datetime.now(timezone.utc) - r["time"]).total_seconds())

    return {
        "ok": True,
        "device": r["device_name"],
        "temperature_c": round(t, 1),
        "humidity_pct": round(rh, 1),
        "dew_point_c": round(dew, 1),
        "feels_like_c": round(feels, 1),
        "comfort": comfort,
        "hint": hint,
        "age_seconds": age_s,
    }
