#!/bin/bash
# Automatisches Setup-Skript für den Gartenbewässerungs-Daemon auf dem Raspberry Pi

# Farben für schöne Konsolen-Ausgaben
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}==========================================================${NC}"
echo -e "${GREEN}   Gartenbewässerung-Daemon: System-Einrichtung auf dem Pi${NC}"
echo -e "${GREEN}==========================================================${NC}"
echo ""

# 1. Update und System-Bibliotheken
echo -e "${CYAN}[1/4] Aktualisiere Paketquellen...${NC}"
sudo apt update

echo -e "${CYAN}[2/4] Installiere Mosquitto Broker und Python-Abhängigkeiten...${NC}"
sudo apt install -y mosquitto mosquitto-clients python3-paho-mqtt

# 2. Systemd Hintergrunddienst konfigurieren
echo -e "${CYAN}[3/4] Konfiguriere systemd-Dienst (Autostart)...${NC}"

# Hole aktuellen User und Home-Pfad dynamisch
CURRENT_USER=$USER
CURRENT_HOME=$HOME

sudo tee /etc/systemd/system/garden-irrigation.service > /dev/null <<EOF
[Unit]
Description=Gartenbewaesserungs-Steuerung Daemon
After=network.target mosquitto.service

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${CURRENT_HOME}/garden
ExecStart=/usr/bin/python3 -m src.daemon.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 3. Dienst aktivieren und starten
echo -e "${CYAN}[4/4] Starte und aktiviere den Hintergrunddienst...${NC}"
sudo systemctl daemon-reload
sudo systemctl enable garden-irrigation.service
sudo systemctl restart garden-irrigation.service

echo ""
echo -e "${GREEN}==========================================================${NC}"
echo -e "${GREEN}🎉 Setup erfolgreich abgeschlossen!${NC}"
echo -e "${GREEN}==========================================================${NC}"
echo ""
echo -e "Der Dienst läuft jetzt im Hintergrund und startet bei jedem Boot automatisch."
echo -e "Prüfen Sie den Echtzeit-Status mit folgendem Befehl:"
echo -e "   ${YELLOW}sudo systemctl status garden-irrigation.service${NC}"
echo ""
echo -e "Um die Echtzeit-Logs des Bots zu sehen, nutzen Sie:"
echo -e "   ${YELLOW}journalctl -u garden-irrigation.service -f${NC}"
echo ""
echo -e "Öffnen Sie nun Ihren Telegram-Bot und senden Sie ${GREEN}/start${NC}!"
echo -e "${GREEN}==========================================================${NC}"
