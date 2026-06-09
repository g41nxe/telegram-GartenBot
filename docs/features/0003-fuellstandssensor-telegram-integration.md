# Feature: Füllstandssensor Klärgrube (Telegram & Daemon Integration)

## Problemstellung (Problem Statement)

Die von dem Klärgruben-Sensor gesendeten Messdaten müssen vom zentralen GartenBot-Daemon empfangen, kalibriert und ausgewertet werden. Der Benutzer benötigt eine einfache Möglichkeit, den aktuellen Füllstand mobil abzufragen, und muss aktiv benachrichtigt werden, sobald die Grube vollzulaufen droht. Zudem soll der Zustand Teil der täglichen Statusberichte sein.

## Lösung (Solution)

Der GartenBot-Daemon abonniert das MQTT-Topic des Füllstandssensors. Bei Eingang neuer Messdaten (Distanz in cm) berechnet der Daemon unter Verwendung konfigurierter Kalibrierungs-Grenzwerte den prozentualen Füllstand und speichert diesen in der SQLite-Datenbank.

Wir implementieren folgende Kommunikationswege:
1. **Sofort-Warnung:** Überschreitet der Füllstand erstmals einen kritischen Schwellenwert (z. B. 80%), sendet der Bot sofort eine Push-Nachricht an alle autorisierten Telegram-Benutzer.
2. **Täglicher Statusbericht:** Der Füllstand wird in den automatischen täglichen Report (08:00 Uhr) als separate Zeile inklusive einer eventuellen Warnung integriert.
3. **Manuelle Abfrage:** Im Telegram-Hauptmenü wird ein Button `"🛢️ Füllstand Grube"` eingeführt, der zusammen mit dem Befehl `/fuellstand` den aktuellen Pegel grafisch als Ladebalken, den Trend der letzten 24 Stunden sowie die Sensor-Batteriespannung darstellt.

## User Stories

1. Als Benutzer des Telegram-Bots möchte ich über einen Menü-Button den aktuellen Füllstand abrufen können, um schnell zu sehen, wie voll die Grube ist.
2. Als Benutzer des Telegram-Bots möchte ich sofort benachrichtigt werden, wenn der Füllstand 80% überschreitet, damit ich rechtzeitig einen Entleerungstermin vereinbaren kann.
3. Als Benutzer möchte ich nicht bei jeder Messung mit der gleichen Warnung bombardiert werden, sondern nur bei erstmaliger Überschreitung und als Teil meines täglichen Reports.
4. Als Benutzer möchte ich im täglichen Statusbericht den Füllstand sehen, um ein Gefühl für den täglichen Anstieg zu bekommen.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Kalibrierungs-Logik:** Die Berechnung von Prozent und Rest-Volumen erfolgt dynamisch im Daemon basierend auf Umgebungsvariablen.
- **Datenbankschema:** Eine neue Tabelle `septic_tank_readings` speichert Zeitstempel, Rohdistanz, berechneten Füllstand und Batteriespannung.
- **MQTT-Handler:** Integration des neuen Topics in die bestehende MQTT-Bridge. Der Handler stößt die Berechnung, Speicherung und Alarmprüfung an.
- **Alarmierungs-Zustand:** Um wiederholte Alarme zu vermeiden, wird der Sendezustand (Flankensteuerung) persistent in `system_metadata` abgelegt. Erst wenn der Füllstand wieder unter einen bestimmten Hysteresewert sinkt, wird der Alarm zurückgesetzt.
- **Zustand & Automatische Kopplung:** Im Gegensatz zum Zigbee-Ventil ist für den WLAN-basierten Füllstandssensor kein physischer Kopplungsprozess (Pairing) nötig. Die Kopplung erfolgt automatisch: Sobald der Daemon die erste MQTT-Nachricht auf dem Topic empfängt, wird der Sensor als aktiv registriert. Bei diesem allerersten Signal sendet der Bot eine einmalige Bestätigungsnachricht an alle autorisierten Benutzer. Im Status-Menü wird ab diesem Zeitpunkt der Füllstand sowie das Datum/Uhrzeit der letzten Messung angezeigt.
- **Benutzeroberfläche:** 
  - Neue Schaltfläche im Telegram-Hauptmenü: `"🛢️ Füllstand Grube"`.
  - Implementierung des `/fuellstand` Textbefehls.
  - Visualisierung des Füllstands mit Unicode-Zeichen (z.B. `[██████░░░░] 60%`).

## Test-Entscheidungen (Testing Decisions)

- **Unit-Tests für Berechnungen:** Wir testen die Formeln zur Umrechnung von Distanz in Füllstand (inklusive Randfälle wie extreme Sensorfehler).
- **Integrationstests für MQTT & Alarmierung:** Mocken des MQTT-Clients und Testen der gesamten Kette: Empfang von 50cm (OK) -> Empfang von 15cm (Alarm ausgelöst) -> Empfang von 12cm (kein doppelter Alarm).
- **Test-Nahtstelle (Seam):** Die Tests klinken sich am Event-Bus des Daemons ein, um zu prüfen, ob die richtigen Ereignisse nach Empfang der MQTT-Nachrichten gefeuert werden.

## Nicht im Leistungsumfang (Out of Scope)

- Steuerung einer Pumpe zur automatischen Entleerung.
- Verlaufsgrafiken (Diagramme) direkt im Chat-Bildschirm (nur Textdarstellung und Ladebalken).

## Weitere Anmerkungen (Further Notes)

- Dieses Feature erweitert die bestehenden Benachrichtigungskanäle und die System-Statistiken, die in ADR 0012 definiert wurden.
