# Gartenbewässerungs-Steuerung

Dieses System steuert lokal die automatisierte Bewässerung eines Gartens unter Berücksichtigung von Zeitplänen und Umweltdaten.

## Language

**Steuerzentrale**:
Der Raspberry Pi Zero W, welcher die Steuerungslogik ausführt, Zeitpläne verwaltet und die Schnittstelle zum Ventil darstellt.
_Avoid_: Server, Zentralrechner, Pi

**Ventil**:
Eines oder mehrere physische Sonoff Hydro ONE Smart-Wasserlaufventile (Zigbee 3.0) zur Freigabe/Sperrung des Wasserdurchflusses und Erfassung der Durchflussmenge. Jedes Ventil besitzt einen eigenen Wunschnamen und eine eindeutige ID im System.
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
Ein Bewässerungslauf, der durch eine maximale Dauer (Zeitlimit) und eine maximale Wassermenge (Volumenlimit) definiert ist. Die Bewässerung stoppt automatisch, sobald einer der beiden Grenzwerte zuerst erreicht wird. Im parallelen Betrieb gilt dies individuell pro Ventil.
_Avoid_: Dual-Modus, Mengen-Guss, Zeit-Guss

**Ventil-Kopplung**:
Der geführte Einrichtungsvorgang im Telegram-Bot (`/setup`), bei dem ein neues Ventil mit dem Funk-Koordinator verbunden wird. Der Benutzer vergibt vorab einen Wunschnamen. Der Bewässerungs-Daemon aktiviert temporär den Koppelmodus des Mittelweg-Dienstes, wartet auf das Beitrittssignal des Ventils, weist ihm einen eindeutigen Systemnamen (`valve_<ieee_address>`) zu und registriert es in der Datenbank.
_Avoid_: Pairing, Registrierung, Gerät hinzufügen

**Guss-Steuerung**:
Die softwareseitige Kernkomponente des Bewässerungs-Daemons, welche die zeit- und volumenbasierte Grenzüberwachung des Kombinierten Gusses ausführt und den physischen Ventil-Zustand kontrolliert. Sie kann mehrere Ventile parallel oder sequentiell steuern.
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

**Gieß-Empfehlung**:
Die vom Bewässerungs-Daemon berechnete Einschätzung, ob eine manuelle oder geplante Bewässerung heute sinnvoll ist. Basiert auf dem Regen-Fenster (letzte + nächste 24h), der Tagestemperatur und der Hitzestrecke. Wird auf Anfrage über den Telegram-Bot ausgegeben (`/giesscheck`).
_Avoid_: Gieß-Ratschlag, Bewässerungs-Hinweis, Watering-Advice

**Hitzestrecke**:
Die Anzahl aufeinanderfolgender abgeschlossener Vortage, an denen die maximale Tagestemperatur einen konfigurierten Schwellenwert (Standard: 25°C) erreicht oder überschritten hat. Eine Lücke (fehlende Wetterdaten, z.B. Steuerzentrale offline) bricht die Hitzestrecke ab.
_Avoid_: Hitzeperiode, Hitzewelle, Hot-Streak

**Regen-Fenster**:
Die Summe des gemessenen Niederschlags der letzten 24 Stunden und der vorhergesagten Niederschlagsmenge der nächsten 24 Stunden. Entspricht dem bestehenden Schwellenwert `RAIN_THRESHOLD_MM` und wird sowohl für die Gieß-Empfehlung als auch für die automatische Überspringlogik des Schedulers verwendet.
_Avoid_: Regen-Periode, Niederschlags-Fenster, Rain-Window

**Inaktivitäts-Watchdog**:
Die Überwachungslogik im Bewässerungs-Daemon, die das Ausbleiben regelmäßiger Lebenszeichen von batteriebetriebenen Geräten (z. B. mehr als 18 Stunden beim Füllstandssensor oder mehr als 24 Stunden bei einem Ventil) erkennt und proaktiv über den Telegram-Bot warnt.
_Avoid_: Offline-Timer, Connection-Checker, Heartbeat-Sensor
