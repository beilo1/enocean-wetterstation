"""HTTP-Endpunkte und Lebenszyklus der Wetterstation."""

import asyncio
import csv
import io
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import analytics, config, db, dwd, forecast, govee, periods, queries, rain, rollups, suntimes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = (_ROOT / "db" / "schema.sql").read_text(encoding="utf-8")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    tasks = []
    try:
        await db.init_pool()
        await db.apply_schema(_SCHEMA)
        await rollups.ensure_backfilled()
        tasks.append(asyncio.create_task(rollups.run_periodic()))
        if config.DWD_ENABLED:
            await dwd.ensure_initial_backfill()
            tasks.append(asyncio.create_task(dwd.run_periodic()))
        if config.GOVEE_ENABLED:
            tasks.append(asyncio.create_task(govee.run_periodic()))
        if config.FORECAST_ENABLED:
            tasks.append(asyncio.create_task(forecast.run_periodic()))
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await db.close_pool()


app = FastAPI(
    title="Wetterstation",
    description="Außenmessungen der Dachstation, DWD-Vergleich, Govee-Raumklima und Wetterprognose.",
    version="2.1.1",
    lifespan=lifespan,
    # Eingebautes Swagger deaktivieren – wir liefern eine eigene Seite,
    # die ins App-Layout integriert ist (siehe /api-docs unten).
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json",
)

_NO_STORE = {"Cache-Control": "no-store"}


def _period(name: str, start: str | None, end: str | None) -> periods.Period:
    try:
        return periods.resolve(name, start, end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/healthz", summary="Liveness/Readiness", tags=["System"])
async def healthz():
    try:
        async with db.pool().acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok"}
    except Exception as exc:
        logger.warning("Datenbank für Health-Check nicht erreichbar: %s", exc)
        return JSONResponse({"status": "error", "detail": "Datenbank nicht erreichbar"}, status_code=503)


@app.get("/api/series",
         summary="Aggregierte Zeitreihe der Außenmessung",
         description="Liefert je Auflösung eine begrenzte Punktzahl: 24h aus Rohdaten (5-Min-Buckets), 7d/30d aus Stunden-Aggregaten, 365d aus Tages-Aggregaten.",
         tags=["Daten"])
async def api_series(
    range: str = Query("24h"),
    start: str | None = None,
    end: str | None = None,
    sensor: str | None = None,
):
    data = await queries.fetch_series(sensor or config.DEFAULT_SENSOR_ID, _period(range, start, end))
    return JSONResponse(data, headers=_NO_STORE)


@app.get("/api/latest", summary="Letzte Rohmessung der Außenstation", tags=["Daten"])
async def api_latest(sensor: str | None = None):
    sensor_id = sensor or config.DEFAULT_SENSOR_ID
    latest = await queries.fetch_latest(sensor_id)
    return JSONResponse({"latest": latest}, headers=_NO_STORE)


@app.get("/api/sun", summary="Nacht-Intervalle für Diagramm-Schattierung", tags=["Daten"])
async def api_sun(range: str = Query("24h"), start: str | None = None, end: str | None = None):
    """Liefert Nacht-Intervalle (Sonnenuntergang -> nächster Sonnenaufgang) für den Bereich."""
    s, e = _period(range, start, end).bounds(datetime.now(timezone.utc))
    intervals = []
    if config.HAS_SITE_COORDINATES:
        intervals = suntimes.night_intervals_utc(s, e, config.SITE_LAT, config.SITE_LON)
    return JSONResponse({
        "site": {"lat": config.SITE_LAT, "lon": config.SITE_LON, "name": config.SITE_NAME},
        "nights": [
            [int(a.timestamp() * 1000), int(b.timestamp() * 1000)] for a, b in intervals
        ],
    }, headers=_NO_STORE)


@app.get("/api/dwd", summary="DWD-Vergleichsdaten (Bright Sky)", tags=["Daten"])
async def api_dwd(range: str = Query("24h"), start: str | None = None, end: str | None = None):
    """DWD-Vergleichsdaten, passend zur Auflösung der Hauptansicht aggregiert."""
    period = _period(range, start, end)
    where, params = period.where("time")
    daily = period.seconds == periods.DAY
    bucket_sql = periods.bucket_expression(periods.DAY) if daily else "time"

    sql = f"""
        SELECT (extract(epoch FROM {bucket_sql})*1000)::bigint AS t,
               avg(temperature_c) AS temp,
               avg(wind_ms) AS wind,
               (array_agg(station ORDER BY time DESC))[1] AS station
        FROM dwd_readings WHERE {where}
        GROUP BY 1
        ORDER BY 1
    """
    async with db.pool().acquire() as conn:
        rows = await conn.fetch(sql, *params)
    t, temp, wind = [], [], []
    station = None
    for r in rows:
        t.append(r["t"])
        temp.append(queries.rounded(r["temp"]))
        wind.append(queries.rounded(r["wind"]))
        station = r["station"] or station
    return JSONResponse({
        "station": station,
        "bucket_seconds": periods.DAY if daily else periods.HOUR,
        "t": t,
        "temperature_c": temp,
        "wind_ms": wind,
    }, headers=_NO_STORE)


@app.get("/api/calendar/years", summary="Jahre mit Tageswerten", tags=["Daten"])
async def api_calendar_years(sensor: str | None = None):
    async with db.pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT EXTRACT(YEAR FROM bucket)::int AS year "
            "FROM readings_daily WHERE sensor_id = $1 ORDER BY year DESC",
            sensor or config.DEFAULT_SENSOR_ID,
        )
    return {"years": [r["year"] for r in rows]}


@app.get("/api/calendar", summary="Tageswerte für die Jahres-Heatmap", tags=["Daten"])
async def api_calendar(
    year: int | None = Query(None, ge=1900, le=9998),
    metric: str = Query("temp_max"),
    sensor: str | None = None,
):
    """Tageswerte aus readings_daily für die Heatmap (eine Zelle pro Tag)."""
    allowed = {
        "temp_max": "temp_max", "temp_min": "temp_min", "temp_avg": "temp_avg",
        "wind_max": "wind_max", "wind_avg": "wind_avg",
        "south_max": "south_max", "south_avg": "south_avg",
        "rain_any": "rain_any",
    }
    col = allowed.get(metric, "temp_max")
    sensor_id = sensor or config.DEFAULT_SENSOR_ID
    y = year or date.today().year

    sql = f"""
        SELECT bucket::text AS day, {col} AS val
        FROM readings_daily
        WHERE sensor_id = $1
          AND bucket >= make_date($2, 1, 1)
          AND bucket <  make_date($2 + 1, 1, 1)
        ORDER BY bucket
    """
    async with db.pool().acquire() as conn:
        rows = await conn.fetch(sql, sensor_id, y)

    if col == "rain_any":
        values = {r["day"]: (int(r["val"]) if r["val"] is not None else None) for r in rows}
    else:
        values = {r["day"]: queries.rounded(r["val"]) for r in rows}

    # Wertespanne ermitteln (für die Farbskala im Frontend)
    nums = [v for v in values.values() if isinstance(v, (int, float))]
    return JSONResponse({
        "year": y,
        "metric": metric,
        "values": values,
        "min": min(nums) if nums else None,
        "max": max(nums) if nums else None,
        "count": len(values),
    }, headers=_NO_STORE)


@app.get("/api/health", summary="Sensor-Gesundheit (Lag, Median-Intervall)", tags=["System"])
async def api_health(sensor: str | None = None, details: bool = True):
    """Empfang und Messintervall. details=false überspringt die Zählung des Bestands."""
    sensor_id = sensor or config.DEFAULT_SENSOR_ID
    sql = """
        WITH last_rows AS (
            SELECT time FROM readings WHERE sensor_id=$1
            ORDER BY time DESC LIMIT 200
        ),
        diffs AS (
            SELECT EXTRACT(EPOCH FROM (time - lead(time) OVER (ORDER BY time DESC))) AS d
            FROM last_rows
        )
        SELECT
            (SELECT max(time) FROM last_rows) AS last_t,
            CASE WHEN $2 THEN (SELECT count(*) FROM readings WHERE sensor_id=$1 AND time >= now() - interval '1 hour') END AS last_1h,
            CASE WHEN $2 THEN (SELECT count(*) FROM readings WHERE sensor_id=$1 AND time >= now() - interval '24 hours') END AS last_24h,
            CASE WHEN $2 THEN (SELECT count(*) FROM readings WHERE sensor_id=$1) END AS total,
            (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY d) FROM diffs WHERE d IS NOT NULL AND d > 0) AS median_interval_s
    """
    async with db.pool().acquire() as conn:
        r = await conn.fetchrow(sql, sensor_id, details)

    last_t = r["last_t"]
    age_s = None
    if last_t:
        age_s = int((datetime.now(timezone.utc) - last_t).total_seconds())

    median = r["median_interval_s"]
    # Statusbewertung: wenn keine Messung in den letzten 5 Median-Intervallen kam, ist's "stale".
    status = "ok"
    if median and age_s is not None:
        if age_s > 5 * median and age_s > 300:
            status = "stale"
        if age_s > 30 * median and age_s > 1800:
            status = "down"
    elif age_s is None:
        status = "down"

    return JSONResponse({
        "sensor_id": sensor_id,
        "last_t": int(last_t.timestamp() * 1000) if last_t else None,
        "age_seconds": age_s,
        "median_interval_seconds": int(median) if median else None,
        "count_last_hour": r["last_1h"],
        "count_last_24h": r["last_24h"],
        "count_total": r["total"],
        "status": status,
    }, headers=_NO_STORE)


def _in_house(device_id: str, name: str | None) -> bool:
    return (
        "garage" not in (name or "").casefold()
        and device_id.casefold() not in config.GOVEE_HOUSE_EXCLUDE_DEVICE_IDS
    )


@app.get("/api/indoor/devices", summary="Liste der erkannten Govee-Sensoren", tags=["Daten"])
async def api_indoor_devices():
    """
    Listet alle Govee-Geräte auf, von denen schon Messungen vorliegen –
    inklusive ihrer IDs (für GOVEE_DEVICE_IDS in der .env).
    """
    sql = """
        WITH counts AS (
            SELECT device_id, max(time) AS last_seen, count(*) AS n,
                   count(temperature_c) AS temperature_samples,
                   count(humidity_pct) AS humidity_samples,
                   max(time) FILTER (WHERE temperature_c IS NOT NULL) AS last_temperature
            FROM indoor_readings GROUP BY device_id
        )
        SELECT counts.*, latest.device_name, last_temp.temperature_input_unit
        FROM counts
        JOIN indoor_readings latest ON latest.device_id = counts.device_id AND latest.time = counts.last_seen
        LEFT JOIN indoor_readings last_temp
          ON last_temp.device_id = counts.device_id AND last_temp.time = counts.last_temperature
        ORDER BY counts.last_seen DESC
    """
    async with db.pool().acquire() as conn:
        rows = await conn.fetch(sql)
    return JSONResponse({
        "devices": [
            {
                "device_id": r["device_id"],
                "name": r["device_name"],
                "in_house": _in_house(r["device_id"], r["device_name"]),
                "last_seen": int(r["last_seen"].timestamp() * 1000) if r["last_seen"] else None,
                "samples": r["n"],
                "temperature_samples": r["temperature_samples"],
                "humidity_samples": r["humidity_samples"],
                "last_temperature_at": int(r["last_temperature"].timestamp() * 1000) if r["last_temperature"] else None,
                "temperature_input_unit": r["temperature_input_unit"],
            }
            for r in rows
        ],
    }, headers=_NO_STORE)


@app.get("/api/indoor", summary="Innen-Sensordaten (Govee)", tags=["Daten"])
async def api_indoor(
    range: str = Query("24h"),
    start: str | None = None,
    end: str | None = None,
    resolution: Literal["auto", "5m", "1h", "1d"] = "auto",
):
    """Intervallmittel für Temperatur, relative Luftfeuchte und Taupunkt je Gerät.

    Der Taupunkt wird aus simultanen Temperatur- und Feuchtewerten berechnet
    und anschließend gemittelt. Ohne vollständiges Wertepaar bleibt er leer.
    Explizit sind 5 Minuten bis 7 Tage und 1 Stunde bis 45 Tage verfügbar.
    """
    period = _period(range, start, end)
    where, params = period.where("time")
    if (resolution == "5m" and period.days > 7) or (resolution == "1h" and period.days > 45):
        raise HTTPException(status_code=422, detail="Für diesen Zeitraum eine gröbere Auflösung wählen.")
    seconds = {"5m": periods.FIVE_MINUTES, "1h": periods.HOUR, "1d": periods.DAY}.get(resolution, period.seconds)
    bucket_sql = periods.bucket_expression(seconds)
    a, b = analytics.MAGNUS_A, analytics.MAGNUS_B

    sql = f"""
        WITH samples AS (
            SELECT time, device_id, device_name, temperature_c, humidity_pct,
                   CASE
                       WHEN humidity_pct > 0 AND humidity_pct <= 100
                        AND temperature_c > -{b} AND temperature_c < 'Infinity'::double precision
                       THEN {a} * temperature_c / ({b} + temperature_c) + ln(humidity_pct / 100.0)
                   END AS gamma
            FROM indoor_readings WHERE {where}
        )
        SELECT (extract(epoch FROM {bucket_sql})*1000)::bigint AS t,
               device_id,
               max(device_name) AS device_name,
               avg(temperature_c) AS temp,
               avg(humidity_pct) AS hum,
               avg({b} * gamma / ({a} - gamma)) AS dew
        FROM samples
        GROUP BY 1, device_id
        ORDER BY device_id, 1
    """
    async with db.pool().acquire() as conn:
        rows = await conn.fetch(sql, *params)

    # Pro Gerät eine Serie aufbauen
    series: dict[str, dict] = {}
    for r in rows:
        dev = r["device_id"]
        ser = series.setdefault(dev, {
            "device_id": dev,
            "name": r["device_name"] or dev,
            "t": [], "temperature_c": [], "humidity_pct": [], "dew_point_c": [],
        })
        if r["device_name"]:
            ser["name"] = r["device_name"]
        ser["t"].append(r["t"])
        ser["temperature_c"].append(queries.rounded(r["temp"]))
        ser["humidity_pct"].append(queries.rounded(r["hum"], 1))
        ser["dew_point_c"].append(queries.rounded(r["dew"]))

    for ser in series.values():
        ser["in_house"] = _in_house(ser["device_id"], ser["name"])

    return JSONResponse({"devices": list(series.values()), "bucket_seconds": seconds},
                        headers=_NO_STORE)


@app.get("/api/forecast", summary="Stündliche Wetterprognose", tags=["Daten"])
async def api_forecast():
    return JSONResponse(forecast.snapshot(), headers=_NO_STORE)


@app.get("/api/rain", summary="Aktueller Regenstatus und letztes Ereignis", tags=["Daten"])
async def api_rain(sensor: str | None = None):
    data = await rain.latest_event(sensor or config.DEFAULT_SENSOR_ID)
    return JSONResponse(data, headers=_NO_STORE)

@app.get("/api/analysis/calendar-stats",
         summary="Jahresstatistik für die Heatmap (Sommertage, Frost, …)",
         tags=["Analyse"])
async def api_calendar_stats(year: int | None = Query(None, ge=1900, le=9998), sensor: str | None = None):
    sensor_id = sensor or config.DEFAULT_SENSOR_ID
    y = year or date.today().year
    data = await analytics.calendar_stats(sensor_id, y)
    return JSONResponse(data, headers=_NO_STORE)


@app.get("/api/analysis/comfort",
         summary="Innenraum-Komfort: Taupunkt, gefühlte Temperatur",
         tags=["Analyse"])
async def api_comfort(device: str | None = None):
    data = await analytics.indoor_comfort(device)
    return JSONResponse(data, headers=_NO_STORE)


@app.get("/api/export.csv", summary="Rohdaten als CSV", tags=["Daten"])
async def api_export(
    range: str = Query("24h"),
    start: str | None = None,
    end: str | None = None,
    sensor: str | None = None,
):
    period = _period(range, start, end)
    sensor_id = sensor or config.DEFAULT_SENSOR_ID

    async def stream():
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(["time", "temperature_c", "wind_ms", "twilight_lux",
                         "west_klux", "south_klux", "east_klux", "rain"])
        rows = queries.stream_raw_for_export(sensor_id, period)
        try:
            async for row in rows:
                writer.writerow([
                    row["time"].strftime("%Y-%m-%d %H:%M:%S"),
                    row["temperature_c"], row["wind_ms"], row["twilight_lux"],
                    row["west_klux"], row["south_klux"], row["east_klux"], int(bool(row["rain"])),
                ])
                if buffer.tell() >= 32 * 1024:
                    yield buffer.getvalue()
                    buffer.seek(0)
                    buffer.truncate()
            if buffer.tell():
                yield buffer.getvalue()
        finally:
            await rows.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="wetter_{period.name}.csv"',
            **_NO_STORE,
        },
    )


# --- Frontend statisch ausliefern ---
_frontend = config.FRONTEND_DIR


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(_frontend / "index.html")


@app.get("/raumklima", include_in_schema=False)
async def indoor_page():
    return FileResponse(_frontend / "indoor.html")


@app.get("/heatmap", include_in_schema=False)
async def heatmap_page():
    return FileResponse(_frontend / "heatmap.html")


@app.get("/docs-app", include_in_schema=False)
async def docs_page():
    return FileResponse(_frontend / "docs.html")


@app.get("/api-docs", include_in_schema=False)
async def api_docs_page():
    return FileResponse(_frontend / "api.html")


@app.get("/api-redoc", include_in_schema=False)
async def legacy_api_page():
    return RedirectResponse("/api-docs")


@app.get("/maintenance", include_in_schema=False)
async def maintenance_page():
    return FileResponse(_frontend / "maintenance.html")


@app.get("/install-guide.md", include_in_schema=False)
async def install_guide():
    return FileResponse(_ROOT / "DEPLOY.md",
                        media_type="text/markdown; charset=utf-8", filename="DEPLOY.md")


@app.get("/license", include_in_schema=False)
async def project_license():
    return FileResponse(_ROOT / "LICENSE", media_type="text/plain")


app.mount("/", StaticFiles(directory=str(_frontend)), name="frontend")
