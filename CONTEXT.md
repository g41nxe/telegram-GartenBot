# Gartenbewässerungs-Steuerung

Dieses System steuert lokal die automatisierte Bewässerung eines Gartens unter Berücksichtigung von Zeitplänen und Umweltdaten.

## Language

**Steuerzentrale**:
Der Raspberry Pi Zero W, welcher die Steuerungslogik ausführt, Zeitpläne verwaltet und die Schnittstelle zum Ventil darstellt.
_Avoid_: Server, Zentralrechner, Pi

**Ventil**:
Das Sonoff Hydro ONE Smart-Wasserlaufventil (Zigbee 3.0) zur physischen Freigabe und Sperrung des Wasserdurchflusses sowie zur Erfassung der Durchflussmenge.
_Avoid_: Schalter, Regler, Sonoff-Gerät

**Funk-Koordinator**:
Der an der Steuerzentrale angeschlossene USB-Zigbee-Dongle, welcher die drahtlose Kommunikation mit dem Ventil ermöglicht.
_Avoid_: Gateway, Hub, Router

**Mittelweg-Dienst**:
Die auf der Steuerzentrale laufende Bridge-Software (Zigbee2MQTT), welche die Zigbee-Funksignale des Ventils in lokale MQTT-Nachrichten übersetzt.
_Avoid_: Funk-Treiber, Bridge-Server

**Bewässerungs-Daemon**:
Der in Python implementierte Hintergrunddienst auf der Steuerzentrale, welcher die Steuerungslogik ausführt, MQTT-Nachrichten verarbeitet, Zeitpläne steuert und Wetterdaten abfragt.
_Avoid_: Backend, Server-Prozess

**Datenbank**:
Die lokale SQLite-Datei, in welcher Zeitpläne, Bewässerungsprotokolle und erfasste Umweltdaten dauerhaft gespeichert werden.
_Avoid_: DB-Server, SQL-Server

**Wetter-Dienst**:
Die externe Online-Wetter-API (z. B. Open-Meteo), über welche der Bewässerungs-Daemon lokale Wettervorhersagen und historische Regenmengen abruft, um Bewässerungsentscheidungen zu treffen.
_Avoid_: Wetterstation, Wettersensoren

**Telegram-Bot**:
Die primäre, gesicherte Benutzeroberfläche, über welche der Benutzer mit dem Bewässerungs-Daemon über Chat-Befehle und interaktive Buttons kommuniziert und Benachrichtigungen erhält.
_Avoid_: Cockpit, Web-App, Dashboard

**Sicherheits-Timeout**:
Die hardwareseitige Schutzfunktion (Auto-Close / Inching) des Ventils, die den Wasserfluss nach einer maximalen Schutzdauer (z. B. 30 Minuten) physisch stoppt, falls der reguläre Abschaltbefehl ausbleibt.
_Avoid_: Software-Timer, Abschaltzeit

**Wetterdaten-Stand**:
Der im Telegram-Bot angezeigte Zeitstempel (Uhrzeit), welcher angibt, wann die Wetter- und Temperaturdaten zuletzt erfolgreich vom Wetter-Dienst abgerufen wurden.
_Avoid_: Abrufzeitpunkt, API-Zeit

**Kombinierter Guss**:
Ein Bewässerungslauf, der durch eine maximale Dauer (Zeitlimit) und eine maximale Wassermenge (Volumenlimit) definiert ist. Die Bewässerung stoppt automatisch, sobald einer der beiden Grenzwerte zuerst erreicht wird.
_Avoid_: Dual-Modus, Mengen-Guss, Zeit-Guss






