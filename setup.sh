#!/bin/bash
# Automatisches Setup-Skript für das Gartenbewässerungs-System auf dem Raspberry Pi.
# Richtet alle drei Systemdienste ein:
#   1. Mosquitto MQTT-Broker
#   2. Mittelweg-Dienst (Zigbee2MQTT) inkl. vollautomatischer Ventil-Kopplung
#   3. Bewässerungs-Daemon (garden-irrigation)
#
# Verwendung: bash setup.sh [zigbee-port]
# Standard Zigbee-Port: /dev/ttyUSB0

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

ZIGBEE_PORT="${1:-/dev/ttyUSB0}"
CURRENT_USER=$USER
CURRENT_HOME=$HOME
VALVE_NAME="garden_valve"
PAIRING_TIMEOUT=120

log()  { echo -e "${CYAN}[$(date '+%H:%M:%S')]${NC} $*"; }
ok()   { echo -e "${GREEN}✔${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
fail() { echo -e "${RED}✘ FEHLER:${NC} $*"; exit 1; }

echo -e "${GREEN}${BOLD}"
echo "=========================================================="
echo "   Gartenbewässerungs-System: Vollautomatisches Setup     "
echo "   Mosquitto · Zigbee2MQTT · Bewässerungs-Daemon          "
echo "=========================================================="
echo -e "${NC}"

# ══════════════════════════════════════════════════════════════
# SCHRITT 1: System-Pakete
# ══════════════════════════════════════════════════════════════
log "[1/6] Aktualisiere Paketquellen..."
sudo apt update -qq

log "[1/6] Installiere Mosquitto, mosquitto-clients und Python-Abhängigkeiten..."
sudo apt install -y mosquitto mosquitto-clients python3-paho-mqtt git curl
ok "System-Pakete installiert"

# ══════════════════════════════════════════════════════════════
# SCHRITT 2: Node.js für Zigbee2MQTT
# ══════════════════════════════════════════════════════════════
log "[2/6] Installiere Node.js 20..."
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - >/dev/null 2>&1
sudo apt install -y nodejs >/dev/null 2>&1
ok "Node.js $(node --version) installiert"

# ══════════════════════════════════════════════════════════════
# SCHRITT 3: Mittelweg-Dienst (Zigbee2MQTT) installieren
# ══════════════════════════════════════════════════════════════
log "[3/6] Installiere Mittelweg-Dienst (Zigbee2MQTT)..."

# Funk-Koordinator prüfen
if [ ! -e "$ZIGBEE_PORT" ]; then
    echo ""
    echo -e "${RED}Funk-Koordinator nicht gefunden unter: ${ZIGBEE_PORT}${NC}"
    echo "Verfügbare serielle Geräte:"
    ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo "  Keine gefunden."
    fail "Funk-Koordinator (USB-Zigbee-Dongle) einstecken und Setup erneut starten.\n  Alternativ: bash setup.sh /dev/ttyACM0"
fi
ok "Funk-Koordinator gefunden: ${ZIGBEE_PORT}"

INSTALL_DIR="/opt/zigbee2mqtt"
sudo mkdir -p "$INSTALL_DIR"
sudo chown -R "$CURRENT_USER" "$INSTALL_DIR"

if [ -d "$INSTALL_DIR/.git" ]; then
    warn "Zigbee2MQTT bereits vorhanden – überspringe Download."
else
    log "Lade Zigbee2MQTT herunter..."
    git clone --depth 1 https://github.com/Koenkk/zigbee2mqtt.git "$INSTALL_DIR" >/dev/null 2>&1
fi

log "Installiere npm-Abhängigkeiten (kann einige Minuten dauern)..."
cd "$INSTALL_DIR" && npm ci --silent
ok "Mittelweg-Dienst installiert"

# ══════════════════════════════════════════════════════════════
# SCHRITT 4: Konfiguration des Mittelweg-Dienstes
# ══════════════════════════════════════════════════════════════
log "[4/6] Konfiguriere Mittelweg-Dienst..."

mkdir -p "$INSTALL_DIR/data"
cat > "$INSTALL_DIR/data/configuration.yaml" <<EOF
# Zigbee2MQTT Konfiguration
# Automatisch erstellt von setup.sh – nicht manuell bearbeiten.

serial:
  port: ${ZIGBEE_PORT}

permit_join: false

mqtt:
  base_topic: zigbee2mqtt
  server: mqtt://localhost

frontend:
  port: 8080

homeassistant: false
EOF

ok "Mittelweg-Dienst konfiguriert"


# ══════════════════════════════════════════════════════════════
# SCHRITT 5: Alle systemd-Dienste einrichten
# ══════════════════════════════════════════════════════════════
log "[5/6] Richte systemd-Dienste ein..."

# Mittelweg-Dienst (Zigbee2MQTT)
sudo tee /etc/systemd/system/zigbee2mqtt.service > /dev/null <<EOF
[Unit]
Description=Mittelweg-Dienst (Zigbee2MQTT)
After=network.target mosquitto.service
Wants=mosquitto.service

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/node ${INSTALL_DIR}/index.js
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Bewässerungs-Daemon – startet nach Mosquitto UND Zigbee2MQTT
sudo tee /etc/systemd/system/garden-irrigation.service > /dev/null <<EOF
[Unit]
Description=Gartenbewaesserungs-Steuerung Daemon
After=network.target mosquitto.service zigbee2mqtt.service
Wants=mosquitto.service zigbee2mqtt.service

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${CURRENT_HOME}/garden
ExecStart=/usr/bin/python3 -m src.daemon.main
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable mosquitto.service
sudo systemctl enable zigbee2mqtt.service
sudo systemctl enable garden-irrigation.service

sudo systemctl restart mosquitto.service
sudo systemctl restart zigbee2mqtt.service
sudo systemctl restart garden-irrigation.service

ok "Alle drei Dienste aktiviert und gestartet"

# ══════════════════════════════════════════════════════════════
# SCHRITT 6: Status-Check
# ══════════════════════════════════════════════════════════════
log "[6/6] Prüfe Dienst-Status..."
sleep 3

check_service() {
    if systemctl is-active --quiet "$1"; then
        ok "$1 läuft"
    else
        warn "$1 läuft NICHT – prüfe mit: journalctl -u $1 -n 30"
    fi
}

check_service mosquitto
check_service zigbee2mqtt
check_service garden-irrigation

# ══════════════════════════════════════════════════════════════
# ABSCHLUSS
# ══════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}${BOLD}"
echo "=========================================================="
echo "  ✅ Vollständiges Setup abgeschlossen!"
echo "=========================================================="
echo -e "${NC}"
echo -e "Startreihenfolge: ${BOLD}Mosquitto → Zigbee2MQTT → Bewässerungs-Daemon${NC}"
echo ""
echo "Dienst-Status prüfen:"
echo -e "   ${YELLOW}sudo systemctl status mosquitto zigbee2mqtt garden-irrigation${NC}"
echo ""
echo "Live-Logs:"
echo -e "   ${YELLOW}journalctl -u garden-irrigation -f${NC}"
echo ""
echo "Zigbee2MQTT Web-UI:"
echo -e "   ${YELLOW}http://$(hostname -I | awk '{print $1}'):8080${NC}"
echo ""
echo -e "${GREEN}Öffne jetzt den Telegram-Bot und sende /status${NC}"
echo -e "${GREEN}==========================================================${NC}"
