"""Regression tests for forecast parsing and the rain event query."""
import os
import runpy
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import dwd, forecast, govee, periods, rain, rollups


NOW = datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc)


class ConfigTests(unittest.TestCase):
    def load_config(self, **environment):
        config_path = Path(__file__).resolve().parents[1] / "backend" / "app" / "config.py"
        with patch.dict(os.environ, environment, clear=True):
            return runpy.run_path(str(config_path))

    def test_local_installation_has_no_site_or_credentials_by_default(self):
        config = self.load_config()
        self.assertEqual(config["DATABASE_URL"], "")
        self.assertEqual(config["DEFAULT_SENSOR_ID"], "")
        self.assertFalse(config["HAS_SITE_COORDINATES"])
        self.assertFalse(config["FORECAST_ENABLED"])
        self.assertFalse(config["DWD_ENABLED"])

    def test_site_and_sensor_are_taken_from_the_environment(self):
        config = self.load_config(SITE_LAT="0", SITE_LON="0", SENSOR_ID="abcdef01")
        self.assertTrue(config["HAS_SITE_COORDINATES"])
        self.assertTrue(config["FORECAST_ENABLED"])
        self.assertTrue(config["DWD_ENABLED"])
        self.assertEqual(config["DEFAULT_SENSOR_ID"], "ABCDEF01")

    def test_explicit_dwd_station_can_be_used_without_coordinates(self):
        config = self.load_config(DWD_STATION_ID="00001")
        self.assertEqual(config["DWD_STATION_ID"], "00001")
        self.assertFalse(config["FORECAST_ENABLED"])
        self.assertTrue(config["DWD_ENABLED"])

    def test_incomplete_coordinates_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "SITE_LAT und SITE_LON"):
            self.load_config(SITE_LAT="1")


class ForecastTests(unittest.TestCase):
    def test_missing_weather_and_zero_values(self):
        rows = forecast.normalize({
            "time": [100, 200],
            "temperature_2m": [0.0, None],
            "precipitation_probability": [0],
            "precipitation": [0.0],
            "weather_code": [0, None],
            "is_day": [0, None],
        })
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["t"], 100000)
        self.assertEqual(rows[0]["temperature_c"], 0)
        self.assertEqual(rows[0]["precipitation_probability_pct"], 0)
        self.assertIs(rows[0]["is_day"], False)

    def test_cache_hides_expired_hours_and_labels_old_fetch(self):
        from unittest.mock import patch

        points = [{"t": int((NOW + timedelta(hours=h)).timestamp() * 1000)} for h in (-1, 1, 3)]
        with patch.object(forecast.config, "FORECAST_ENABLED", True), \
             patch.object(forecast.config, "FORECAST_REFRESH_MINUTES", 30), \
             patch.object(forecast, "_cache", (NOW - timedelta(hours=2), points)):
            self.assertEqual(forecast.snapshot(NOW)["status"], "stale")
            self.assertEqual(forecast.snapshot(NOW)["hours"], points[1:])
            self.assertEqual(forecast.snapshot(NOW + timedelta(hours=4))["status"], "unavailable")


class GoveeTests(unittest.TestCase):
    def test_target_temperature_does_not_replace_measured_temperature(self):
        capabilities = [
            {"instance": "sensorTemperature", "type": "devices.capabilities.property", "state": {"value": 68.0}},
            {"instance": "targetTemperature", "type": "devices.capabilities.range", "state": {"value": 32.0}},
            {"instance": "sensorHumidity", "type": "devices.capabilities.property", "state": {"value": {"currentValue": 0}}},
        ]
        self.assertEqual(govee._extract_measurements({"payload": {"capabilities": capabilities}}), (20.0, 0.0, "fahrenheit"))


    def test_fahrenheit_below_old_cutoff(self):
        value = {"instance": "sensorTemperature", "state": {"value": 42.6}}
        payload = {"payload": {"capabilities": [value]}}
        self.assertEqual(govee._extract_measurements(payload), (5.89, None, "fahrenheit"))

    def test_explicit_celsius_and_per_device_override(self):
        from unittest.mock import patch

        value = {"instance": "currentTemperature", "state": {"value": {"currentValue": 5.9, "unit": "°C"}}}
        payload = {"payload": {"capabilities": [value]}}
        self.assertEqual(govee._extract_measurements(payload), (5.9, None, "celsius"))
        payload["payload"]["capabilities"][0]["state"]["value"] = 7.1
        with patch.object(govee.config, "GOVEE_TEMPERATURE_UNITS", "ab:cd|celsius"):
            self.assertEqual(govee._extract_measurements(payload, "AB:CD"), (7.1, None, "celsius"))

    def test_state_strings_offline_errors_and_setpoints(self):
        payload = {"payload": {"capabilities": [
            {"instance": "ambientTemperature", "state": {"value": "-1,5 °C"}},
            {"instance": "targetTemperature", "state": {"value": 40}},
            {"instance": "relativeHumidity", "state": {"value": "61,2 %"}},
        ]}}
        self.assertEqual(govee._extract_measurements(payload), (-1.5, 61.2, "celsius"))
        self.assertEqual(govee._extract_measurements({**payload, "code": 429}), (None, None, None))



class RainSummaryTests(unittest.TestCase):
    def test_gap_makes_current_status_unknown_and_preserves_duration(self):
        row = {
            "latest_time": NOW - timedelta(minutes=8), "latest_rain": True,
            "first_wet": NOW - timedelta(minutes=12), "last_wet": NOW - timedelta(minutes=8),
            "previous_time": NOW - timedelta(minutes=13), "previous_rain": False, "split_at_gap": False,
        }
        result = rain.summarize(row, NOW, 300)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["duration_seconds"], 240)
        self.assertEqual(result["since_last_wet_seconds"], 480)
        self.assertTrue(result["start_bounded"])


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL fehlt")
class RainPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_last_group_is_split_by_gap_and_unknown_sample(self):
        import asyncpg

        connection = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
        try:
            await connection.execute(
                "CREATE TEMP TABLE readings (sensor_id text, time timestamptz, rain boolean)"
            )
            await connection.executemany("INSERT INTO readings VALUES ($1, $2, $3)", [
                ("roof", NOW - timedelta(minutes=minute), wet)
                for minute, wet in [(30, False), (29, True), (28, True), (27, None),
                                    (26, True), (10, True), (9, True), (8, False)]
            ])
            row = await connection.fetchrow(rain._SQL, "roof", 300)
            result = rain.summarize(row, NOW - timedelta(minutes=7), 300)
            self.assertEqual(result["status"], "dry")
            self.assertEqual(result["first_wet_at"], int((NOW - timedelta(minutes=10)).timestamp() * 1000))
            self.assertEqual(result["duration_seconds"], 60)
            self.assertFalse(result["start_bounded"])
            empty = await connection.fetchrow(rain._SQL, "missing", 300)
            self.assertIsNone(rain.summarize(empty, NOW, 300)["last_wet_at"])
        finally:
            await connection.close()



class PeriodTests(unittest.TestCase):
    def test_presets_preserve_resolution_and_rolling_bounds(self):
        for name, seconds, days in (("24h", 300, 1), ("7d", 3600, 7), ("30d", 3600, 30), ("365d", 86400, 365)):
            with self.subTest(name=name):
                period = periods.resolve(name, None, None)
                self.assertEqual(period.seconds, seconds)
                self.assertEqual(period.bounds(NOW), (NOW - timedelta(days=days), NOW))

    def test_large_custom_interval_has_precise_inclusive_last_day(self):
        period = periods.resolve("custom", "2026-01-01", "2026-03-01")
        self.assertEqual(period.seconds, periods.DAY)
        sql, args = period.where("time", 2)
        self.assertEqual(sql, "time >= $2 AND time < $3")
        self.assertEqual(args[1], datetime(2026, 3, 2, tzinfo=timezone.utc))
        date_sql, date_args = period.where("bucket", 2, daily=True)
        self.assertEqual(date_sql, "bucket >= $2 AND bucket < $3")
        self.assertEqual(date_args[1], args[1].date())

    def test_invalid_dates_are_reported_and_unknown_presets_fall_back(self):
        with self.assertRaises(ValueError):
            periods.resolve("custom", "2026-11-31", "2026-12-01")
        with self.assertRaises(ValueError):
            periods.resolve("custom", "2026-12-01", "2026-11-30")
        self.assertEqual(periods.resolve("unknown", None, None).name, "24h")


class DwdTests(unittest.TestCase):
    def test_station_names_are_shared_for_synop_and_historical_sources(self):
        sources = [
            {"id": 1, "dwd_station_id": "abc", "station_name": "Beispiel"},
            {"id": 2, "dwd_station_id": "abc", "station_name": "Beispiel Wetterstation"},
            {"id": 3, "station_name": "Andere"},
            {"id": 4},
        ]
        self.assertEqual(dwd._station_names(sources),
                         {1: "Beispiel Wetterstation", 2: "Beispiel Wetterstation", 3: "Andere", 4: "DWD-4"})


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL fehlt")
class RollupPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_uses_all_rows_of_the_first_hour_and_skips_same_values(self):
        import asyncpg

        conn = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
        try:
            await conn.execute("SET timezone TO 'Europe/Berlin'")
            await conn.execute("""
                CREATE TEMP TABLE readings (
                    time timestamptz, sensor_id text, temperature_c double precision,
                    wind_ms double precision, twilight_lux double precision,
                    west_klux double precision, south_klux double precision,
                    east_klux double precision, rain boolean);
                CREATE TEMP TABLE readings_hourly (
                    bucket timestamptz, sensor_id text, temp_avg double precision,
                    temp_min double precision, temp_max double precision,
                    wind_avg double precision, wind_max double precision,
                    twilight_avg double precision, twilight_max double precision,
                    west_avg double precision, south_avg double precision,
                    south_max double precision, east_avg double precision, rain_any boolean,
                    n integer, PRIMARY KEY(sensor_id, bucket));
                INSERT INTO readings(time, sensor_id, temperature_c) VALUES
                    ('2026-11-25 09:03:00+01', 'roof', 4),
                    ('2026-11-25 09:43:00+01', 'roof', 8);
            """)
            table, bucket, _ = rollups._ROLLUPS[0]
            sql = rollups._upsert_sql(table, bucket, "date_trunc('hour', timestamptz '2026-11-25 09:35:00+01')")
            self.assertEqual(await conn.execute(sql), "INSERT 0 1")
            self.assertEqual(await conn.fetchval("SELECT temp_avg FROM readings_hourly"), 6)
            self.assertEqual(await conn.execute(sql), "INSERT 0 0")
        finally:
            await conn.close()
