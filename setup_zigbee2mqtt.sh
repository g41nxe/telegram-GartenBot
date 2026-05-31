#!/bin/bash
# Automatisches Setup-Skript für den Mittelweg-Dienst (Zigbee2MQTT) auf der Steuerzentrale.
# Installiert Zigbee2MQTT, koppelt das Ventil vollautomatisch und richtet die korrekte
# Startreihenfolge aller Systemdienste ein.
#
# Verwendung: bash setup_zigbee2mqtt.sh [zigbee-port]
# Standard-Port: /dev/ttyUSB0

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

ZIGBEE_PORT="${1:-/dev/ttyUSB0}"
INSTALL_DIR="/opt/zigbee2mqtt"
VALVE_NAME="garden_valve"
PAIRING_TIMEOUT=120  # Sekunden bis Pairing-Abbruch

log()  { echo -e "${CYAN}[$(date '+%H:%M:%S')]${NC} $*"; }
ok()   { echo -e "${GREEN}✔${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
fail() { echo -e "${RED}✘ FEHLER:${NC} $*"; exit 1; }

echo -e "${GREEN}${BOLD}"
echo "=========================================================="
echo "   Mittelweg-Dienst (Zigbee2MQTT): Vollautomatisches     "
echo "   Setup inkl. Ventil-Kopplung & Dienst-Integration      "
echo "=========================================================="
echo -e "${NC}"
echo -e "Funk-Koordinator: ${YELLOW}${ZIGBEE_PORT}${NC}"
echo ""

# ── Schritt 0: Dongle prüfen ───────────────────────────────────────────────
log "[0/6] Prüfe Funk-Koordinator..."
if [ ! -e "$ZIGBEE_PORT" ]; then
    echo -e "${RED}Gerät ${ZIGBEE_PORT} nicht gefunden!${NC}"
    echo "Verfügbare serielle Geräte:"
    ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo "  Keine gefunden."
    echo ""
    fail "Bitte Funk-Koordinator einstecken und Skript erneut starten.\n  Alternativ: bash setup_zigbee2mqtt.sh /dev/ttyACM0"
fi
ok "Funk-Koordinator gefunden: ${ZIGBEE_PORT}"

# ── Schritt 1: Node.js installieren ────────────────────────────────────────
log "[1/6] Installiere Node.js 20..."
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - >/dev/null 2>&1
sudo apt install -y nodejs >/dev/null 2>&1
ok "Node.js $(node --version) installiert"

# ── Schritt 2: Zigbee2MQTT installieren ────────────────────────────────────
log "[2/6] Installiere Mittelweg-Dienst (Zigbee2MQTT) nach ${INSTALL_DIR}..."
sudo mkdir -p "$INSTALL_DIR"
sudo chown -R "$USER" "$INSTALL_DIR"

if [ -d "$INSTALL_DIR/.git" ]; then
    warn "Bereits installiert – überspringe git clone."
else
    git clone --depth 1 https://github.com/Koenkk/zigbee2mqtt.git "$INSTALL_DIR" >/dev/null 2>&1
fi

cd "$INSTALL_DIR"
log "Installiere npm-Abhängigkeiten (kann einige Minuten dauern)..."
npm ci --silent
ok "Mittelweg-Dienst installiert"

# ── Schritt 3: Konfiguration erstellen ─────────────────────────────────────
log "[3/6] Erstelle Konfiguration..."
mkdir -p "$INSTALL_DIR/data"
cat > "$INSTALL_DIR/data/configuration.yaml" <<EOF
# Zigbee2MQTT Konfiguration
# Automatisch erstellt von setup_zigbee2mqtt.sh – nicht manuell bearbeiten.

serial:
  port: ${ZIGBEE_PORT}

permit_join: false

mqtt:
  base_topic: zigbee2mqtt
  server: mqtt://localhost

frontend:
  port: 8080

homeassistant: false

devices:
  # Ventil wird beim Koppeln automatisch eingetragen:
  # '0x<ieee>':
  #   friendly_name: garden_valve
EOF
ok "Konfiguration erstellt"

# ── Schritt 4: Ventil koppeln ──────────────────────────────────────────────
log "[4/6] Starte Ventil-Kopplung (Pairing)..."
echo ""
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}${BOLD}  JETZT: Ventil (Sonoff Hydro ONE) in Pairing-Modus setzen${NC}"
echo -e "${YELLOW}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  → Reset-Knopf am Ventil ${BOLD}5 Sekunden${NC} gedrückt halten"
echo -e "  → Warten bis LED ${BOLD}schnell blinkt${NC}"
echo -e "  → Skript erkennt das Ventil automatisch (max. ${PAIRING_TIMEOUT} Sek.)"
echo ""

# Zigbee2MQTT temporär mit permit_join:true starten
sed -i 's/permit_join: false/permit_join: true/' "$INSTALL_DIR/data/configuration.yaml"
node "$INSTALL_DIR/index.js" &
Z2M_PID=$!

cleanup() {
    kill "$Z2M_PID" 2>/dev/null || true
    wait "$Z2M_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Warte bis Zigbee2MQTT bereit ist
log "Warte auf Start des Mittelweg-Dienstes..."
sleep 10

# Auf Pairing-Event lauschen
log "Warte auf Ventil-Erkennungssignal..."
IEEE_ADDRESS=""
ELAPSED=0

while [ $ELAPSED -lt $PAIRING_TIMEOUT ]; do
    # Lausche 5 Sekunden auf MQTT join-Events
    EVENT=$(mosquitto_sub -h localhost -t "zigbee2mqtt/bridge/event" -C 1 -W 5 2>/dev/null || true)

    if echo "$EVENT" | grep -q '"device_joined"'; then
        IEEE_ADDRESS=$(echo "$EVENT" | grep -o '"ieee_address":"[^"]*"' | grep -o '0x[^"]*')
        break
    fi

    ELAPSED=$((ELAPSED + 5))
    REMAINING=$((PAIRING_TIMEOUT - ELAPSED))
    printf "\r  ⏳ Warte auf Ventil... noch %d Sek.  " "$REMAINING"
done
echo ""

if [ -z "$IEEE_ADDRESS" ]; then
    cleanup
    fail "Kein Ventil erkannt nach ${PAIRING_TIMEOUT} Sekunden.\n  Bitte Reset-Knopf am Sonoff Hydro ONE 5 Sek. halten und Skript erneut starten."
fi

ok "Ventil erkannt! IEEE-Adresse: ${IEEE_ADDRESS}"

# ── Automatisch umbenennen auf garden_valve ────────────────────────────────
log "Benenne Ventil automatisch in '${VALVE_NAME}' um..."
mosquitto_pub -h localhost \
    -t "zigbee2mqtt/bridge/request/device/rename" \
    -m "{\"from\":\"${IEEE_ADDRESS}\",\"to\":\"${VALVE_NAME}\"}"
sleep 3

# Bestätige Umbenennung
CONFIRM=$(mosquitto_sub -h localhost -t "zigbee2mqtt/bridge/response/device/rename" -C 1 -W 5 2>/dev/null || true)
if echo "$CONFIRM" | grep -q '"status":"ok"'; then
    ok "Ventil erfolgreich als '${VALVE_NAME}' registriert"
else
    warn "Umbenennung konnte nicht bestätigt werden – bitte in der Web-UI prüfen (http://$(hostname -I | awk '{print $1}'):8080)"
fi

# permit_join deaktivieren
sed -i 's/permit_join: true/permit_join: false/' "$INSTALL_DIR/data/configuration.yaml"
ok "permit_join deaktiviert (Sicherheit)"

# Temporären Prozess beenden
cleanup
trap - EXIT

# ── Schritt 5: systemd-Dienst einrichten ───────────────────────────────────
log "[5/6] Richte systemd-Dienst ein..."
sudo tee /etc/systemd/system/zigbee2mqtt.service > /dev/null <<EOF
[Unit]
Description=Mittelweg-Dienst (Zigbee2MQTT)
After=network.target mosquitto.service
Wants=mosquitto.service

[Service]
Type=simple
User=${USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/node ${INSTALL_DIR}/index.js
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable zigbee2mqtt.service
sudo systemctl start zigbee2mqtt.service
ok "Mittelweg-Dienst als systemd-Dienst eingerichtet und gestartet"

# ── Schritt 6: Bewässerungs-Daemon anpassen ────────────────────────────────
log "[6/6] Passe Bewässerungs-Daemon an Startreihenfolge an..."
SERVICE_FILE="/etc/systemd/system/garden-irrigation.service"

if [ -f "$SERVICE_FILE" ]; then
    # After-Zeile um zigbee2mqtt ergänzen
    sudo sed -i 's|After=network.target mosquitto.service|After=network.target mosquitto.service zigbee2mqtt.service|' "$SERVICE_FILE"
    sudo sed -i '/After=network.target/a Wants=zigbee2mqtt.service' "$SERVICE_FILE"
    sudo systemctl daemon-reload
    sudo systemctl restart garden-irrigation.service
    ok "Bewässerungs-Daemon startet nun nach Mittelweg-Dienst"
else
    warn "garden-irrigation.service nicht gefunden – bitte zuerst setup.sh ausführen."
fi

# ── Abschluss ──────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}"
echo "=========================================================="
echo "  ✅ Vollständige Einrichtung abgeschlossen!"
echo "=========================================================="
echo -e "${NC}"
echo -e "Startreihenfolge: ${BOLD}Mosquitto → Zigbee2MQTT → Bewässerungs-Daemon${NC}"
echo ""
echo "Dienst-Status prüfen:"
echo -e "   ${YELLOW}sudo systemctl status zigbee2mqtt.service${NC}"
echo ""
echo "Live-Logs:"
echo -e "   ${YELLOW}journalctl -u zigbee2mqtt -f${NC}"
echo ""
echo "Web-Oberfläche:"
echo -e "   ${YELLOW}http://$(hostname -I | awk '{print $1}'):8080${NC}"
echo ""
echo -e "${GREEN}Öffne jetzt den Telegram-Bot und sende /status – das Ventil sollte online sein.${NC}"
echo -e "${GREEN}==========================================================${NC}"
