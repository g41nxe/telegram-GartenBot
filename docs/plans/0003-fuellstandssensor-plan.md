# Implementation Plan: Füllstandssensor Klärgrube (Telegram & Daemon Integration)

Dieser Plan beschreibt den Entwurf und die zu ändernden Dateien für die Integration des WLAN-basierten Füllstandssensors in das GartenBot-System.

## Design Rules & Decisions

- **Automatische Kopplung (Auto-Discovery):** Die Registrierung erfolgt beim ersten Eintreffen eines Messsignals über MQTT. Eine einmalige Push-Nachricht informiert den Benutzer darüber.
- **Dynamischer Menü-Button:** Die Schaltfläche `"🛢️ Füllstand Grube"` wird erst nach dem ersten empfangenen Signal dynamisch in der Bot-Tastatur (`get_main_keyboard()`) eingeblendet.
- **Flanken-Triggerung & Hysterese:** Der Bot warnt sofort bei erstmaliger Überschreitung des Grenzwerts (z. B. 80%). Das Flag wird erst gelöscht, wenn der Pegel unter einen Hysteresewert von **75%** sinkt.
- **Trendberechnung:** Der 24h-Trend wird als direkter Prozentvergleich (Differenz zur Messung vor exakt 24 Stunden) berechnet.
- **Konfiguration:** Alle Kalibrierungsparameter (Tiefe leer, Tiefe voll, Alarmschwelle) werden in der `.env` definiert.
- **Decoupled Architecture (ADR-0014):** Der MQTT-Client speichert Füllstände nicht direkt in der Datenbank. Stattdessen wird ein `SepticReadingReported` event gefeuert. Der `DatabaseLoggerAdapter` abonniert das Event, speichert die Daten und löst ggf. Alarm-Schwellenwert-Logik aus.

---

## Proposed Changes

### 1. Konfiguration

#### [MODIFY] [.env](file:///c:/Users/g41nx/Repositories/garden/.env)
Hinzufügen der Parameter zur Kalibrierung und MQTT-Konfiguration:
```env
# --- Füllstandssensor Klärgrube ---
SEPTIC_TANK_MQTT_TOPIC=garden/septic_tank/reading
SEPTIC_TANK_DEPTH_EMPTY_CM=200.0
SEPTIC_TANK_DEPTH_FULL_CM=20.0
SEPTIC_TANK_WARNING_THRESHOLD_PCT=80.0
SEPTIC_TANK_HYSTERESIS_THRESHOLD_PCT=75.0
```

#### [MODIFY] [config.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/config.py)
- Importieren und Validieren der neuen Umgebungsvariablen mit entsprechenden Fallback-Werten.

---

### 2. Datenhaltung (Datenbank)

#### [MODIFY] [database.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/adapters/database.py)
- **Schema-Erweiterung:** In `init_db()` die Tabelle `septic_tank_readings` erstellen:
  - `id INTEGER PRIMARY KEY AUTOINCREMENT`
  - `timestamp TEXT NOT NULL`
  - `distance_cm REAL NOT NULL`
  - `fill_level_percent REAL NOT NULL`
  - `battery_voltage REAL`
- **CRUD-Funktionen:**
  - `log_septic_reading(distance_cm: float, fill_level_percent: float, battery_voltage: float)`
  - `get_latest_septic_reading() -> dict`
  - `get_septic_reading_closest_to(timestamp: str) -> dict` (für Trend-Berechnung)
  - `get_septic_readings_history(limit: int) -> list[dict]`

---

### 3. Event-Klassen & MQTT-Empfänger

#### [NEW] [septic_events.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/core/septic_events.py)
- `SepticReadingReported(Event)` Event-Klasse mit Feldern: `distance_cm`, `fill_level_percent`, `battery_voltage`.

#### [MODIFY] [mqtt_client.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/adapters/mqtt_client.py)
- Abonnieren von `SEPTIC_TANK_MQTT_TOPIC` im Paho-Client-Callback.
- **Empfangs-Logik:**
  - Berechnen des Füllstands in Prozent:
    $$\text{Pegel (\%)} = \frac{\text{Abstand}_{\text{leer}} - \text{Abstand}_{\text{gemessen}}}{\text{Abstand}_{\text{leer}} - \text{Abstand}_{\text{voll}}} \times 100$$
    (begrenzt auf den Bereich $0 - 100\%$).
  - Veröffentlichen des `SepticReadingReported`-Events auf dem EventBus.

---

### 4. Database-Logger & Event-Handling

#### [MODIFY] [database_adapter.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/adapters/database_adapter.py)
- Abonnieren des `SepticReadingReported`-Events.
- **Speicher- und Alarmierungs-Logik:**
  - Speichern des Werts über `database.log_septic_reading`.
  - **Automatische Kopplung & Bestätigung:**
    - Ist das die erste gespeicherte Messung, wird eine Willkommensnachricht gesendet (über ein Event oder UI-Triggersignal).
  - **Alarmierung bei Schwellenwert-Überschreitung:**
    - Steigt der Pegel von unter 80% auf $\ge 80\%$, wird ein Event `SepticWarningTriggered` gefeuert und das Alert-Flag `watchdog_alert_active_septic` in `system_metadata` gesetzt.
    - Sinkt der Pegel unter den Hysteresewert von 75%, wird das Alert-Flag in `system_metadata` gelöscht und ggf. Entwarnung gegeben.

---

### 5. Scheduler

#### [MODIFY] [scheduler.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/scheduler.py)
- **Erweiterung Statusbericht:**
  - Einfügen des aktuellen Füllstands und der Batteriespannung in `generate_daily_report()`, sofern der Sensor gekoppelt ist.

---

### 6. Benutzeroberfläche

#### [MODIFY] [telegram_ui.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/ui/telegram_ui.py)
- **Hauptmenü:**
  - Dynamisches Hinzufügen des Buttons `"🛢️ Füllstand Grube"` in das Reply Keyboard (`get_main_keyboard()`), wenn mindestens ein Eintrag in `septic_tank_readings` vorhanden ist.
- **Befehle:**
  - Implementierung der manuellen Abfrage bei Klick auf den Button oder Eingabe von `/fuellstand`.
  - Berechnen des 24h-Trends durch Differenzbildung zur Messung, die vor 24 Stunden aufgezeichnet wurde.
  - Visualisierung des Pegels (z. B. `[██████░░░░] 60%`) und Anzeige der Details (Batterie, letzte Aktualisierung, 24h-Trend).
- **Statusanzeige:**
  - Integration einer kompakten Zeile zum Füllstand in `handle_status()`, falls der Sensor gekoppelt ist.

---

## Verification Plan

### Automated Tests
- Testen der Füllstandsberechnung bei verschiedenen Rohwerten (Randwerte, Division durch Null, Begrenzung auf 0-100%).
- Simulation von nacheinander eingehenden Werten zur Verifizierung der Flankenerkennung und Hysterese (75%).
- Testen der 24h-Trend-Berechnung mit mockierten Zeitstempeln.

### Manual Verification
1. Senden eines Messwerts via MQTT:
   `mosquitto_pub -h 127.0.0.1 -t garden/septic_tank/reading -m "{\"distance_cm\": 50.0, \"battery_voltage\": 3.95}"`
2. Verifizieren des Datenbank-Eintrags und der automatischen Bestätigungsnachricht im Telegram-Bot sowie das Erscheinen des Buttons `"🛢️ Füllstand Grube"`.
3. Ausführen der manuellen Abfrage über den neuen Menü-Button.
4. Prüfen der Warnung beim Überschreiten des Füllstands (z. B. bei Distanz = 15 cm) und des Rücksetzens beim Absinken unter 75% Hysterese.
5. Simulieren eines Ausfalls (keine Messungen über 18 Stunden) und Verifizieren des Offline-Alarms im Watchdog.
