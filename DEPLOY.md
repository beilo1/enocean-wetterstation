# EnOcean Wetterstation installieren

- [Neuinstallation auf dem Raspberry Pi](#neuinstallation-auf-dem-raspberry-pi)
- [Funktion prüfen](#funktion-prüfen)
- [Bestehende Installation aktualisieren](#bestehende-installation-aktualisieren)
- [Optionale SQLite-Migration](#optionale-sqlite-migration)

Die Befehle laufen in Bash auf dem Raspberry Pi, etwa per SSH. Sie setzen Raspberry Pi OS mit systemd, Python ab 3.10 und PostgreSQL ab 14 voraus. Die mitgelieferten Dienste verwenden `/opt/wetter-station`.

## Neuinstallation auf dem Raspberry Pi

### 1. Betriebssystem und Pakete vorbereiten

Installiere mit dem Raspberry Pi Imager ein zum Modell passendes Raspberry Pi OS, zum Beispiel Raspberry Pi OS Lite (64 Bit). Lege dort ein eigenes Benutzerkonto an und aktiviere SSH, wenn du den Pi ohne Bildschirm einrichtest. Verbinde dich nach dem Start mit diesem Konto. [Raspberry Pi OS installieren](https://www.raspberrypi.com/documentation/computers/getting-started.html#install-an-os-using-raspberry-pi-imager)

```bash
sudo apt update
sudo apt install -y git rsync curl postgresql libpq5 python3-venv python3-dev build-essential
python3 --version
psql --version
```

### 2. EnOcean-Empfänger anschließen

**USB-Stick.** Stecke den ESP3-fähigen Empfänger ein und ermittle den Gerätepfad. Ein Eintrag unter `/dev/serial/by-id/` bleibt bei wechselnden USB-Portnummern stabil. Verwende sonst den auf deinem Pi gefundenen Pfad, etwa `/dev/ttyUSB0`.

```bash
ls -l /dev/serial/by-id/
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

**GPIO-Empfänger wie Fam4Pi.** Öffne `sudo raspi-config` und wähle **Interface Options → Serial Port**. Deaktiviere die serielle Login-Shell und aktiviere die serielle Hardware. Starte den Pi neu und prüfe den Pfad. Die Baudrate für die beschriebenen ESP3-Empfänger beträgt 57.600. [Raspberry-Pi-UARTs](https://www.raspberrypi.com/documentation/computers/configuration.html#configuring-uarts)

```bash
ls -l /dev/serial0
```

### 3. Projekt installieren

Klonen oder alternativ das GitHub-Quellarchiv entpacken. Wenn du das Archiv verwendest, setze `source_dir` auf dessen entpackten Ordner mit `db/schema.sql`.

```bash
git clone https://github.com/beilo1/enocean-wetterstation.git "$HOME/enocean-wetterstation"
source_dir="$HOME/enocean-wetterstation"
```

Richte ein eigenes Systemkonto, die Python-Umgebung und die lokal ausgelieferte Diagrammbibliothek ein.

```bash
getent passwd wetter >/dev/null || sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin wetter
sudo usermod -aG dialout wetter
sudo install -d -o wetter -g wetter -m 0755 /opt/wetter-station
test -f "$source_dir/db/schema.sql" &&
  sudo rsync -a --chown=wetter:wetter --exclude='/.git/' --exclude='/.env' --exclude='/venv/' \
    "$source_dir/" /opt/wetter-station/

cd /opt/wetter-station
sudo -u wetter python3 -m venv venv
sudo -u wetter venv/bin/python -m pip install -r backend/requirements.txt -r ingestor/requirements.txt
sudo -u wetter bash scripts/vendor_frontend.sh
```

### 4. PostgreSQL einrichten

```bash
sudo systemctl enable --now postgresql
sudo -u postgres psql
```

Gib in `psql` die folgenden Befehle ein. `\password` fragt ein selbst gewähltes Passwort verdeckt ab.

```sql
CREATE ROLE wetter LOGIN;
\password wetter
CREATE DATABASE wetter OWNER wetter;
ALTER DATABASE wetter SET timezone TO 'UTC';
\q
```

Lege die Tabellen als Datenbankbenutzer `wetter` an. Gib an der Eingabeaufforderung dasselbe Passwort ein.

```bash
cd /opt/wetter-station
psql -h 127.0.0.1 -U wetter -d wetter -W -v ON_ERROR_STOP=1 -f db/schema.sql
```

### 5. Sender-ID ermitteln und Konfiguration ausfüllen

Wenn du die EnOcean-Sender-ID deines Wetterdaten-Sendemoduls schon kennst, kannst du direkt die `.env` anlegen. Sonst starte die Diagnose mit dem in Schritt 2 gefundenen Port. Stoppe sie mit **Strg+C**, sobald du genügend Telegramme gesehen hast. Gesucht ist die achtstellige Hex-ID hinter `ID=`, die bei den Wettertelegrammen mit letztem Datenbyte `18` (trocken) oder `1A` (Regen) und `28` (Helligkeit) wiederkehrt. Vergleiche die ID bei mehreren Sendern mit der Angabe am Funkmodul beziehungsweise in dessen Konfiguration.

```bash
cd /opt/wetter-station
serial_port=/dev/ttyUSB0  # durch den ermittelten Pfad ersetzen
sudo -u wetter env "SERIAL_PORT=$serial_port" BAUDRATE=57600 \
  ENOCEAN_LOGFILE=/opt/wetter-station/enocean-diagnose.csv \
  venv/bin/python ingestor/log_all_enocean.py
```

```bash
cd /opt/wetter-station
sudo install -o wetter -g wetter -m 0600 .env.example .env
sudoedit /opt/wetter-station/.env
```

| Variable | Eintragen |
| --- | --- |
| `DATABASE_URL` | `postgresql://wetter:PASSWORT_HIER@127.0.0.1:5432/wetter` mit dem in Schritt 4 gesetzten Passwort. URL-Sonderzeichen im Passwort müssen prozentkodiert sein, etwa `%40` für `@`. |
| `SENSOR_ID` | Acht Hex-Zeichen der Sender-ID. `DEFAULT_SENSOR_ID` kann leer bleiben und übernimmt dann `SENSOR_ID`. |
| `SERIAL_PORT`, `BAUDRATE` | Gerätepfad aus Schritt 2 und `57600`. |
| `SITE_NAME`, `SITE_LAT`, `SITE_LON` | Optionaler Anzeigename und Koordinatenpaar als Dezimalzahlen mit Punkt. Ohne Koordinaten bleiben Nachtmarkierungen und Prognose aus. |
| `FORECAST_ENABLED`, `FORECAST_HOURS`, `FORECAST_REFRESH_MINUTES` | `1` aktiviert Open-Meteo bei gesetzten Koordinaten. Standardmäßig zwölf Stunden und ein Abruf alle 30 Minuten. `0` schaltet den Abruf aus. |
| `DWD_ENABLED`, `DWD_STATION_ID` | `1` aktiviert die DWD-Vergleichsdaten bei gesetzten Koordinaten oder expliziter Stations-ID. Führende Nullen einer echten Stations-ID beibehalten. Mit `0` bleibt der Abruf aus. |
| `GOVEE_API_KEY`, `GOVEE_DEVICE_IDS` | Für Innenmessungen den eigenen Govee-API-Schlüssel eintragen. Eine leere Geräteliste aktiviert die automatische Suche nach geeigneten Geräten. Alternativ kommagetrennte `device\|sku`-Paare angeben. Ein leerer Schlüssel lässt die Integration aus. |
| `GOVEE_TEMPERATURE_UNIT`, `GOVEE_TEMPERATURE_UNITS` | Eingangs-Standard in der Vorlage ist `fahrenheit`. Explizite Einheiten aus der API werden erkannt. Gerätebezogene Ausnahmen als kommagetrennte `device\|celsius`- oder `device\|fahrenheit`-Paare setzen. |

Govee-Historie entsteht ab der ersten erfolgreichen Messung. Für die optionale SQLite-Migration ist jetzt der passende Zeitpunkt. [SQLite-Import](#optionale-sqlite-migration)

### 6. Dienste starten und Dashboard öffnen

```bash
cd /opt/wetter-station
sudo install -m 0644 deploy/wetter-backend.service deploy/wetter-ingestor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wetter-backend wetter-ingestor
```

Öffne im Browser `http://PI-IP:8000` mit der tatsächlichen IP-Adresse des Pi. PostgreSQL bleibt bei der Standardinstallation lokal. Der Webdienst lauscht auf Port 8000 und hat keine eigene Anmeldung. Dashboard, API und Exporte können Standort- und Innenmessdaten enthalten. Begrenze den Zugriff auf ein vertrauenswürdiges Netz oder nutze einen Reverse Proxy mit Authentifizierung. Bei ausschließlich lokalem Reverse Proxy kannst du Uvicorn in der systemd-Unit an `127.0.0.1` binden.

Bei aktivierten externen Integrationen greift der Server auf `api.open-meteo.com`, `api.brightsky.dev` und `openapi.api.govee.com` zu. Der Browser lädt die Wetterdaten, ECharts und Schriftarten vom Pi.

## Funktion prüfen

```bash
sudo systemctl --no-pager status wetter-backend wetter-ingestor
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/api/latest
curl -fsS http://127.0.0.1:8000/api/rain
curl -fsS http://127.0.0.1:8000/api/forecast
curl -fsS http://127.0.0.1:8000/api/indoor/devices
sudo journalctl -u wetter-backend -u wetter-ingestor -n 80 --no-pager
```

- `/healthz` liefert bei erreichbarer Datenbank `{"status":"ok"}`.
- `/api/latest` enthält nach dem Empfang beider Wettertelegramme eine Messung. Bleibt `latest` leer, prüfe Port, Baudrate, Sender-ID und Zugriffsrechte im Journal. Beende ein noch laufendes Diagnoseskript vor dem Start des Ingestors.
- Die erste Prognose und Govee-Messung können etwas später eintreffen. Der Jahreskalender zeigt Daten nach dem ersten Aufbau der Tagesaggregate.
- Falls keine Diagramme erscheinen, prüfe, ob `frontend/vendor/echarts.min.js` nach Schritt 3 existiert.

## Bestehende Installation aktualisieren

Die Befehle setzen den Standardpfad `/opt/wetter-station` und die Datenbank `wetter` voraus. Prüfe mit `sudo systemctl cat wetter-backend wetter-ingestor` zunächst Dienstkonto und Gruppe. Wenn deine Installation andere Werte verwendet, passe die entsprechenden Variablen, Pfade und Datenbanknamen an. Bewahre `.env` und Sicherungen außerhalb eines öffentlichen Git-Repositories auf.

### 1. Quellcode und Sicherung vorbereiten

Hole die neue Fassung in einen getrennten Ordner wie in Schritt 3 der Neuinstallation beschrieben. Setze `source_dir` auf diesen Ordner. Führe die folgenden Befehle in derselben Bash-Sitzung aus.

```bash
source_dir="$HOME/enocean-wetterstation"
backup=$(mktemp -d "$HOME/wetter-backup-$(date +%F)-XXXXXX") &&
  test -f "$source_dir/db/schema.sql" &&
  sudo systemctl stop wetter-ingestor wetter-backend &&
  sudo tar -czf - -C /opt wetter-station > "$backup/installation.tar.gz" &&
  sudo -u postgres pg_dump -Fc -d wetter > "$backup/wetter.dump" &&
  sudo cp -L /etc/systemd/system/wetter-{backend,ingestor}.service "$backup/" &&
  tar -tzf "$backup/installation.tar.gz" >/dev/null &&
  pg_restore --list "$backup/wetter.dump" >/dev/null &&
  printf 'Sicherung erstellt und lesbar: %s\n' "$backup"
```

Gehe erst nach Ausgabe des Sicherungspfads weiter. Bei einem Abbruch nach dem Stoppen der Dienste kannst du den bisherigen Stand mit `sudo systemctl start wetter-backend wetter-ingestor` wieder starten.

### 2. Code übernehmen

```bash
app_owner=wetter
app_group=wetter
sudo rsync -a --chown="$app_owner:$app_group" --exclude='/.git/' --exclude='/.env' --exclude='/venv/' \
  "$source_dir/" /opt/wetter-station/
cd /opt/wetter-station
sudo -u "$app_owner" venv/bin/python -m pip install -r backend/requirements.txt -r ingestor/requirements.txt
test -s frontend/vendor/echarts.min.js || sudo -u "$app_owner" bash scripts/vendor_frontend.sh
sudoedit /opt/wetter-station/.env
```

Prüfe insbesondere `DATABASE_URL` und `SENSOR_ID`. Trage Standortkoordinaten explizit ein, wenn deine Installation bisher eingebaute Standardwerte verwendet hat. Die vorhandenen Unit-Dateien und Messdaten können weiterverwendet werden. Das Backend ergänzt fehlende Schemaobjekte beim Start.

```bash
sudo systemctl start wetter-backend wetter-ingestor
curl -fsS http://127.0.0.1:8000/healthz
```

Prüfe anschließend die [Funktionen](#funktion-prüfen). Bei älteren Govee-Daten mit bestätigter falscher Temperatureinheit zeigt `venv/bin/python scripts/fix_govee_fahrenheit.py --help`, wie du für eine konkrete Geräte-ID und einen bestätigten Zeitraum eine Vorschau erstellst. Prüfe die Vorschau und sichere die Datenbank, bevor du `--apply` einsetzt.

### 3. Bei Bedarf zum vorherigen Code zurückkehren

```bash
sudo systemctl stop wetter-ingestor wetter-backend
sudo mv /opt/wetter-station "/opt/wetter-station-failed-$(date +%Y%m%d-%H%M%S)"
sudo tar --numeric-owner -xzf "$backup/installation.tar.gz" -C /opt
sudo install -m 0644 "$backup/wetter-backend.service" "$backup/wetter-ingestor.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start wetter-backend wetter-ingestor
curl -fsS http://127.0.0.1:8000/healthz
```

Setze `backup` in einer neuen Shell zuerst auf den zuvor ausgegebenen Sicherungsordner. Der PostgreSQL-Dump ist eine separate Datensicherung für den Fall, dass eine Datenwiederherstellung erforderlich ist.

## Optionale SQLite-Migration

Importiere eine alte `weather.db` mit der Tabelle `weather_readings` nach der Schemaanlage und möglichst vor dem ersten Start beider Dienste. Sichere eine schon befüllte PostgreSQL-Datenbank vorher.

```bash
cd /opt/wetter-station
sudo install -o wetter -g wetter -m 0600 /PFAD/ZUM/BACKUP/weather.db /opt/wetter-station/weather-import.db
sudo -u wetter venv/bin/python scripts/migrate_sqlite_to_pg.py \
  weather-import.db --dsn postgresql://wetter@127.0.0.1:5432/wetter \
  --sensor SENDER_ID_HIER --prompt-password
```

Ersetze `SENDER_ID_HIER` durch die EnOcean-Sender-ID. Der Import nutzt vorhandene IDs aus den Messungen und den Parameter für Zeilen ohne gespeicherte ID. Die alten Zeitstempel werden als Europe/Berlin interpretiert. Schlüsselkonflikte werden übersprungen. Beim ersten Start baut das Backend leere Stunden- und Tagesaggregate auf. Für nachträgliche Importe älterer Zeiträume in eine laufende Installation mit vorhandenen Aggregaten ist gegebenenfalls ein gezielter Neuaufbau erforderlich. Hinweise dazu findest du in der Anwendung unter **Wartung**.
