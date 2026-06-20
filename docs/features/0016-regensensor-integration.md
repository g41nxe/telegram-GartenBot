# Feature: Regensensor-Integration (Aqua Scope RANWIE01)

## Problemstellung (Problem Statement)

Die Bewässerungs-Entscheidungen des Systems beruhen bisher auf regionalen Wetterdaten des Wetter-Dienstes. Lokale Schauer im Garten werden von der ERA5-Reanalyse oft nicht erfasst, weil das tatsächliche Mikroklima vom interpolierten Stationswert abweicht (dokumentiert in ADR 0024). Der Benutzer besitzt nun einen physischen Regensensor und möchte dessen lokale Messungen als Grundlage für genauere Entscheidungen nutzen — sowohl für die Überspringlogik als auch um eine laufende Bewässerung sofort zu unterbrechen, wenn es zu regnen beginnt. Außerdem sollen die Messdaten dauerhaft gespeichert werden, um später Analysen (z. B. Vergleich Vorhersage vs. Messung, temperaturabhängige Gieß-Mengen) zu ermöglichen.

## Lösung (Solution)

Der Bewässerungs-Daemon abonniert das MQTT-Topic des Regensensors. Bei Eingang einer Regenmessung publiziert der Mittelweg-Pfad ein `RainSensorMeasured`-Ereignis in den Ereignis-Kanal. Mehrere Abonnenten reagieren entkoppelt darauf:

1. **Dauerhafte Speicherung:** Der `DatabaseLoggerAdapter` schreibt jede Regenmessung als Zeitreihe in eine neue Tabelle — Niederschlagsmenge, kumulierter Gesamtwert, Temperatur und Batteriestand.
2. **Echtzeit-Schutz (Guss-Unterbrechung):** Erkennt der Sensor aktiven Regen, stoppt die Guss-Steuerung alle laufenden Kombinierten Güsse sofort und veröffentlicht ein eigenständiges `WateringCycleInterrupted`-Ereignis.
3. **Genauere Überspringlogik:** Der Wetter-Dienst-Pfad (`weather.py`) verwendet die lokale 24h-Summe des Regensensors als primäre Quelle für die gefallene Regenmenge. Die ERA5-Reanalyse bleibt automatischer Fallback, falls der Sensor länger als ein konfiguriertes Fenster keine Regenmessung sendet.
4. **Sofort-Benachrichtigung (Flankensteuerung):** Beim Einsetzen von Regen sendet der Telegram-Bot eine einmalige Push-Nachricht; eine Entwarnung folgt, wenn der Regen aufhört. Während andauerndem Regen wird der Benutzer nicht wiederholt benachrichtigt.
5. **Statusanzeige & Tagesbericht:** Der aktuelle Sensorzustand erscheint in `/status` und als eigene Sektion im Tagesbericht inklusive der verwendeten Datenquelle.
6. **Inaktivitäts-Watchdog:** Bleibt die Regenmessung über das erwartete Heartbeat-Fenster hinaus aus, warnt das System proaktiv.

## User Stories

1. Als Benutzer möchte ich, dass das System lokale Regenmessungen meines Regensensors statt regionaler Wettervorhersagen für die Überspringentscheidung verwendet, damit Bewässerungen auch bei lokalen Schauern korrekt übersprungen werden.
2. Als Benutzer möchte ich, dass eine laufende Bewässerung sofort gestoppt wird, sobald der Regensensor Regen meldet, um Wasser zu sparen und Überwässerung zu vermeiden.
3. Als Benutzer mit mehreren Ventilen möchte ich, dass bei erkanntem Regen alle aktiven Güsse gleichzeitig unterbrochen werden, da Regen den gesamten Garten betrifft.
4. Als Benutzer des Telegram-Bots möchte ich beim Einsetzen von Regen eine sofortige Benachrichtigung erhalten, um über die Wetterlage im Garten informiert zu sein.
5. Als Benutzer möchte ich während andauerndem Regen nicht wiederholt benachrichtigt werden, sondern nur einmal beim Beginn und einmal beim Ende.
6. Als Benutzer möchte ich im `/status`-Befehl den aktuellen Messwert, die Gesamtmenge, die Temperatur und den Batteriestand des Regensensors sehen, um den Sensorzustand zu prüfen.
7. Als Benutzer möchte ich im Tagesbericht eine eigene Regensensor-Sektion sehen (Tagessumme, stärkstes Intervall, Temperaturverlauf, Batterie), um den Tagesverlauf nachzuvollziehen.
8. Als Benutzer möchte ich im Tagesbericht und in `/status` sehen, welche Datenquelle (Regensensor oder ERA5) gerade für die gefallene Regenmenge verwendet wird, um die Verlässlichkeit einzuschätzen.
9. Als Benutzer möchte ich benachrichtigt werden, wenn mein Regensensor länger als erwartet keine Daten sendet, damit ich einen Batterie- oder Verbindungsausfall erkenne.
10. Als Benutzer möchte ich, dass das System bei Ausfall des Regensensors transparent auf die ERA5-Reanalyse zurückfällt, damit die Bewässerungsentscheidungen weiterhin funktionieren.
11. Als Benutzer möchte ich, dass eine durch Regen unterbrochene Bewässerung im Tagesbericht klar als Unterbrechung (nicht als regulärer Abschluss oder manueller Stopp) erkennbar ist.
12. Als Benutzer möchte ich, dass alle Regenmessungen dauerhaft gespeichert werden, um später Auswertungen über mehrere Saisons durchführen zu können.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Kommunikationsprotokoll:** MQTT-nativ. Der Regensensor ist ein WLAN-Gerät, das direkt in den bestehenden Mosquitto-Broker publiziert — keine neue HTTP-Infrastruktur. Das Topic ist konfigurierbar (Standard: `sensor/rain`, generischer Präfix statt Herstellername).
- **Neues Domänen-Ereignis `RainSensorMeasured`:** Trägt Niederschlagsmenge des Intervalls, kumulierten Gesamtwert, Temperatur (°C), Batteriestand (%) und das berechnete Kennzeichen `is_raining`. Das `is_raining`-Flag wird bereits im Mittelweg-Pfad anhand des konfigurierten Schwellenwerts berechnet, damit die Kernlogik keine Konfiguration kennen muss. Das Ereignis lebt in einer neuen Datei `core/sensor_events.py`.
- **Temperatur-Konvertierung:** Der Sensor liefert die Temperatur in 1/10 °C (z. B. `"200"` = 20,0 °C). Die Umrechnung erfolgt beim Parsen im Mittelweg-Pfad.
- **Zwei separate Guss-Abbruch-Ereignisse mit gemeinsamem Eltern-Ereignis:** Ein manueller Stopp durch den Benutzer und eine systemseitige Guss-Unterbrechung sind semantisch verschieden. Beide erben von einem gemeinsamen Eltern-Ereignis, das die gemeinsamen Felder (gelaufene Dauer, geflossenes Volumen, Quelle, Details) definiert:

  ```
  WateringCycleTerminated          # Eltern; definiert gemeinsame Felder
  ├── WateringCycleStopped         # manueller Stopp durch Benutzer
  └── WateringCycleInterrupted     # Guss-Unterbrechung durch System (Regen)
  ```

  Da der Ereignis-Kanal exakt auf den konkreten Ereignistyp matcht (kein `isinstance`), empfangen Abonnenten des Eltern-Typs keine Kind-Ereignisse. Komponenten, die beide Vorgänge verarbeiten (z. B. der Datenbank-Adapter), abonnieren beide konkreten Typen. Die Watering-Ereignisse werden dabei aus dem Guss-Steuerungs-Modul in eine eigene Ereignis-Datei ausgelagert.
- **Datenbankschema:** Neue Tabelle `rain_measurements` mit Zeitstempel, Niederschlag des Intervalls, kumuliertem Gesamtwert, Temperatur und Batteriestand, samt Index auf den Zeitstempel. Die Migration läuft automatisch beim Systemstart (try/except-Muster für Schema-Drift, kein Migrations-Framework). Ein neues Datenbank-Query liefert die 24h-Summe der Niederschlagsmengen.
- **Datenhaltung:** Kein automatischer Aufräum-Job. Die Tabelle wächst unbegrenzt (für die geplante Mehr-Saison-Analyse erwünscht; das Datenvolumen ist für SQLite unkritisch).
- **Guss-Unterbrechung in der Guss-Steuerung:** Die Guss-Steuerung abonniert `RainSensorMeasured`. Bei `is_raining=True` werden alle aktiven Zyklen geschlossen und je ein `WateringCycleInterrupted` veröffentlicht. Die Details enthalten die gemessene Regenmenge.
- **Wetter-Dienst-Pfad:** Die gefallene Regenmenge der letzten 24h stammt primär aus der Regensensor-Zeitreihe. Ist der jüngste Eintrag älter als das konfigurierte Offline-Fenster, greift der bestehende ERA5-Pfad. Es gibt keine gleitende Mischung beider Quellen — der Sensor hat Vorrang, ERA5 ist vollständiger Ersatz. Die aktive Quelle wird im bestehenden `rain_last_source`-Feld kenntlich gemacht.
- **Benachrichtigungs-Zustand (Flankensteuerung):** Der Sendezustand für die Regen-Benachrichtigung wird persistent in den System-Metadaten abgelegt (gleiches Muster wie der Watchdog). Eine Benachrichtigung wird nur beim Übergang trocken→Regen gesendet, eine Entwarnung beim Übergang Regen→trocken.
- **Inaktivitäts-Watchdog:** Der bestehende Watchdog wird um den Regensensor erweitert. Das Inaktivitäts-Fenster orientiert sich am Heartbeat-Intervall des Sensors (alle 6 Stunden bei Trockenheit) plus Puffer. Sofortige Entwarnung beim nächsten Eingang einer Regenmessung, analog zu Ventil und Garten-Kamera.
- **Konfiguration:** Drei neue Umgebungsvariablen — Topic, Schwellenwert für „es regnet" und Offline-Fenster für den ERA5-Fallback — jeweils mit sinnvollen Standardwerten und Dokumentation in der `.env`-Vorlage.
- **Telegram-Oberfläche:** Erweiterung von `/status` und Tagesbericht sowie die Guss-Unterbrechungs- und Regen-Benachrichtigungen (Details unten). Alle Texte folgen verbindlich dem Design-System (ADR 0029 / `docs/design/telegram-design-system.html`) und sind nach der Umsetzung in IST- und SOLL-Referenz nachzuziehen (siehe `.claude/rules/telegram_messages.md`).
- **Architektur-Abweichung:** ADR 0028 löst ADR 0003 ab (Verzicht auf physische Sensoren). Begründung und Konsequenzen sind dort dokumentiert.

### Konkrete Telegram-Formate

Die folgenden Formate folgen dem Design-System (ADR 0029 / `docs/design/telegram-design-system.html`): Anrede „du", Header `*Emoji Titel*` ohne Doppelpunkt, Einheiten mit Leerzeichen (`1.4 mm`, `2.1 l`), Zeiten mit „Uhr", Garten-Ampel/Progressive Disclosure, qualitative Batterie (`voll`/`mittel`/`schwach`). Beispieldaten sind eingesetzt; Titel werden fett dargestellt.

**`/status` — Regensensor-Zeile** in `handle_status()`, im kompakten gebündelten Stil der übrigen Geräte. „Aktuell" = `rainlevel_mm` der letzten Regenmessung, „Gesamt" = `raintotal_mm`. Batterie qualitativ über `_get_battery_description()`. Entfällt vollständig, wenn kein Regensensor registriert ist.

```
🌧 Regen  1.4 mm · Gesamt 18.2 mm · 🌡 21.8 °C · 🔋 voll
```

Offline (kein Eintrag jünger als `RAIN_SENSOR_OFFLINE_HOURS`) — der Regensensor wird über den Watchdog zum Aufmerksamkeits-/Problemfall der Garten-Ampel; die Technik-Details erscheinen nur dann (Progressive Disclosure):

```
🌧 Regen  ⚠️ Sensor offline (seit 7.2 h) · Regen-24h via ERA5
```

**`/report` & Tagesbericht** — beide nutzen `daily_report.generate_daily_report()`, also genügt eine Änderung an zwei Stellen:

1. *Quellen-Marker am bestehenden Regen-Satz* in `_format_weather_section()`. An „X mm Regen gefallen" wird die Quelle angehängt: `(lokal gemessen)` bei Sensor-Quelle, `(ERA5-Reanalyse)` beim Fallback. Nutzt das bestehende `rain_last_source`-Feld, das nun zusätzlich den Wert `"sensor"` annehmen kann.

2. *Neue Regensensor-Zeile* im Stil der bestehenden Ventil-Zeile (`📡 Terrasse — …`). Ø/Max-Temperatur stammen aus den `rain_measurements` der letzten 24h:

```
🌧 Regen — 3.6 mm gefallen · Ø 20.1 °C, max 26.8 °C · 🔋 voll
```

Offline-Variante:

```
🌧 Regen — ⚠️ Sensor offline (seit 9 h), Fallback auf ERA5
```

**Guss-Unterbrechung** (`WateringCycleInterrupted` → neuer `_on_watering_interrupted`-Handler, Broadcast wie die übrigen `_on_*`-Handler). Verspieltes Regen-Framing wie der Skip, Werte gebündelt wie beim manuellen Stopp:

```
🌧 Regen übernimmt — Guss gestoppt
Terrasse · 4 Min · 2.1 l geflossen · 0.6 mm erkannt
```

**Regen-Benachrichtigung (Flankensteuerung)** — beim Übergang trocken→Regen bzw. Regen→trocken:

```
🌧 Regen erkannt — 1.4 mm
```
```
🌤 Regen vorbei
```

## Test-Entscheidungen (Testing Decisions)

- **Was ein guter Test prüft:** Nur das von außen beobachtbare Verhalten — welche Ereignisse nach einer eingehenden Regenmessung gefeuert werden, ob die Guss-Steuerung das Ventil schließt, welche Datenquelle der Wetter-Dienst-Pfad wählt — nicht die internen Implementierungsdetails.
- **Test-Nahtstelle (Seam):** Der **Ereignis-Kanal (EventBus)** ist die höchste, bereits etablierte Nahtstelle. Tests konstruieren die jeweilige Komponente mit einem `EventBus` und publizieren `RainSensorMeasured` direkt darauf. Es wird **kein** simulierter MQTT-Payload-Roundtrip nachgebaut — das ist sauberer und schneller. Dieses Muster entspricht den bestehenden Tests der Guss-Steuerung und des Watchdogs.
- **Guss-Steuerung:** Tests prüfen, dass ein eingehendes `RainSensorMeasured` mit aktivem Regen alle laufenden Zyklen schließt und `WateringCycleInterrupted` (nicht `WateringCycleStopped`) veröffentlicht — inklusive des Mehr-Ventil-Falls (alle parallel laufenden Zyklen werden gestoppt).
- **Datenbank & Datenbank-Adapter:** Tests prüfen, dass eine Regenmessung korrekt in `rain_measurements` geschrieben wird und die 24h-Summen-Abfrage die erwarteten Werte liefert. Referenz: bestehende Tests des Datenbank-Adapters (`SepticReadingReported`-Pfad).
- **Wetter-Dienst-Pfad:** Tests prüfen die Quellenauswahl — frische Sensordaten → Sensor als Quelle; veraltete/fehlende Sensordaten → ERA5-Fallback. Referenz: bestehende Wetter-Tests.
- **Mittelweg-Pfad (Parsing):** Ein gezielter Test für das Parsen des Sensor-Payloads inklusive der 1/10-°C-Temperatur-Konvertierung und der Berechnung von `is_raining`.
- **Telegram-Benachrichtigung:** Tests prüfen die Flankensteuerung — Benachrichtigung nur beim Regenbeginn, Entwarnung beim Regenende, keine wiederholten Nachrichten bei andauerndem Regen.
- **Watchdog:** Tests prüfen Auslösung des Inaktivitäts-Alarms nach Überschreiten des Offline-Fensters sowie sofortige Entwarnung bei der nächsten Regenmessung. Referenz: `test_watchdog.py`.
- **TDD & Thread-Hygiene:** Rot-Grün-Refaktor pro Einheit. Alle in Produktionscode erzeugten Timer/Threads sind als Daemon zu markieren. Die Coverage darf nicht regredieren.

## Nicht im Leistungsumfang (Out of Scope)

- **Temperatur-basierte Gieß-Mengen:** Die Temperatur des Regensensors als Grundlage für dynamische Volumenlimits ist ein eigenständiges Folge-Feature. Dieses Feature legt nur die Datenbasis (gespeicherte Temperatur).
- **Täglicher Vorhersage-vs-Messung-Vergleich:** Die Auswertung der Vorhersagegenauigkeit anhand von Regensensor- und Wetter-Historie ist ein separates Folge-Feature.
- **Geführte Kopplung des Regensensors** über den Telegram-Bot (analog zur Ventil- oder Kamera-Kopplung). Der Sensor wird über sein konfiguriertes Topic eingebunden; eine Wizard-gestützte Kopplung ist nicht Teil dieses Features.
- **Diagramm-Darstellung** der Regen-Zeitreihe im Chat (nur Textwerte).
- **Modbus IP- und JSON-Webhook-Anbindung** des Sensors — nur der MQTT-Pfad wird unterstützt.

## Weitere Anmerkungen (Further Notes)

- Dieses Feature erweitert die in ADR 0012 definierten Benachrichtigungskanäle und System-Statistiken und baut auf der Ereignis-getriebenen Architektur (ADR 0008) auf.
- Die Quellen-Fallback-Logik knüpft direkt an ADR 0024 (getrennte Behandlung von gemessener Vergangenheit und Vorhersage) an; der Regensensor wird zur neuen bevorzugten Quelle der gemessenen Vergangenheit.
- Neue Domänenbegriffe sind in `CONTEXT.md` ergänzt: **Regensensor**, **Regenmessung**, **Guss-Unterbrechung**.
- Schema-DDL und Ereignis-Signaturen sind in diesem Dokument (Abschnitt Implementierungs-Entscheidungen) sowie in ADR 0028 festgehalten.
