---
name: deploy-garden
description: Überträgt den Gartenbewässerungs-Daemon von diesem Windows-Rechner auf den Raspberry Pi Zero W und leitet die Installation ein.
---
# Deploy Garden Skill

Dieser Skill automatisiert die Bereitstellung des Gartenbewässerungs-Services auf dem Ziel-Raspberry Pi.

## Ablaufprotokoll

1. **Konfiguration prüfen**: 
   Überprüfe vorab, ob die Datei `.env` im Projekt-Root existiert und sinnvolle Werte für `TELEGRAM_BOT_TOKEN` sowie `TELEGRAM_ALLOWED_USER_IDS` enthält. Sollten Standardplatzhalter vorhanden sein, weise den Benutzer darauf hin.

2. **Verbindungsdaten abfragen**:
   Frage den Benutzer nach der IP-Adresse oder dem Hostnamen des Pi (Standard: `raspberrypi.local`) und dem SSH-Benutzernamen (Standard: `pi`).

3. **Deployment ausführen**:
   Führe das PowerShell-Bereitstellungsskript direkt im Terminal des Benutzers aus:
   `powershell -ExecutionPolicy Bypass -File .\deploy.ps1`

4. **Nächste Schritte ausgeben**:
   Bestätige dem Benutzer die erfolgreiche Übertragung und weise ihn an, sich über SSH auf dem Pi einzuloggen und das Setup-Skript auszuführen:
   `cd ~/garden && bash setup.sh`
