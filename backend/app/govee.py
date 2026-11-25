"""
Govee Cloud API – Polling für Innen-Sensoren (z. B. H5100 Hygrometer).

Die offene Govee-API liefert nur den jeweils aktuellen Wert eines Geräts;
historische Werte gibt es nicht. Wir fragen die API daher in regelmäßigen
Abständen ab und legen jede Messung als Zeile in `indoor_readings` ab.

Konfiguration:
    GOVEE_API_KEY        – Pflicht. Über die Govee-App / das Developer-Portal.
    GOVEE_POLL_MINUTES   – Polling-Intervall (Standard: 5 Minuten).
    GOVEE_DEVICE_IDS     – optional, "device|sku,device|sku" – wenn leer,
                            werden automatisch alle Thermometer/Hygrometer
                            des Kontos eingesammelt.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from math import isfinite
from typing import Iterable

from . import config, db

logger = logging.getLogger("govee")
_BASE = "https://openapi.api.govee.com/router/api/v1"

# Welche Govee-Geräte gelten als Innen-Sensoren?
_SENSOR_TYPES = {
    "devices.types.thermometer",
    "devices.types.thermosensor",
    "devices.types.sensor",
}


def _request(path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{_BASE}{path}",
        data=data,
        method=method,
        headers={
            "Govee-API-Key": config.GOVEE_API_KEY,
            "Content-Type": "application/json",
            "User-Agent": "wetterstation/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def discover_devices() -> list[dict]:
    """Liefert eine Liste {device, sku, name} aller relevanten Geräte."""
    # Konfigurierte Geräte hart vorgeben (überspringt die Filterung,
    # holt aber die lesbaren Namen einmalig aus der API nach).
    if config.GOVEE_DEVICE_IDS:
        configured: list[dict] = []
        for entry in config.GOVEE_DEVICE_IDS.split(","):
            entry = entry.strip()
            if not entry or "|" not in entry:
                continue
            dev, sku = entry.split("|", 1)
            configured.append({"device": dev.strip(), "sku": sku.strip(), "name": dev.strip()})
        # Lesbaren Namen aus /user/devices ergänzen (best effort).
        try:
            payload = await asyncio.to_thread(_request, "/user/devices", "GET")
            by_id = {
                d.get("device"): d.get("deviceName")
                for d in (payload.get("data") or [])
                if d.get("device")
            }
            for item in configured:
                nice = by_id.get(item["device"])
                if nice:
                    item["name"] = nice
        except Exception as exc:
            logger.info("Govee: Namens-Abruf nicht möglich, verwende IDs (%s)", exc)
        logger.info("Govee: %d Gerät(e) aus GOVEE_DEVICE_IDS übernommen: %s",
                    len(configured), ", ".join(d["name"] for d in configured))
        return configured

    try:
        payload = await asyncio.to_thread(_request, "/user/devices", "GET")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(400).decode("utf-8", errors="replace")
        except Exception:
            pass
        logger.warning("Govee Discovery: HTTP %s %s – %s", exc.code, exc.reason, body)
        return []
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        logger.warning("Govee Discovery: Verbindungsfehler: %s", exc)
        return []

    code = payload.get("code")
    msg = payload.get("message") or payload.get("msg")
    devs = payload.get("data") or []
    if code and code != 200:
        logger.warning("Govee Discovery: API-Code %s (%s)", code, msg)
        return []

    logger.info("Govee Discovery: %d Gerät(e) insgesamt im Konto", len(devs))
    out: list[dict] = []
    skipped: list[str] = []
    for d in devs:
        dtype = d.get("type") or ""
        capabilities = d.get("capabilities") or []
        has_measurements = any(
            _measurement((c.get("instance") or "").lower(), c.get("type") or "")
            for c in capabilities
        )
        if dtype not in _SENSOR_TYPES and not has_measurements:
            skipped.append(f"{d.get('deviceName') or d.get('device')} ({dtype})")
            continue
        out.append({
            "device": d.get("device"),
            "sku": d.get("sku"),
            "name": d.get("deviceName") or d.get("device"),
        })
    if skipped:
        logger.info("Govee Discovery: %d Gerät(e) übersprungen (kein Thermometer-Typ): %s",
                    len(skipped), ", ".join(skipped[:5]))
    return out


def _temperature_unit(value) -> str | None:
    label = str(value or "").casefold().strip().replace("°", "")
    if label in {"c", "celsius", "centigrade", "degc", "℃"}:
        return "celsius"
    if label in {"f", "fahrenheit", "degf", "℉"}:
        return "fahrenheit"
    return None


def _device_unit(device: str) -> str | None:
    for entry in config.GOVEE_TEMPERATURE_UNITS.split(","):
        key, separator, unit = entry.partition("|")
        if separator and key.strip().casefold() == device.casefold():
            return _temperature_unit(unit)
    return None


def _measurement(instance: str, kind: str) -> str | None:
    if instance in ("sensortemperature", "currenttemperature", "ambienttemperature"):
        return "temperature"
    if instance in ("sensorhumidity", "currenthumidity", "relativehumidity"):
        return "humidity"
    if not kind or kind == "devices.capabilities.property":
        if not any(word in instance for word in ("target", "setting", "setpoint", "threshold", "calibration")):
            return next((metric for metric in ("temperature", "humidity") if metric in instance), None)
    return None


def _extract_measurements(payload: dict, device: str = "") -> tuple[float | None, float | None, str | None]:
    """Ermittelt Messwerte und die Eingangseinheit der Temperatur."""
    temp = hum = used_unit = None
    if payload.get("code") not in (None, 200, "200"):
        return temp, hum, used_unit
    data = payload.get("payload") or {}
    for cap in data.get("capabilities") or []:
        measurement = _measurement((cap.get("instance") or "").lower(), cap.get("type") or "")
        if not measurement:
            continue
        state = cap.get("state") or {}
        value = state.get("value", state.get("currentValue"))
        sources = [state, cap, data, (cap.get("parameters") or {})]
        if isinstance(value, dict):
            sources.insert(0, value)
            value = value.get("currentValue", value.get("value"))
        if isinstance(value, bool):
            continue
        text_unit = None
        if isinstance(value, str):
            match = re.fullmatch(r"\s*([-+]?\d+(?:[.,]\d+)?)\s*(°?\s*[CFcf]|℃|℉|%)?\s*", value)
            if not match:
                continue
            value, suffix = match.groups()
            value = value.replace(",", ".")
            text_unit = _temperature_unit((suffix or "").replace(" ", ""))
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not isfinite(number):
            continue
        if measurement == "temperature":
            declared = next((unit for source in sources if isinstance(source, dict)
                             for key in ("unit", "temperatureUnit", "temperature_unit")
                             if (unit := _temperature_unit(source.get(key)))), None)
            used_unit = (_device_unit(device) or text_unit or declared
                         or _temperature_unit(config.GOVEE_TEMPERATURE_UNIT) or "fahrenheit")
            if abs(number) > 200:
                number /= 100
            if used_unit == "fahrenheit":
                number = (number - 32) * 5 / 9
            temp = round(number, 2)
        elif measurement == "humidity":
            if number > 100:
                number /= 100
            if 0 <= number <= 100:
                hum = round(number, 1)
    return temp, hum, used_unit


async def poll_device(device: str, sku: str, name: str) -> bool:
    """Holt den aktuellen Zustand eines Geräts und schreibt eine Zeile."""
    body = {
        "requestId": str(uuid.uuid4()),
        "payload": {"sku": sku, "device": device},
    }
    try:
        payload = await asyncio.to_thread(_request, "/device/state", "POST", body)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        logger.warning("Govee Abruf (%s) fehlgeschlagen: %s", device, exc)
        return False

    temp, hum, unit = _extract_measurements(payload, device)
    if temp is None and hum is None:
        logger.info("Govee: keine Messwerte von %s (Status %s)", name, payload.get("code"))
        return False

    now = datetime.now(timezone.utc)
    async with db.pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO indoor_readings (time, device_id, device_name, temperature_c, humidity_pct, temperature_input_unit)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (device_id, time) DO NOTHING
            """,
            now, device, name, temp, hum, unit,
        )
    return True


async def poll_all(devices: Iterable[dict]) -> int:
    n = 0
    for d in devices:
        if not d.get("device") or not d.get("sku"):
            continue
        name = d.get("name") or d["device"]
        try:
            n += await poll_device(d["device"], d["sku"], name)
        except Exception:
            logger.exception("Govee-Messung für %s fehlgeschlagen", name)
        # Mini-Pause schont das Rate-Limit
        await asyncio.sleep(1.0)
    return n


async def run_periodic() -> None:
    """Endlosschleife: Geräte einmal entdecken, dann periodisch pollen."""
    interval = max(60, config.GOVEE_POLL_MINUTES * 60)
    devices: list[dict] = []
    while not devices:
        try:
            devices = await discover_devices()
        except Exception:
            logger.exception("Govee-Gerätesuche fehlgeschlagen")
        if devices:
            logger.info("Govee: %d Sensor(en) gefunden: %s",
                        len(devices), ", ".join(d.get("name", "?") for d in devices))
            break
        logger.info("Govee: keine Sensoren gefunden, neuer Versuch in 5 min")
        await asyncio.sleep(300)

    while True:
        try:
            n = await poll_all(devices)
            if n:
                logger.info("Govee: %d Messung(en) gespeichert", n)
        except Exception as exc:
            logger.warning("Govee-Poll fehlgeschlagen: %s", exc)
        await asyncio.sleep(interval)
