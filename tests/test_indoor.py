"""Regression tests for Govee history and the house comparison."""
import json
import os
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import asyncpg
from fastapi import HTTPException

from app import analytics, config, main


class HouseComparisonTests(unittest.TestCase):
    def test_garage_names_and_configured_ids_are_excluded(self):
        with patch.object(config, "GOVEE_HOUSE_EXCLUDE_DEVICE_IDS", {"outbuilding"}):
            self.assertFalse(main._in_house("device-1", "Govee-Thermostat GARAGE"))
            self.assertFalse(main._in_house("OUTBUILDING", "Werkstatt"))
            self.assertTrue(main._in_house("device-2", "Wohnzimmer"))


class IndoorResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_fine_resolution_is_rejected_for_long_ranges(self):
        for interval, resolution in [("30d", "5m"), ("365d", "1h")]:
            with self.subTest(interval=interval, resolution=resolution):
                with self.assertRaises(HTTPException) as error:
                    await main.api_indoor(range=interval, resolution=resolution)
                self.assertEqual(error.exception.status_code, 422)


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL fehlt")
class IndoorPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_dew_point_is_averaged_only_from_complete_samples(self):
        connection = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
        self.addAsyncCleanup(connection.close)
        await connection.execute("""
            CREATE TEMP TABLE indoor_readings (
                time timestamptz, device_id text, device_name text,
                temperature_c double precision, humidity_pct double precision
            )
        """)
        first = datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc)
        await connection.executemany("INSERT INTO indoor_readings VALUES ($1, $2, $3, $4, $5)", [
            (first + timedelta(minutes=minute), "sensor", "Wohnzimmer", temperature, humidity)
            for minute, temperature, humidity in [
                (0, 20.0, 50.0), (5, 24.0, 60.0), (10, 50.0, None), (15, None, 90.0),
                (20, 25.0, 0.0), (60, None, 60.0),
            ]
        ])

        @asynccontextmanager
        async def acquire():
            yield connection

        with patch.object(main.db, "pool", return_value=SimpleNamespace(acquire=acquire)):
            result = await main.api_indoor("custom", "2026-11-25", "2026-11-25", "1h")

        data = json.loads(result.body)
        series, = data["devices"]
        expected = round((analytics._dew_point(20, 50) + analytics._dew_point(24, 60)) / 2, 2)
        self.assertEqual(data["bucket_seconds"], 3600)
        self.assertEqual(series["temperature_c"], [29.75, None])
        self.assertEqual(series["humidity_pct"], [50.0, 60.0])
        self.assertEqual(series["dew_point_c"], [expected, None])
        self.assertEqual(len(series["t"]), 2)
