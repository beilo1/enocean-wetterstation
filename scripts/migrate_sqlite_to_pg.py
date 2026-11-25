#!/usr/bin/env python3
"""
Migration: alte weather.db (SQLite)  ->  PostgreSQL (Tabelle readings).

Die alten Zeitstempel sind naive Lokalzeit (Europe/Berlin). Sie werden
korrekt als Berliner Zeit interpretiert und nach UTC umgerechnet, damit
sie nahtlos an die neu erfassten Daten anschließen.

Aufruf:
    python3 migrate_sqlite_to_pg.py /pfad/zur/weather.db \
        --dsn postgresql://wetter@127.0.0.1:5432/wetter \
        --sensor SENDER_ID_HIER --prompt-password
"""
import argparse
import getpass
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

LOCAL_TZ = ZoneInfo("Europe/Berlin")
UTC = ZoneInfo("UTC")


def rows_from_sqlite(path, sensor_default):
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT ts, sender_id, twilight_lux, temperature_c, wind_ms,
                   rain, west_klux, south_klux, east_klux
            FROM weather_readings ORDER BY ts
        """)
        for r in cur:
            try:
                naive = datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue
            # Lokalzeit -> UTC
            ts_utc = naive.replace(tzinfo=LOCAL_TZ).astimezone(UTC)
            yield (
                ts_utc,
                r["sender_id"] or sensor_default,
                r["temperature_c"], r["wind_ms"], r["twilight_lux"],
                r["west_klux"], r["south_klux"], r["east_klux"],
                bool(r["rain"]) if r["rain"] is not None else None,
            )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sqlite_path")
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--sensor", required=True, type=str.upper, help="Ersatz-ID für Zeilen ohne Sender-ID")
    ap.add_argument("--prompt-password", action="store_true", help="PostgreSQL-Passwort verdeckt abfragen")
    args = ap.parse_args()
    if not re.fullmatch(r"[0-9A-F]{8}", args.sensor):
        ap.error("--sensor muss aus acht Hex-Zeichen bestehen.")

    print(f"Lese {args.sqlite_path} …")
    connection_options = {"password": getpass.getpass("PostgreSQL-Passwort: ")} if args.prompt_password else {}

    with psycopg.connect(args.dsn, **connection_options) as conn:
        with conn.cursor() as cur:
            # In temporäre Tabelle kopieren, dann konfliktfrei einspielen.
            cur.execute("""
                CREATE TEMP TABLE _import (
                    time timestamptz, sensor_id text,
                    temperature_c double precision, wind_ms double precision,
                    twilight_lux double precision, west_klux double precision,
                    south_klux double precision, east_klux double precision,
                    rain boolean
                ) ON COMMIT DROP
            """)
            with cur.copy(
                "COPY _import (time, sensor_id, temperature_c, wind_ms, "
                "twilight_lux, west_klux, south_klux, east_klux, rain) FROM STDIN"
            ) as copy:
                for row in rows_from_sqlite(args.sqlite_path, args.sensor):
                    copy.write_row(row)

            cur.execute("""
                INSERT INTO readings (time, sensor_id, temperature_c, wind_ms,
                    twilight_lux, west_klux, south_klux, east_klux, rain)
                SELECT time, sensor_id, temperature_c, wind_ms,
                    twilight_lux, west_klux, south_klux, east_klux, rain
                FROM _import
                ON CONFLICT (sensor_id, time) DO NOTHING
            """)
            inserted = cur.rowcount

    print(f"Fertig. {inserted:,} neue Zeilen eingefügt.")
    print("Hinweis: Beim ersten Start des Backends werden die Rollups "
          "automatisch aus diesen Daten aufgebaut.")


if __name__ == "__main__":
    main()
