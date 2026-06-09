---
name: deploy-garden
description: Überträgt das Gartenbewässerungs-System von diesem Windows-Rechner auf den Raspberry Pi Zero W und leitet die vollständige Installation aller Systemdienste ein (Mosquitto, Zigbee2MQTT, Bewässerungs-Daemon).
---
# Deploy Garden Skill

Dieser Skill automatisiert die Bereitstellung des gesamten Gartenbewässerungs-Systems auf dem Ziel-Raspberry Pi.

## Ablaufprotokoll

1. **Konfiguration prüfen**:
   Überprüfe vorab, ob die Datei `.env` im Projekt-Root existiert und sinnvolle Werte für `TELEGRAM_BOT_TOKEN` sowie `TELEGRAM_ALLOWED_USER_IDS` enthält. Sollten Standardplatzhalter vorhanden sein, weise den Benutzer darauf hin, bevor du fortfährst.

2. **Funk-Koordinator prüfen**:
   Frage den Benutzer, ob der Zigbee USB-Funk-Koordinator bereits am Raspberry Pi eingesteckt ist. Wenn nicht, weise ihn darauf hin, dass ohne den Dongle das Ventil-Pairing fehlschlägt.

3. **Verbindungsdaten abfragen**:
   Frage den Benutzer nach der IP-Adresse oder dem Hostnamen des Pi (Standard: `raspberrypi.local`) und dem SSH-Benutzernamen (Standard: `pi`).

4. **Deployment ausführen**:
   Führe das PowerShell-Bereitstellungsskript direkt im Terminal des Benutzers aus:
   `powershell -ExecutionPolicy Bypass -File .\deploy.ps1`

5. **Nächste Schritte ausgeben**:
   Bestätige dem Benutzer die erfolgreiche Übertragung und weise ihn an, sich über SSH auf dem Pi einzuloggen und das **einheitliche** Setup-Skript auszuführen:
   ```
   ssh <user>@<pi-ip>
   cd ~/garden && bash scripts/setup.sh
   ```
   
   Erkläre dem Benutzer, dass `scripts/setup.sh` nun **alle drei Dienste** automatisch einrichtet:
   - Mosquitto MQTT-Broker
   - Mittelweg-Dienst (Zigbee2MQTT) inkl. automatischer Ventil-Kopplung
   - Bewässerungs-Daemon
   
   Und dass er während des Setups aufgefordert wird, den **Reset-Knopf am Ventil 5 Sekunden** zu halten, sobald das Skript dazu auffordert.

6. **Status-Prüfung empfehlen**:
   Nach Abschluss des Setups empfehle folgende Befehle zur Überprüfung:
   ```
   sudo systemctl status mosquitto zigbee2mqtt garden-irrigation
   ```
   Und: Telegram-Bot öffnen und `/status` senden.
