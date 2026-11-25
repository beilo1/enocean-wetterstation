-- =====================================================================
--  Dachstation – PostgreSQL-Schema
--  Rohdaten + vorab aggregierte Rollups (stündlich / täglich).
--  Idempotent: kann gefahrlos mehrfach ausgeführt werden.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1) Rohdaten: eine Zeile pro Messung des Sensors.
--    time als timestamptz (NICHT als Text wie bisher).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS readings (
    time          timestamptz      NOT NULL,
    sensor_id     text             NOT NULL,
    temperature_c double precision,
    wind_ms       double precision,
    twilight_lux  double precision,
    west_klux     double precision,
    south_klux    double precision,
    east_klux     double precision,
    rain          boolean,
    PRIMARY KEY (sensor_id, time)
);

-- Wichtigster Index für Zeitbereichs-Abfragen.
CREATE INDEX IF NOT EXISTS idx_readings_time ON readings (time DESC);

-- ---------------------------------------------------------------------
-- 2) Stündliche Aggregation. Quelle für 7- und 30-Tage-Ansichten.
--    avg/min/max je Messgröße, rain_any = "hat es in dieser Stunde
--    irgendwann geregnet?", n = Anzahl Rohmessungen im Bucket.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS readings_hourly (
    bucket        timestamptz NOT NULL,
    sensor_id     text        NOT NULL,
    temp_avg      double precision,
    temp_min      double precision,
    temp_max      double precision,
    wind_avg      double precision,
    wind_max      double precision,
    twilight_avg  double precision,
    twilight_max  double precision,
    west_avg      double precision,
    south_avg     double precision,
    south_max     double precision,
    east_avg      double precision,
    rain_any      boolean,
    n             integer,
    PRIMARY KEY (sensor_id, bucket)
);
CREATE INDEX IF NOT EXISTS idx_hourly_bucket ON readings_hourly (bucket DESC);

-- ---------------------------------------------------------------------
-- 3) Tägliche Aggregation. Quelle für die 12-Monats-Ansicht.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS readings_daily (
    bucket        date        NOT NULL,
    sensor_id     text        NOT NULL,
    temp_avg      double precision,
    temp_min      double precision,
    temp_max      double precision,
    wind_avg      double precision,
    wind_max      double precision,
    twilight_avg  double precision,
    twilight_max  double precision,
    west_avg      double precision,
    south_avg     double precision,
    south_max     double precision,
    east_avg      double precision,
    rain_any      boolean,
    n             integer,
    PRIMARY KEY (sensor_id, bucket)
);
CREATE INDEX IF NOT EXISTS idx_daily_bucket ON readings_daily (bucket DESC);

-- ---------------------------------------------------------------------
-- 4) DWD-Vergleichsdaten (über Bright Sky abgerufen).
--    Speichert stündliche Werte der geographisch nächsten DWD-Station.
--    "station" ist ein lesbarer Name, "source_id" die Bright-Sky-Quelle.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dwd_readings (
    time          timestamptz NOT NULL,
    station       text        NOT NULL,
    source_id     integer,
    temperature_c double precision,
    wind_ms       double precision,
    PRIMARY KEY (station, time)
);
CREATE INDEX IF NOT EXISTS idx_dwd_time ON dwd_readings (time DESC);

-- ---------------------------------------------------------------------
-- 5) Innen-Sensoren (z. B. Govee-Hygrometer).
--    Die Cloud-API liefert nur den aktuellen Wert; wir samplen ihn
--    selbst und legen die Historie hier ab.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS indoor_readings (
    time          timestamptz NOT NULL,
    device_id     text        NOT NULL,
    device_name   text,
    temperature_c double precision,
    humidity_pct  double precision,
    PRIMARY KEY (device_id, time)
);
CREATE INDEX IF NOT EXISTS idx_indoor_time ON indoor_readings (time DESC);

-- Regenereignisse: jeweils letzten nassen bzw. unterbrechenden Messpunkt finden.
CREATE INDEX IF NOT EXISTS idx_readings_rain_wet ON readings (sensor_id, time DESC) WHERE rain IS TRUE;
CREATE INDEX IF NOT EXISTS idx_readings_rain_break ON readings (sensor_id, time DESC) WHERE rain IS NOT TRUE;

-- Provenienz der Govee-Temperatur. Altdaten ohne sichere Einheit bleiben NULL.
ALTER TABLE indoor_readings ADD COLUMN IF NOT EXISTS temperature_input_unit text;
