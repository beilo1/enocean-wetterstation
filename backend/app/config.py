"""Konfiguration. Liest alles aus Umgebungsvariablen (siehe .env.example)."""
import os
from pathlib import Path

# Verzeichnis mit den ausgelieferten Frontend-Dateien.
FRONTEND_DIR = Path(
    os.environ.get(
        "FRONTEND_DIR",
        str(Path(__file__).resolve().parents[2] / "frontend"),
    )
)

# PostgreSQL-Verbindung als DSN.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Standard-Sensor, falls in der API keiner angegeben wird.
# Entspricht der ID deiner Wetterstation (siehe Ingestor).
DEFAULT_SENSOR_ID = (
    os.environ.get("DEFAULT_SENSOR_ID", "").strip() or os.environ.get("SENSOR_ID", "").strip()
).upper()

# Wie oft (Sekunden) der Rollup-Refresh im Hintergrund läuft.
ROLLUP_REFRESH_SECONDS = int(os.environ.get("ROLLUP_REFRESH_SECONDS", "60"))

# Pool-Größe – auf einem Pi 3B+ bewusst klein halten.
DB_POOL_MIN = int(os.environ.get("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "4"))

# ---- Standort (für Sonnenzeiten und DWD-Vergleich) ----
_latitude = os.environ.get("SITE_LAT", "").strip()
_longitude = os.environ.get("SITE_LON", "").strip()
if bool(_latitude) != bool(_longitude):
    raise ValueError("SITE_LAT und SITE_LON gemeinsam setzen oder beide leer lassen.")
SITE_LAT = float(_latitude) if _latitude else None
SITE_LON = float(_longitude) if _longitude else None
HAS_SITE_COORDINATES = SITE_LAT is not None and SITE_LON is not None
if HAS_SITE_COORDINATES and not (-90 <= SITE_LAT <= 90 and -180 <= SITE_LON <= 180):
    raise ValueError("SITE_LAT muss zwischen -90 und 90 liegen, SITE_LON zwischen -180 und 180.")
SITE_NAME = os.environ.get("SITE_NAME", "").strip() or "Wetterstation"

# ---- DWD-Vergleich (über Bright Sky, freie DWD-API) ----
DWD_REFRESH_MINUTES = int(os.environ.get("DWD_REFRESH_MINUTES", "60"))
DWD_BACKFILL_DAYS = int(os.environ.get("DWD_BACKFILL_DAYS", "30"))
# Optional: feste DWD-Station erzwingen (statt geografische Auto-Auswahl).
# Wenn gesetzt, ignoriert das Backend SITE_LAT/SITE_LON für DWD-Abrufe und
# nimmt ausschließlich diese Station. Wert: die "dwd_station_id" aus
# https://api.brightsky.dev/sources?lat=...&lon=...
DWD_STATION_ID = os.environ.get("DWD_STATION_ID", "").strip()
DWD_ENABLED = (HAS_SITE_COORDINATES or bool(DWD_STATION_ID)) and (
    os.environ.get("DWD_ENABLED", "1").strip().lower() not in ("0", "false", "no")
)

# ---- Govee Innen-Sensoren ----
# Aktiv, sobald GOVEE_API_KEY gesetzt ist. Optional: GOVEE_DEVICE_IDS als
# kommagetrennte Liste von "device|sku"-Paaren – sonst werden beim Start
# alle Thermometer-Geräte des Kontos automatisch eingesammelt.
GOVEE_API_KEY = os.environ.get("GOVEE_API_KEY", "").strip()
GOVEE_ENABLED = bool(GOVEE_API_KEY)
GOVEE_POLL_MINUTES = int(os.environ.get("GOVEE_POLL_MINUTES", "5"))
GOVEE_DEVICE_IDS = os.environ.get("GOVEE_DEVICE_IDS", "").strip()
GOVEE_TEMPERATURE_UNIT = os.environ.get("GOVEE_TEMPERATURE_UNIT", "fahrenheit").strip()
GOVEE_TEMPERATURE_UNITS = os.environ.get("GOVEE_TEMPERATURE_UNITS", "").strip()

# --- Kurzfristprognose & Regenstatus ---
FORECAST_ENABLED = HAS_SITE_COORDINATES and (
    os.environ.get("FORECAST_ENABLED", "1").strip().lower() not in ("0", "false", "no")
)
FORECAST_HOURS = max(3, min(24, int(os.environ.get("FORECAST_HOURS", "12"))))
FORECAST_REFRESH_MINUTES = max(10, min(180, int(os.environ.get("FORECAST_REFRESH_MINUTES", "30"))))
RAIN_GAP_SECONDS = max(30, int(os.environ.get("RAIN_GAP_SECONDS", "300")))
