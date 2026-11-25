#!/usr/bin/env bash
# Lädt ECharts für die lokale Auslieferung an den Browser.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/../frontend/vendor" && pwd)"
URL="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"
download="$(mktemp "$DIR/.echarts.XXXXXX")"
trap 'rm -f -- "$download"' EXIT
echo "Lade ECharts nach $DIR/echarts.min.js"
curl -fsSL "$URL" -o "$download"
chmod 0644 "$download"
mv -f -- "$download" "$DIR/echarts.min.js"
echo "Fertig ($(du -h "$DIR/echarts.min.js" | cut -f1))."
