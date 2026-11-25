"""
Sonnenauf- und -untergang nach dem NOAA-/Meeus-Algorithmus.

Reine Berechnung, keine externe API nötig. Genauigkeit ca. ±1 Minute,
für die Visualisierung der Nachtschattierung im Diagramm völlig
ausreichend.

Quellen: NOAA Solar Calculator, Jean Meeus "Astronomical Algorithms".
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache


def _julian_day(d: date) -> float:
    y, m = d.year, d.month
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d.day + b - 1524.5


@lru_cache(maxsize=1024)
def _sun_rise_set(d: date, lat: float, lon: float, kind: str = "rise") -> datetime | None:
    """Liefert Sonnenauf- bzw. -untergang in UTC als datetime, oder None bei Polarnacht/-tag."""
    # n = ganzzahlige Anzahl Tage seit J2000 (J2000 = 2000-01-01 12:00 UT, JD 2451545.0).
    # _julian_day liefert JD für Mitternacht UT (x.5), darum +0.5 für Mittag.
    n = math.floor(_julian_day(d) + 0.5 - 2451545.0 + 0.0008)
    j_star = n - lon / 360.0
    m = (357.5291 + 0.98560028 * j_star) % 360
    m_rad = math.radians(m)
    c = (1.9148 * math.sin(m_rad)
         + 0.0200 * math.sin(2 * m_rad)
         + 0.0003 * math.sin(3 * m_rad))
    lam = (m + c + 180 + 102.9372) % 360
    lam_rad = math.radians(lam)
    j_transit = 2451545.0 + j_star + 0.0053 * math.sin(m_rad) - 0.0069 * math.sin(2 * lam_rad)
    delta = math.asin(math.sin(lam_rad) * math.sin(math.radians(23.4397)))
    lat_rad = math.radians(lat)
    cos_h0 = ((math.sin(math.radians(-0.83)) - math.sin(lat_rad) * math.sin(delta))
              / (math.cos(lat_rad) * math.cos(delta)))
    if cos_h0 < -1 or cos_h0 > 1:
        return None  # Polartag/-nacht
    h0 = math.degrees(math.acos(cos_h0))
    if kind == "rise":
        jd = j_transit - h0 / 360.0
    else:
        jd = j_transit + h0 / 360.0
    # JD -> UTC datetime
    unix = (jd - 2440587.5) * 86400.0
    return datetime.fromtimestamp(unix, tz=timezone.utc)


def night_intervals_utc(
    start: datetime, end: datetime, lat: float, lon: float
) -> list[tuple[datetime, datetime]]:
    """
    Liefert eine Liste von (start, ende)-Intervallen, die jeweils Nacht
    sind, innerhalb des Bereichs [start, end] (UTC).

    Eine "Nacht" beginnt mit Sonnenuntergang und endet mit dem nächsten
    Sonnenaufgang. Die Funktion deckt mehrere Tage korrekt ab.
    """
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    intervals: list[tuple[datetime, datetime]] = []
    d = (start.date() - timedelta(days=1))
    while d <= end.date() + timedelta(days=1):
        sset = _sun_rise_set(d, lat, lon, "set")
        rise_next = _sun_rise_set(d + timedelta(days=1), lat, lon, "rise")
        if sset and rise_next:
            a = max(sset, start)
            b = min(rise_next, end)
            if a < b:
                intervals.append((a, b))
        d += timedelta(days=1)
    return intervals
