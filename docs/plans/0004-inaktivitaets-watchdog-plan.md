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

---

## Proposed Changes

### 1. Konfiguration

#### [MODIFY] [.env](file:///d:/Projects/Repositories/telegram-GartenBot/.env)
Hinzufügen der Parameter für die Inaktivitätsüberwachung:
```env
# --- Inaktivitäts-Watchdog ---
WATCHDOG_ENABLED=true
WATCHDOG_VALVE_TIMEOUT_HOURS=24.0
WATCHDOG_SEPTIC_TIMEOUT_HOURS=18.0
```

#### [MODIFY] [config.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/config.py)
- Importieren der neuen Watchdog-Konfigurationswerte mit passenden Standardwerten.

---

### 2. Datenhaltung & Hilfsfunktionen

#### [MODIFY] [database.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/adapters/database.py)
- **Aktivitätsabfrage für Ventile:**
  - `get_valve_last_update(valve_id: int) -> str`
    Gibt den ISO-Zeitstempel des letzten Signals (`last_update`) für ein bestimmtes Ventil aus der `valves`-Tabelle zurück.
- **Aktivitätsabfrage für Füllstandssensor:**
  - `get_septic_sensor_last_update() -> str`
    Gibt den ISO-Zeitstempel der letzten empfangenen Füllstandsmeldung zurück.

---

### 3. Watchdog-Hintergrunddienst

#### [MODIFY] [scheduler.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/scheduler.py)
- **Implementierung der Watchdog-Klasse / Logik:**
  - Definition der generischen Watchdog-Regeln.
  - Eine periodische Funktion `check_devices_activity()`, die z. B. stündlich läuft:
    1. Liest alle gekoppelten Ventile aus der Datenbank und erzeugt dynamisch eine Regel pro Ventil.
    2. Liest den Füllstandssensor-Zustand.
    3. Für jedes Gerät die Differenz zwischen der aktuellen Uhrzeit und dem letzten Signalzeitpunkt berechnen.
    4. Wenn `Differenz > Schwellenwert` und kein Alert-Flag in `system_metadata` gesetzt ist:
       - Sende Telegram-Warnung: `"⚠️ *Verbindung verloren:* Das Gerät '[Wunschname]' hat seit mehr als [X] Stunden kein Lebenszeichen gesendet."`
       - Setze das Alert-Flag in `system_metadata` auf `watchdog_alert_active_valve_<id> = 1` bzw. `watchdog_alert_active_septic = 1`.
    5. Wenn `Differenz <= Schwellenwert` und das Alert-Flag gesetzt ist:
       - Sende Telegram-Entwarnung: `"🟢 *Verbindung wiederhergestellt:* Das Gerät '[Wunschname]' sendet wieder Signale."`
       - Lösche das Alert-Flag.

---

## Verification Plan

### Automated Tests
- In `tests/test_watchdog.py` testen wir:
  - Ob die Timeout-Berechnung bei verschiedenen Zeitabständen korrekt anschlägt.
  - Ob die Warnung bei wiederkehrenden Signalen ordnungsgemäß zurückgesetzt wird.
  - Ob die Unterdrückung von Folgealarmen (Spam-Schutz) funktioniert.
  - Das Verhalten bei mehreren registrierten Ventilen unter Verwendung von `watchdog_alert_active_valve_<id>`.

### Manual Verification
1. Setze in `.env` ein sehr niedriges Limit (z. B. `WATCHDOG_VALVE_TIMEOUT_HOURS=0.01` für 36 Sekunden).
2. Starte den Daemon und warte, bis die Warnung für das Ventil gesendet wird.
3. Sende einen künstlichen Status-Eintrag für das Ventil oder triggere den Simulator, um zu prüfen, ob die Entwarnung gesendet wird.
