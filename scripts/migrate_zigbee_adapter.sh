#!/bin/bash
# Skript zur automatischen Migration des Zigbee2MQTT-Adaptertyps nach einem Firmware-Upgrade.
# Führt die Schritte (stop -> ezsp -> start -> stop -> ember -> start) automatisch aus.

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${CYAN}[$(date '+%H:%M:%S')]${NC} $*"; }
ok()   { echo -e "${GREEN}✔${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
fail() { echo -e "${RED}✘ FEHLER:${NC} $*"; exit 1; }

INSTALL_DIR="/opt/zigbee2mqtt"
CONFIG_FILE="$INSTALL_DIR/data/configuration.yaml"

if [ ! -f "$CONFIG_FILE" ]; then
    fail "Konfigurationsdatei nicht gefunden unter $CONFIG_FILE. Bitte führen Sie zuerst setup.sh aus."
fi

# Helper zum Setzen des Adapters
set_adapter() {
    local type=$1
    if grep -q "adapter:" "$CONFIG_FILE"; then
        # Ersetze existierende adapter-Zeile
        sudo sed -i "s/^\s*adapter:.*/  adapter: $type/" "$CONFIG_FILE"
    else
        # Füge adapter unter serial: ein
        sudo sed -i "/serial:/a\  adapter: $type" "$CONFIG_FILE"
    fi
}

echo -e "${GREEN}${BOLD}"
echo "=========================================================="
echo "   Zigbee2MQTT: Automatisches Adapter-Firmware-Upgrade    "
echo "   Migration: ezsp (Legacy) -> ember (Modern)            "
echo "=========================================================="
echo -e "${NC}"

# Lese den konfigurierten Port aus der configuration.yaml aus
ZIGBEE_PORT=$(grep -E "^\s*port:" "$CONFIG_FILE" | head -n 1 | cut -d':' -f2- | tr -d ' ' | tr -d '\r')
if [ -z "$ZIGBEE_PORT" ]; then
    ZIGBEE_PORT="/dev/ttyUSB0"
fi

echo -e "${YELLOW}${BOLD}=== VORBEREITUNG ===${NC}"
echo "Bitte stellen Sie sicher, dass:"
echo "1. Der Zigbee-Dongle erfolgreich am PC geflasht wurde."
echo "2. Der Dongle am USB/Daten-Port des Raspberry Pi angeschlossen ist."
echo ""

while [ ! -e "$ZIGBEE_PORT" ]; do
    warn "Funk-Koordinator unter '$ZIGBEE_PORT' wurde nicht erkannt."
    echo -e "Bitte stecken Sie den Dongle jetzt ein und drücken Sie danach ${BOLD}[ENTER]${NC}..."
    read -r
done
ok "Funk-Koordinator unter '$ZIGBEE_PORT' erkannt!"
echo ""

log "Stoppe Zigbee2MQTT-Dienst..."
sudo systemctl stop zigbee2mqtt.service || true
ok "Dienst gestoppt."

log "Schritt 1: Setze temporär adapter: ezsp zur Backup-Konvertierung..."
set_adapter "ezsp"
ok "adapter: ezsp eingetragen."

log "Starte Zigbee2MQTT zur einmaligen Konvertierung..."
sudo systemctl start zigbee2mqtt.service

log "Warte bis Zigbee2MQTT die Konvertierung abschließt..."
success=0
for i in {1..20}; do
    # Suche in den systemd-Journal-Logs der letzten Minute nach Erfolgs- oder Fehlermeldungen
    if sudo journalctl -u zigbee2mqtt.service --since "1 minute ago" | grep -q -E "Successfully started|Starting Zigbee2MQTT version"; then
        # Ein paar Sekunden warten, um sicherzustellen, dass die Konvertierung fertiggeschrieben wurde
        sleep 5
        success=1
        break
    fi
    if sudo journalctl -u zigbee2mqtt.service --since "1 minute ago" | grep -q -E "Error while starting|Exiting|unsupported EZSP version"; then
        warn "Fehler oder Abbruch im Log erkannt."
        break
    fi
    printf "."
    sleep 1.5
done
echo ""

if [ $success -eq 1 ]; then
    ok "Einmaliger Start mit ezsp war erfolgreich (Backup migriert)."
else
    warn "Konnte den erfolgreichen Start mit ezsp nicht bestätigen. Bitte prüfen Sie journalctl -u zigbee2mqtt -f"
fi

log "Stoppe Dienst für den Wechsel..."
sudo systemctl stop zigbee2mqtt.service || true

log "Schritt 2: Wechsle dauerhaft auf adapter: ember..."
set_adapter "ember"
ok "adapter: ember eingetragen."

log "Starte Zigbee2MQTT erneut..."
sudo systemctl start zigbee2mqtt.service

log "Prüfe finalen Status..."
sleep 3
if systemctl is-active --quiet zigbee2mqtt.service; then
    ok "Zigbee2MQTT läuft jetzt erfolgreich mit adapter: ember!"
else
    warn "Zigbee2MQTT läuft nicht – bitte prüfen Sie die Logs mit: journalctl -u zigbee2mqtt -n 50"
fi

echo -e "${GREEN}${BOLD}==========================================================${NC}"
