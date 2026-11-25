#!/usr/bin/env python3
"""Preview and, on request, correct a confirmed subset of legacy Fahrenheit rows."""
import argparse
from datetime import datetime
from math import isfinite

from dotenv import dotenv_values
import psycopg


def zoned_time(value: str) -> datetime:
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Bitte einen ISO-8601-Zeitpunkt angeben") from exc
    if ts.tzinfo is None:
        raise argparse.ArgumentTypeError("Bitte einen UTC-Offset angeben, z. B. +01:00 oder Z")
    return ts


FILTER = """
    device_id = %s AND time >= %s AND time < %s
    AND temperature_input_unit IS NULL AND temperature_c BETWEEN %s AND %s
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default="/opt/wetter-station/.env")
    parser.add_argument("--device", required=True, help="Exakte Geräte-ID aus /api/indoor/devices")
    parser.add_argument("--start", required=True, type=zoned_time, help="Erster Zeitpunkt (inklusive)")
    parser.add_argument("--end", required=True, type=zoned_time, help="Letzter Zeitpunkt (exklusive)")
    parser.add_argument("--min-old", required=True, type=float)
    parser.add_argument("--max-old", required=True, type=float)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.end <= args.start:
        parser.error("--end muss nach --start liegen")
    if not (isfinite(args.min_old) and args.min_old <= args.max_old <= 50):
        parser.error("Der alte Wertebereich muss gültig sein und darf höchstens 50 °F umfassen.")
    dsn = dotenv_values(args.env_file).get("DATABASE_URL")
    if not dsn:
        parser.error("DATABASE_URL fehlt in der angegebenen .env.")

    params = (args.device, args.start, args.end, args.min_old, args.max_old)
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*), min(temperature_c), max(temperature_c) "
            "FROM indoor_readings WHERE " + FILTER,
            params,
        )
        count, lo, hi = cursor.fetchone()
        print(f"{count} passende alte Zeilen.")
        if not count:
            return
        c_lo, c_hi = (lo - 32) * 5 / 9, (hi - 32) * 5 / 9
        print(f"Alt {lo:.2f} bis {hi:.2f} → neu {c_lo:.2f} bis {c_hi:.2f} °C.")
        if not args.apply:
            print("Vorschau. Zum Schreiben --apply nur für bestätigte falsch gespeicherte Werte verwenden.")
            return
        cursor.execute(
            "UPDATE indoor_readings "
            "SET temperature_c = round(((temperature_c - 32) * 5 / 9)::numeric, 2)::double precision, "
            "temperature_input_unit = 'fahrenheit' WHERE " + FILTER,
            params,
        )
        print(f"{cursor.rowcount} Zeilen korrigiert.")


if __name__ == "__main__":
    main()