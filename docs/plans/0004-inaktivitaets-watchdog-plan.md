# Implementation Plan: Inaktivitäts-Watchdog (Systemweite Geräteüberwachung)

Dieser Plan beschreibt den Entwurf und die zu ändernden Dateien für die Implementierung der systemweiten Inaktivitätsüberwachung, angepasst an die Unterstützung mehrerer Ventile.

## Design Rules & Decisions

- **Generischer Ansatz:** Jedes zu überwachende Gerät wird als Regel-Objekt definiert. Eine Regel besteht aus:
  - Gerätekennung / Name (für Benachrichtigungen und Metadaten)
  - Timeout-Schwellenwert (in Stunden)
  - Einer Funktion, die den Zeitstempel der letzten Aktivität aus der DB abfragt
  - Einem Metadaten-Schlüssel für den Alert-Status
- **Dynamische Ventilprüfung (Multi-Valve):** Der Watchdog liest alle gekoppelten Ventile aus der Datenbank aus und wendet die Überwachungsregel dynamisch auf jedes einzelne Ventil an.
- **Spam-Schutz & DB-IDs:** Warnungen werden nur einmalig beim Überschreiten gesendet. Die Alert-Schlüssel in `system_metadata` nutzen die Datenbank-ID des Ventils (z. B. `watchdog_alert_active_valve_<id>`), um Namenskollisionen zu vermeiden.
- **Wunschnamen in Nachrichten:** In den Benachrichtigungen an den Benutzer wird ausschließlich der benutzerdefinierte Wunschname des Ventils (z. B. "Rasen") verwendet.
- **Konfigurierbarkeit:** Schwellenwerte für die Timeouts werden als Stunden-Werte in der `.env` hinterlegt.
- **Architekturentkopplung (ADR-0014):** Der Watchdog sendet keine Nachrichten direkt über den Telegram-Bot. Stattdessen publiziert er bei Inaktivität oder Reaktivierung Events wie `InactivityAlertTriggered` und `InactivityAlertResolved` auf dem EventBus. Der Telegram-Bot-Adapter abonniert diese Events und übernimmt den eigentlichen Nachrichtenversand.

---

## Proposed Changes

### 1. Konfiguration

#### [MODIFY] [.env](file:///c:/Users/g41nx/Repositories/garden/.env)
Hinzufügen der Parameter für die Inaktivitätsüberwachung:
```env
# --- Inaktivitäts-Watchdog ---
WATCHDOG_ENABLED=true
WATCHDOG_VALVE_TIMEOUT_HOURS=24.0
WATCHDOG_SEPTIC_TIMEOUT_HOWERS=18.0
```

#### [MODIFY] [config.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/config.py)
- Importieren der neuen Watchdog-Konfigurationswerte mit passenden Standardwerten.

---

### 2. Datenhaltung & Hilfsfunktionen

#### [MODIFY] [database.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/adapters/database.py)
- **Aktivitätsabfrage für Ventile:**
  - `get_valve_last_update(valve_id: int) -> str`
    Gibt den ISO-Zeitstempel des letzten Signals (`last_update`) für ein bestimmtes Ventil aus der `valves`-Tabelle zurück.
- **Aktivitätsabfrage für Füllstandssensor:**
  - `get_septic_sensor_last_update() -> str`
    Gibt den ISO-Zeitstempel der letzten empfangenen Füllstandsmeldung zurück.
- **Isolierter Gerätestatus (Multi-Valve):**
  - Schema-Erweiterung für `device_status_log` um die Spalte `device_name` (oder `valve_id`).
  - Anpassen von `log_device_status(device_name: str, battery: int, linkquality: int)`.
  - Anpassen der 24h-Statistikabfragen per Gerät.

---

### 3. Event-Klassen & Watchdog-Hintergrunddienst

#### [NEW] [watchdog_events.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/core/watchdog_events.py)
- `InactivityAlertTriggered(Event)` mit Feldern: `device_name`, `hours_inactive`.
- `InactivityAlertResolved(Event)` mit Feld: `device_name`.

#### [MODIFY] [scheduler.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/scheduler.py)
- Periodische Funktion `check_devices_activity()`, die z. B. stündlich läuft:
  1. Liest alle gekoppelten Ventile aus der Datenbank und wendet die Timeout-Prüfung an.
  2. Liest die Aktivität des Füllstandssensors.
  3. Falls `Differenz > Schwellenwert` und kein Alert-Flag gesetzt ist:
     - Publiziert `InactivityAlertTriggered(device_name, threshold_hours)`.
     - Setzt das Alert-Flag in `system_metadata`.
  4. Falls `Differenz <= Schwellenwert` und das Alert-Flag gesetzt ist:
     - Publiziert `InactivityAlertResolved(device_name)`.
     - Löscht das Alert-Flag.

---

### 4. Präsentationsschicht (Telegram-Bot)

#### [MODIFY] [telegram_ui.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/ui/telegram_ui.py)
- Registrieren von Event-Handlern für `InactivityAlertTriggered` und `InactivityAlertResolved`.
- Beim Auslösen formatiert und versendet der Bot die Nachrichten:
  - Warnung: `"⚠️ *Verbindung verloren:* Das Gerät '[Wunschname]' hat seit mehr als [X] Stunden kein Lebenszeichen gesendet."`
  - Entwarnung: `"🟢 *Verbindung wiederhergestellt:* Das Gerät '[Wunschname]' sendet wieder Signale."`

---

## Verification Plan

### Automated Tests
- In `tests/test_watchdog.py` testen wir:
  - Korrektes Auslösen der Events bei Grenzwertüberschreitung.
  - Sendeunterdrückung (Spam-Schutz) per persistentem Flag.
  - Event-Veröffentlichung bei Reaktivierung.
  - Verhalten bei mehreren registrierten Ventilen.

### Manual Verification
1. Setze in `.env` ein sehr niedriges Limit (z. B. `WATCHDOG_VALVE_TIMEOUT_HOURS=0.01` für 36 Sekunden).
2. Starte den Daemon und warte, bis das `InactivityAlertTriggered`-Event gefeuert und als Telegram-Warnung zugestellt wird.
3. Sende einen künstlichen Status-Eintrag für das Ventil, um das `InactivityAlertResolved`-Event und die Entwarnung zu verifizieren.
