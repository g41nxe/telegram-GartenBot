# Implementation Plan: Füllstandssensor Klärgrube (Telegram & Daemon Integration)

Dieser Plan beschreibt den Entwurf und die zu ändernden Dateien für die Integration des WLAN-basierten Füllstandssensors in das GartenBot-System.

## Design Rules & Decisions

- **Automatische Kopplung (Auto-Discovery):** Die Registrierung erfolgt beim ersten Eintreffen eines Messsignals über MQTT. Eine einmalige Push-Nachricht informiert den Benutzer darüber.
- **Flanken-Triggerung für Warnungen:** Der Bot warnt sofort bei erstmaliger Überschreitung des Grenzwerts (z. B. 80%). Folge-Messungen über dem Grenzwert senden keinen neuen Alarm, um Spam zu verhindern.
- **Inaktivitäts-Watchdog:** Wenn für mehr als 18 Stunden keine neuen Daten eintreffen, sendet das System eine Fehlermeldung per Telegram, um Ausfälle des Sensors (z. B. leere Batterie) abzufangen.
- **Konfiguration:** Alle Kalibrierungsparameter (Tiefe leer, Tiefe voll, Alarmschwelle) werden in der `.env` definiert, damit der Sensor-Code selbst unberührt bleiben kann.

---

## Proposed Changes

### 1. Konfiguration

#### [MODIFY] [.env](file:///d:/Projects/Repositories/telegram-GartenBot/.env)
Hinzufügen der Parameter zur Kalibrierung und MQTT-Konfiguration:
```env
# --- Füllstandssensor Klärgrube ---
SEPTIC_TANK_MQTT_TOPIC=garden/septic_tank/reading
SEPTIC_TANK_DEPTH_EMPTY_CM=200.0
SEPTIC_TANK_DEPTH_FULL_CM=20.0
SEPTIC_TANK_WARNING_THRESHOLD_PCT=80.0
```

#### [MODIFY] [config.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/config.py)
- Importieren und Validieren der neuen Umgebungsvariablen mit entsprechenden Fallback-Werten.

---

### 2. Datenhaltung (Datenbank)

#### [MODIFY] [database.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/adapters/database.py)
- **Schema-Erweiterung:** In `init_db()` die Tabelle `septic_tank_readings` erstellen:
  - `id INTEGER PRIMARY KEY AUTOINCREMENT`
  - `timestamp TEXT NOT NULL`
  - `distance_cm REAL NOT NULL`
  - `fill_level_percent REAL NOT NULL`
  - `battery_voltage REAL`
- **CRUD-Funktionen:**
  - `log_septic_reading(distance_cm: float, fill_level_percent: float, battery_voltage: float)`
  - `get_latest_septic_reading() -> dict`
  - `get_septic_readings_history(limit: int) -> list[dict]`

---

### 3. MQTT-Empfänger & Warnlogik

#### [MODIFY] [mqtt_client.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/adapters/mqtt_client.py)
- Abonnieren von `SEPTIC_TANK_MQTT_TOPIC` im Paho-Client-Callback.
- **Empfangs-Logik:**
  - Berechnen des Füllstands in Prozent:
    $$\text{Pegel (\%)} = \frac{\text{Abstand}_{\text{leer}} - \text{Abstand}_{\text{gemessen}}}{\text{Abstand}_{\text{leer}} - \text{Abstand}_{\text{voll}}} \times 100$$
    (begrenzt auf den Bereich $0 - 100\%$).
  - Speichern des Werts über `database.log_septic_reading`.
- **Automatische Kopplung & Bestätigung:**
  - Ist das die erste gespeicherte Messung, wird eine Willkommensnachricht gesendet.
- **Alarmierung bei Schwellenwert-Überschreitung:**
  - Laden des vorherigen Pegels.
  - Steigt der Pegel von unter 80% auf $\ge 80\%$, wird eine Warnmeldung abgesetzt und ein Alert-Flag in `system_metadata` gesetzt.
  - Sinkt der Pegel unter 80% (mit Hystereseschutz, z. B. unter 78%), wird das Alert-Flag in `system_metadata` zurückgesetzt.

---

### 4. Scheduler & Watchdog

#### [MODIFY] [scheduler.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/scheduler.py)
- **Watchdog-Task:** 
  - Eine regelmäßige Prüfung (z. B. stündlich) vergleicht das aktuelle Datum/Uhrzeit mit dem Zeitstempel der letzten Messung in `septic_tank_readings`.
  - Liegt das letzte Signal länger als 18 Stunden zurück, wird eine Warnung ("Sensor offline") gesendet und `septic_tank_offline_alert_sent = 1` in `system_metadata` markiert.
  - Sobald ein neuer Messwert eintrifft, wird die Warnung in `system_metadata` gelöscht.
- **Erweiterung Statusbericht:**
  - Einfügen des aktuellen Füllstands und der Batteriespannung in `generate_daily_report()`.

---

### 5. Benutzeroberfläche

#### [MODIFY] [telegram_ui.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/ui/telegram_ui.py)
- **Hauptmenü:**
  - Hinzufügen des Buttons `"🛢️ Füllstand Grube"` in das Reply Keyboard (`get_main_keyboard()`).
- **Befehle:**
  - Implementierung der manuellen Abfrage bei Klick auf den Button oder Eingabe von `/fuellstand`.
  - Visualisierung des Pegels (z. B. `[██████░░░░] 60%`) und Anzeige der Details (Batterie, letzte Aktualisierung, 24h-Trend).
- **Statusanzeige:**
  - Integration einer kompakten Zeile zum Füllstand in `handle_status()`.

---

## Verification Plan

### Automated Tests
- Testen der Füllstandsberechnung bei verschiedenen Rohwerten (Randwerte, Division durch Null, Begrenzung auf 0-100%).
- Simulation von nacheinander eingehenden Werten zur Verifizierung der Flankenerkennung und des Watchdogs.

### Manual Verification
1. Senden eines Messwerts via MQTT:
   `mosquitto_pub -h 127.0.0.1 -t garden/septic_tank/reading -m "{\"distance_cm\": 50.0, \"battery_voltage\": 3.95}"`
2. Verifizieren des Datenbank-Eintrags und der automatischen Bestätigungsnachricht im Telegram-Bot.
3. Ausführen der manuellen Abfrage über den neuen Menü-Button.
4. Prüfen der Warnung beim Überschreiten des Füllstands (z. B. bei Distanz = 15 cm).
5. Simulieren eines Ausfalls (keine Messungen über 18 Stunden) und Verifizieren des Offline-Alarms.
