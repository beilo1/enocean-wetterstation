#!/usr/bin/env bash
# Setzt saubere Linux-Berechtigungen für die Wetterstation-Installation.
# Idempotent – kann jederzeit erneut ausgeführt werden.
set -euo pipefail

ROOT="/opt/wetter-station"
APP_OWNER="${1:-wetter}"
APP_GROUP="$(id -gn "$APP_OWNER")"

if [[ $EUID -ne 0 ]]; then
  echo "Bitte mit sudo ausführen." >&2
  exit 1
fi

echo "Setze Owner $APP_OWNER:$APP_GROUP rekursiv auf $ROOT …"
chown -R "$APP_OWNER:$APP_GROUP" "$ROOT"

# Erst alles auf sinnvolle Default-Werte: Ordner 755, Dateien 644.
echo "Setze Default-Modi (Ordner 755, Dateien 644) …"
find "$ROOT" -type d -exec chmod 755 {} +
find "$ROOT" -type f -exec chmod 644 {} +

# Shell-Skripte ausführbar machen.
echo "Setze Shell-Skripte auf 755 …"
find "$ROOT/scripts" -maxdepth 1 -type f -name '*.sh' -exec chmod 755 {} + 2>/dev/null || true

# .env enthält Geheimnisse: nur Owner darf lesen.
if [[ -f "$ROOT/.env" ]]; then
  echo "Setze $ROOT/.env auf 600 (nur Besitzer lesbar) …"
  chmod 600 "$ROOT/.env"
fi

# venv: ausführbare Binaries kennzeichnen
if [[ -d "$ROOT/venv/bin" ]]; then
  echo "Stelle sicher, dass venv/bin-Skripte ausführbar sind …"
  find "$ROOT/venv/bin" -maxdepth 1 -type f -exec chmod 755 {} + 2>/dev/null || true
fi

# TLS-Material (optional, nur wenn vorhanden)
if [[ -d /etc/ssl/wetter ]]; then
  echo "Setze TLS-Material in /etc/ssl/wetter …"
  chown root:root /etc/ssl/wetter/cert.pem 2>/dev/null || true
  chmod 644 /etc/ssl/wetter/cert.pem 2>/dev/null || true
  if [[ -f /etc/ssl/wetter/private.pem ]]; then
    # ssl-cert-Gruppe gibt es auf Debian/Raspbian; sonst Fallback auf root
    if getent group ssl-cert >/dev/null; then
      chown root:ssl-cert /etc/ssl/wetter/private.pem
    else
      chown root:root /etc/ssl/wetter/private.pem
    fi
    chmod 640 /etc/ssl/wetter/private.pem
  fi
fi

echo "Fertig."
echo
echo "Übersicht:"
ls -ld "$ROOT" "$ROOT/.env" "$ROOT/scripts" "$ROOT/venv" 2>/dev/null || true
echo
echo "Skripte:"
ls -l "$ROOT/scripts"/*.sh 2>/dev/null || true
