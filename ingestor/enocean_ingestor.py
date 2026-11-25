#!/usr/bin/env python3
"""
EnOcean-Ingestor für die Eltako-Multisensor-Wetterstation (WMS).

Liest ESP3-Frames von einem seriellen EnOcean-Empfänger, dekodiert die
4BS-Telegramme der Wetterstation und schreibt Messungen nach PostgreSQL.

Die Dekodier-Mathematik ist 1:1 aus der bisherigen, funktionierenden
App übernommen – an der Kalibrierung wird bewusst nichts geändert.

Konfiguration über Umgebungsvariablen:
    SERIAL_PORT   (Default /dev/serial0)
    BAUDRATE      (Default 57600)
    SENSOR_ID     (EnOcean-Sender-ID als acht Hex-Zeichen)
    DATABASE_URL  (PostgreSQL-DSN)
"""
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone

import psycopg
import serial

from esp3 import bytes_to_hex, read_esp3_frame

SERIAL_PORT = os.environ.get("SERIAL_PORT", "/dev/serial0")
BAUDRATE = int(os.environ.get("BAUDRATE", "57600"))
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Welche Sender-IDs gelten als "unsere" Wetterstation.
WEATHER_IDS = {os.environ.get("SENSOR_ID", "").strip().upper()}


# ----------------------------------------------------------------------
# Dekodierung der beiden Telegramm-Hälften  (unverändert übernommen)
# ----------------------------------------------------------------------
def decode_part1(db3, db2, db1, db0):
    rr, ss, tt, uu = db3, db2, db1, db0
    return {
        "twilight_lux": rr * 1000.0 / 255.0,
        "temperature_c": (ss * 120.0 / 255.0) - 40.0,
        "wind_ms": tt * 70.0 / 255.0,
        "rain": 1 if uu == 0x1A else 0,
    }


def decode_part2(db3, db2, db1, db0):
    vv, ww, xx = db3, db2, db1
    return {
        "west_klux": vv * 150.0 / 255.0,
        "south_klux": ww * 150.0 / 255.0,
        "east_klux": xx * 150.0 / 255.0,
    }


# ----------------------------------------------------------------------
# Persistenz
# ----------------------------------------------------------------------
_INSERT = """
    INSERT INTO readings (
        time, sensor_id, twilight_lux, temperature_c, wind_ms, rain,
        west_klux, south_klux, east_klux)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (sensor_id, time) DO NOTHING
"""


def store(conn, sender_hex, part1, part2):
    now = datetime.now(timezone.utc)
    conn.execute(
        _INSERT,
        (
            now, sender_hex,
            part1["twilight_lux"], part1["temperature_c"],
            part1["wind_ms"], bool(part1["rain"]),
            part2["west_klux"], part2["south_klux"], part2["east_klux"],
        ),
    )
    return now


# ----------------------------------------------------------------------
# Hauptschleife mit Wiederverbindung
# ----------------------------------------------------------------------
def run_once():
    state = defaultdict(dict)
    with (
        psycopg.connect(DATABASE_URL, autocommit=True) as conn,
        serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1) as ser,
    ):
        print("Starte EnOcean-Ingestor …")
        print(f"Port={SERIAL_PORT} @ {BAUDRATE} Baud")
        print(f"Wetterstation-IDs: {', '.join(sorted(WEATHER_IDS))}")

        while True:
            frame = read_esp3_frame(ser)
            if frame is None:
                continue

            packet_type, data, _ = frame
            if packet_type != 0x01:
                continue
            if len(data) < 10:
                continue
            if data[0] != 0xA5:  # nur 4BS
                continue

            db3, db2, db1, db0 = data[1], data[2], data[3], data[4]
            sender_hex = bytes_to_hex(data[5:9])
            if sender_hex not in WEATHER_IDS:
                continue

            if db0 in (0x18, 0x1A):
                state[sender_hex]["part1"] = decode_part1(db3, db2, db1, db0)
            elif db0 == 0x28:
                state[sender_hex]["part2"] = decode_part2(db3, db2, db1, db0)
            else:
                continue

            part1 = state[sender_hex].get("part1")
            part2 = state[sender_hex].get("part2")
            if part1 and part2:
                ts = store(conn, sender_hex, part1, part2)
                print(
                    f"{ts.isoformat(timespec='seconds')}  ID={sender_hex}  "
                    f"Dämmerung={part1['twilight_lux']:.0f} lx, "
                    f"Temp={part1['temperature_c']:.1f} °C, "
                    f"Wind={part1['wind_ms']:.1f} m/s, "
                    f"Regen={'JA' if part1['rain'] else 'nein'}, "
                    f"W={part2['west_klux']:.1f} / S={part2['south_klux']:.1f} / "
                    f"O={part2['east_klux']:.1f} kLux"
                )


def main():
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL in der Konfiguration fehlt.")
    if not all(re.fullmatch(r"[0-9A-F]{8}", sender_id) for sender_id in WEATHER_IDS):
        raise SystemExit("SENSOR_ID muss aus acht Hex-Zeichen bestehen.")

    while True:
        try:
            run_once()
        except (serial.SerialException, psycopg.OperationalError) as exc:
            print(f"[ingestor] Verbindungsfehler: {exc} – neuer Versuch in 5 s")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\nBeende Ingestor.")
            break


if __name__ == "__main__":
    main()
