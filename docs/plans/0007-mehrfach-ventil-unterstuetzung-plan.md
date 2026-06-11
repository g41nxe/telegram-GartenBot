# Implementierungsplan: Multi-Ventil-Unterstützung und flexible Zeitpläne

Wir erweitern das Gartenbewässerungs-System um die Unterstützung mehrerer Ventile. Die Ventile können dynamisch über den Bot registriert, Zeitplänen zugewiesen und manuell oder automatisch (sequentiell/parallel) bewässert werden.

## Proposed Changes

### 1. Datenbank (Database Schema & Migration)
#### [MODIFY] [database.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/adapters/database.py)
* **Tabelle `valves`**: Neu anlegen für die dynamische Ventilregistrierung.
* **Tabelle `schedule_valves`**: Neu anlegen für die n-zu-m Verknüpfung zwischen Zeitplänen und Ventilen.
* **Tabelle `schedules`**: Um die Spalte `execution_mode` (TEXT, standardmäßig `'sequential'`) erweitern.
* **Tabelle `watering_history`**: Um die Spalte `valve_id` (INTEGER) erweitern.
* **Migrationen**:
  * Beim Start prüft `init_db()` das Schema. Wenn die Tabelle `valves` fehlt, erstellen wir sie und legen ein Standard-Eintrag (`id=1`, `name="garden_valve"`, `mqtt_name="garden_valve"`, `is_paired=1`) an, um Abwärtskompatibilität zu wahren.
  * Bestehende Zeitpläne in `schedules` werden über `schedule_valves` mit dem Standard-Ventil (`valve_id=1`) verknüpft.
  * Bestehende Einträge in `watering_history` werden auf `valve_id=1` gesetzt.

### 2. MQTT-Client (Adapter-Ebene)
#### [MODIFY] [mqtt_client.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/adapters/mqtt_client.py)
* Der MQTT-Client verwaltet den Status aller Ventile in einem Dictionary `valves_status: Dict[str, Dict[str, Any]]` anstelle des einzelnen globalen `valve_status`.
* Beim Verbindungsaufbau liest der Client alle registrierten Ventile aus der Datenbank und abonniert deren individuelle Topics (z. B. `zigbee2mqtt/valve_<ieee_address>`).
* Die API `open_valve(valve_name)` und `close_valve(valve_name)` nimmt nun den Topic-Namen des Ventils entgegen.

### 3. Guss-Steuerung (Watering Controller & Events)
#### [MODIFY] [watering_controller.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/core/watering_controller.py)
* Der `WateringController` verwaltet ein Dictionary aktiver Guss-Zyklen `_active_cycles` (indiziert nach `valve_id` bzw. `mqtt_name`).
* Der Controller wird um die Fähigkeit erweitert, sequentielle Güsse (eine Warteschlange von Ventilen) oder parallele Güsse (mehrere Ventile gleichzeitig mit individuellen Grenzwerten) zu steuern.
* Domain-Events (`WateringCycleStarted`, `WateringCycleCompleted`, etc.) werden um ein `valve_id` (oder `valve_name`) Feld ergänzt, damit Benachrichtigungen ventilgenau erfolgen.

### 4. Scheduler (Zeitsteuerung)
#### [MODIFY] [scheduler.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/scheduler.py)
* Liest bei Auslösung eines Zeitplans die zugewiesenen Ventile aus `schedule_valves` aus.
* Startet den Guss über den Controller im konfigurierten `execution_mode` (sequentiell oder parallel).
* Der tägliche Statusbericht weckt vorab alle Ventile per MQTT auf und listet deren LQI, Batteriestände und Fehlermeldungen einzeln auf.

### 5. Telegram-Bot Benutzeroberfläche
#### [MODIFY] [telegram_ui.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/ui/telegram_ui.py)
* **Kopplungs-Assistent (`/setup`)**: Fragt vor der Kopplung nach dem Wunschnamen des Ventils, startet dann die Suche und registriert das Ventil dynamisch.
* **Zeitplan-Assistent (`/zeitplan`)**:
  * Schritt 1-5 wie bisher (Name, Zeit, Dauer, Volumen).
  * Neuer Schritt 6a: Auswahl der Ventile via Multi-Select Inline-Keyboard. *Wird übersprungen, falls nur 1 Ventil existiert.*
  * Neuer Schritt 6b: Auswahl des Ausführungsmodus (sequentiell/parallel), falls mehr als ein Ventil gewählt wurde. *Wird übersprungen, falls nur 1 Ventil existiert.*
* **Manueller Start (`🟢 Bewässern starten`)**: Erlaubt ebenfalls Multi-Select von Ventilen sowie die Auswahl des Ausführungsmodus. *Wird übersprungen, falls nur 1 Ventil existiert (vorausgewählt).*
* **Statusanzeige (`/status`)**: Listet den Zustand aller registrierten Ventile einzeln auf.

## Verification Plan

### Automated Tests
* Wir erweitern die Testsuite in `tests/test_irrigation.py` um Tests für:
  * Datenbank-Schema-Migration und CRUD-Aktivitäten mit mehreren Ventilen.
  * Sequentielle und parallele Bewässerung über den `WateringController`.
  * Einhaltung individueller Limits im parallelen Guss.
  * Korrektes und fehlerfreies Verhalten der Anwendung, wenn nur ein einziges Ventil registriert ist.

### Manual Verification
* Simulierte Ausführung des Telegram-Bot-Dialogs zur Erstellung eines Multi-Ventil-Zeitplans.
* Validierung des Verhaltens im Ein-Ventil-Modus (keine zusätzlichen Abfragen).
* Validierung des Statusberichts per `/status` und `/report`.

