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
Die hardwareseitige Schutzfunktion (Auto-Close / Fail-Safe) des Ventils, die den Wasserfluss nach einer maximalen Schutzdauer (z. B. 30 Minuten) physisch stoppt, falls der reguläre Abschaltbefehl ausbleibt. Beim Sonoff Hydro ONE wird dies über das Parameter-Feld `manual_default_settings.fail_safe` des Mittelweg-Dienstes gesteuert.
_Avoid_: Software-Timer, Abschaltzeit, Inching

**Wetterdaten-Stand**:
Der im Telegram-Bot angezeigte Zeitstempel (Uhrzeit), welcher angibt, wann die Wetter- und Temperaturdaten zuletzt erfolgreich vom Wetter-Dienst abgerufen wurden.
_Avoid_: Abrufzeitpunkt, API-Zeit

**Kombinierter Guss**:
Ein Bewässerungslauf, der durch eine maximale Dauer (Zeitlimit) und eine maximale Wassermenge (Volumenlimit) definiert ist. Die Bewässerung stoppt automatisch, sobald einer der beiden Grenzwerte zuerst erreicht wird.
_Avoid_: Dual-Modus, Mengen-Guss, Zeit-Guss

**Ventil-Kopplung**:
Der einmalige, geführte Einrichtungsvorgang im Telegram-Bot (`/setup`), bei dem das Ventil erstmals mit dem Funk-Koordinator verbunden wird. Der Bewässerungs-Daemon aktiviert dabei temporär den Koppelmodus des Mittelweg-Dienstes, wartet auf das Beitrittssignal des Ventils und weist ihm automatisch den Systemnamen `garden_valve` zu.
_Avoid_: Pairing, Registrierung, Gerät hinzufügen

**Guss-Steuerung**:
Die softwareseitige Kernkomponente des Bewässerungs-Daemons, welche die zeit- und volumenbasierte Grenzüberwachung des Kombinierten Gusses ausführt und den physischen Ventil-Zustand kontrolliert.
_Avoid_: Cycle-Controller, Ventil-Manager

**Ereignis-Kanal**:
Systeminterner Kommunikationskanal zur entkoppelten Weiterleitung von Zustandsmeldungen (z. B. Guss gestoppt, Ventil gekoppelt) von der Guss-Steuerung an die Datenbank und die Präsentationsschicht.
_Avoid_: Event-Bus, Message-Broker

**Füllstandssensor**:
Der batteriebetriebene, WLAN-basierte Ultraschallsensor (M5Stack AtomS3 Lite) zur berührungslosen Erfassung des Abstands zur Flüssigkeitsoberfläche in der Klärgrube.
_Avoid_: Distanzmesser, Sensor-Modul, ESP32, Pegelmesser

**Füllstands-Meldung**:
Das vom Füllstandssensor per MQTT an die Steuerzentrale gesendete Datenpaket mit der gemessenen Distanz (in cm) und der aktuellen Batteriespannung.
_Avoid_: Sensor-Signal, Telemetrie-Paket

**Inaktivitäts-Watchdog**:
Die Überwachungslogik im Bewässerungs-Daemon, die das Ausbleiben regelmäßiger Lebenszeichen von batteriebetriebenen Geräten (z. B. mehr als 18 Stunden beim Füllstandssensor oder mehr als 24 Stunden beim Ventil) erkennt und proaktiv über den Telegram-Bot warnt.
_Avoid_: Offline-Timer, Connection-Checker, Heartbeat-Sensor

## Architecture Rules

- **Stateless Adapters**: Adapters (e.g. `weather`, `database`, `mqtt_client`) MUST be stateless and MUST NOT import other adapters. 
- **Event-Driven Side Effects**: Cross-cutting concerns and side-effects (like logging to the database or sending UI notifications) MUST NOT be executed via direct function calls across boundaries. Instead, they MUST be handled by publishing Domain Events to the system's `EventBus` (Ereignis-Kanal).
