#!/usr/bin/env bash
set -euo pipefail

GARDEN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="$HOME/garden-backup"
TMP_ARCHIVE="/tmp/garden-update.tar.gz"
TMP_EXTRACT="/tmp/garden-update-extract"
ENV_FILE="$GARDEN_DIR/.env"
Z2M_DIR="/opt/zigbee2mqtt"
Z2M_UPDATED=false
# Marker, den der Daemon beim Neustart liest, um einen fehlgeschlagenen Update-Versuch
# (Rollback) zu melden (ADR 0044). Erfolgsmeldungen macht der Daemon per Versions-Diff.
ROLLBACK_MARKER="/tmp/garden-ota-rollback"
# Versuchs-Marker (Ticket eor): wird VOR der ersten Änderung am Live-Verzeichnis gesetzt und nur
# bei bestätigtem Erfolg bzw. sauberem Rollback wieder gelöscht. Stirbt das Skript still (set -e)
# irgendwo dazwischen, überlebt der Marker — der Daemon meldet den Abbruch beim nächsten Start.
ATTEMPT_MARKER="/tmp/garden-ota-attempt"

log() { echo "[update] $*"; }
die() { log "FEHLER: $*"; exit 1; }

# --- .env parsen ---
get_env() {
    grep -E "^\s*$1\s*=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]'
}

[ -f "$ENV_FILE" ] || die ".env nicht gefunden unter $ENV_FILE"

GITHUB_PAT="$(get_env GITHUB_PAT)"
GITHUB_REPO="$(get_env GITHUB_REPO)"

[ -z "$GITHUB_PAT" ] && die "GITHUB_PAT nicht in .env gesetzt"
[ -z "$GITHUB_REPO" ] && die "GITHUB_REPO nicht in .env gesetzt"

# --- Neuestes Release abfragen ---
log "Frage GitHub API ab..."
RELEASE_JSON=$(curl -sf \
    -H "Authorization: Bearer $GITHUB_PAT" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$GITHUB_REPO/releases/latest") \
    || die "GitHub API nicht erreichbar"

RELEASE_TAG=$(echo "$RELEASE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])")
ASSET_URL=$(echo "$RELEASE_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
assets = data.get('assets', [])
for a in assets:
    if a['name'].endswith('.tar.gz'):
        print(a['url'])
        break
")

[ -z "$RELEASE_TAG" ] && die "Kein Release gefunden"
[ -z "$ASSET_URL" ] && die "Kein .tar.gz Asset im Release $RELEASE_TAG gefunden"

# --- Versionsvergleich ---
LOCAL_VERSION=""
[ -f "$GARDEN_DIR/VERSION" ] && LOCAL_VERSION=$(cat "$GARDEN_DIR/VERSION")

if [ "$LOCAL_VERSION" = "$RELEASE_TAG" ]; then
    log "Bereits aktuell ($LOCAL_VERSION). Kein Update nötig."
    exit 0
fi

log "Update: $LOCAL_VERSION -> $RELEASE_TAG"

# --- Archiv herunterladen ---
log "Lade Archiv herunter..."
curl -sfL \
    -H "Authorization: Bearer $GITHUB_PAT" \
    -H "Accept: application/octet-stream" \
    "$ASSET_URL" \
    -o "$TMP_ARCHIVE" \
    || die "Download fehlgeschlagen"

# --- Backup anlegen ---
log "Lege Backup an..."
rm -rf "$BACKUP_DIR"
mkdir -p "$BACKUP_DIR"
for DIR in src scripts tools config; do
    [ -d "$GARDEN_DIR/$DIR" ] && cp -r "$GARDEN_DIR/$DIR" "$BACKUP_DIR/"
done
[ -d "$Z2M_DIR" ] && cp -r "$Z2M_DIR" "$BACKUP_DIR/zigbee2mqtt_backup"
[ -f "$GARDEN_DIR/Z2M_VERSION" ] && cp "$GARDEN_DIR/Z2M_VERSION" "$BACKUP_DIR/"
[ -f "$GARDEN_DIR/VERSION" ] && cp "$GARDEN_DIR/VERSION" "$BACKUP_DIR/"

LOCAL_Z2M_VERSION=""
[ -f "$GARDEN_DIR/Z2M_VERSION" ] && LOCAL_Z2M_VERSION=$(cat "$GARDEN_DIR/Z2M_VERSION")

# --- Archiv entpacken ---
log "Entpacke Archiv..."
rm -rf "$TMP_EXTRACT"
mkdir -p "$TMP_EXTRACT"
tar -xzf "$TMP_ARCHIVE" -C "$TMP_EXTRACT"

# Ab hier wird das Live-Verzeichnis verändert — Versuchs-Marker setzen (Ticket eor).
# Stirbt das Skript vor Erfolg oder sauberem Rollback, meldet der Daemon-Start den Abbruch.
echo "$RELEASE_TAG" > "$ATTEMPT_MARKER"

# Dateien übertragen — .env und garden.db nie anfassen
for DIR in src scripts tools config; do
    if [ -d "$TMP_EXTRACT/$DIR" ]; then
        rm -rf "$GARDEN_DIR/$DIR"
        cp -r "$TMP_EXTRACT/$DIR" "$GARDEN_DIR/"
    fi
done

# Versionsdateien kopieren
[ -f "$TMP_EXTRACT/VERSION" ]     && cp "$TMP_EXTRACT/VERSION"     "$GARDEN_DIR/VERSION"
[ -f "$TMP_EXTRACT/Z2M_VERSION" ] && cp "$TMP_EXTRACT/Z2M_VERSION" "$GARDEN_DIR/Z2M_VERSION"

# --- Zigbee2MQTT selektiv aktualisieren ---
if [ -d "$TMP_EXTRACT/zigbee2mqtt" ]; then
    NEW_Z2M_VERSION=""
    [ -f "$TMP_EXTRACT/Z2M_VERSION" ] && NEW_Z2M_VERSION=$(cat "$TMP_EXTRACT/Z2M_VERSION")

    if [ "$LOCAL_Z2M_VERSION" != "$NEW_Z2M_VERSION" ]; then
        log "Zigbee2MQTT Update: $LOCAL_Z2M_VERSION -> $NEW_Z2M_VERSION"
        rm -rf "$Z2M_DIR"
        mkdir -p "$Z2M_DIR"
        cp -r "$TMP_EXTRACT/zigbee2mqtt/." "$Z2M_DIR/"
        log "Installiere node_modules (npm ci --production)..."
        cd "$Z2M_DIR" && npm ci --production
        Z2M_UPDATED=true
    else
        log "Zigbee2MQTT unverändert ($LOCAL_Z2M_VERSION). npm ci übersprungen."
    fi
fi

# --- Service neu starten ---
log "Starte garden-irrigation neu..."
sudo systemctl restart garden-irrigation

# --- Health-Check ---
log "Health-Check (15 Sek)..."
sleep 15

if systemctl is-active --quiet garden-irrigation; then
    # Erfolg meldet der Daemon selbst per Versions-Diff (ADR 0044) — hier keine Nachricht.
    # Versuchs-Marker auflösen: der Versuch ist sauber abgeschlossen (Ticket eor).
    rm -f "$ATTEMPT_MARKER"
    log "Update auf $RELEASE_TAG erfolgreich."
    rm -rf "$TMP_ARCHIVE" "$TMP_EXTRACT"
    exit 0
fi

# --- Rollback ---
log "Health-Check fehlgeschlagen. Starte Rollback auf $LOCAL_VERSION..."
for DIR in src scripts tools config; do
    if [ -d "$BACKUP_DIR/$DIR" ]; then
        rm -rf "$GARDEN_DIR/$DIR"
        cp -r "$BACKUP_DIR/$DIR" "$GARDEN_DIR/"
    fi
done
[ -f "$BACKUP_DIR/VERSION" ]     && cp "$BACKUP_DIR/VERSION"     "$GARDEN_DIR/VERSION"
[ -f "$BACKUP_DIR/Z2M_VERSION" ] && cp "$BACKUP_DIR/Z2M_VERSION" "$GARDEN_DIR/Z2M_VERSION"

if [ "$Z2M_UPDATED" = "true" ] && [ -d "$BACKUP_DIR/zigbee2mqtt_backup" ]; then
    rm -rf "$Z2M_DIR"
    cp -r "$BACKUP_DIR/zigbee2mqtt_backup" "$Z2M_DIR"
    cd "$Z2M_DIR" && npm ci --production
fi

# Rollback-Marker für den Daemon hinterlegen (ADR 0044): enthält das gescheiterte Ziel.
# Der Daemon liest ihn beim Neustart, meldet den Fehlschlag und löscht ihn danach.
# Der sauber durchgeführte Rollback hat Vorrang vor dem Abbruch-Marker (Ticket eor).
echo "$RELEASE_TAG" > "$ROLLBACK_MARKER"
rm -f "$ATTEMPT_MARKER"

sudo systemctl restart garden-irrigation
rm -rf "$TMP_ARCHIVE" "$TMP_EXTRACT"
log "Rollback abgeschlossen. Läuft wieder auf $LOCAL_VERSION."
exit 1
