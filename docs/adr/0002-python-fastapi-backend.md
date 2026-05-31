# 2. Leichtgewichtiger Python-Dienst für die Steuerzentrale

Wir entwickeln die Kern-Logik und die API der Steuerzentrale als leichtgewichtigen Python-Dienst (Bewässerungs-Daemon) mit FastAPI und SQLite als lokaler Datenbank.

## Kontext

Der Raspberry Pi Zero W hat sehr begrenzte Systemressourcen (512 MB Arbeitsspeicher, ein Prozessorkern). Schwere Systeme wie ein komplettes Home Assistant oder speicherintensive Node-Umgebungen bergen das Risiko von Instabilitäten und hoher CPU-Last, die für eine reine Ventilsteuerung und Zeitplanüberwachung unnötig sind.

## Entscheidung

Wir setzen auf Python 3, da es nativ auf Raspberry Pi OS unterstützt wird und sich durch exzellente Stabilität und eine geringe Speichernutzung auszeichnet:
- **FastAPI** dient als performante, asynchrone Schnittstelle für das zukünftige Web-Cockpit.
- **SQLite** wird als dateibasierte, ressourcenschonende Datenbank genutzt.
- **APScheduler** übernimmt das zeitgesteuerte Auslösen der Bewässerung.

## Konsequenzen

- **Vorteile**: Minimaler RAM- und CPU-Footprint, extrem einfache Backups (die gesamte Datenbank ist eine einzige Datei), schnelle Entwicklungszeit durch ausgereifte Python-MQTT- und Scheduler-Bibliotheken.
- **Nachteile**: Keine vorgefertigte Benutzeroberfläche out-of-the-box; das Web-Cockpit muss separat implementiert werden.
