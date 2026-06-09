# Implementation Plan: Inaktivitäts-Watchdog (Systemweite Geräteüberwachung)

Dieser Plan beschreibt den Entwurf und die zu ändernden Dateien für die Implementierung der systemweiten Inaktivitätsüberwachung.

## Design Rules & Decisions

- **Generischer Ansatz:** Jedes zu überwachende Gerät wird als Regel-Objekt definiert. Eine Regel besteht aus:
  - Gerätename (für Benachrichtigungen)
  - Timeout-Schwellenwert (in Stunden)
  - Einer Funktion, die den Zeitstempel der letzten Aktivität aus der DB abfragt
  - Einem Metadaten-Schlüssel für den Alert-Status
- **Spam-Schutz:** Warnungen werden nur einmalig beim Überschreiten gesendet. Sobald wieder Daten eingehen, wird automatisch eine Entwarnung gesendet.
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
- **Hilfsfunktion für Ventil-Aktivität:**
  - `get_latest_device_status_timestamp() -> str`
    Gibt den ISO-Zeitstempel des letzten Eintrags in `device_status_log` zurück.

---

### 3. Watchdog-Hintergrunddienst

#### [MODIFY] [scheduler.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/scheduler.py)
- **Implementierung der Watchdog-Klasse / Logik:**
  - Definition der Regeln für das Ventil und den Füllstandssensor.
  - Eine periodische Funktion `check_devices_activity()`, die z. B. stündlich läuft:
    1. Für jede Regel die Differenz zwischen der aktuellen Uhrzeit und dem letzten Signalzeitpunkt berechnen.
    2. Wenn `Differenz > Schwellenwert` und kein Alert-Flag in `system_metadata` gesetzt ist:
       - Sende Telegram-Warnung: `"⚠️ *Verbindung verloren:* [Gerät] hat seit mehr als [X] Stunden kein Lebenszeichen gesendet."`
       - Setze das Alert-Flag in `system_metadata`.
    3. Wenn `Differenz <= Schwellenwert` und das Alert-Flag in `system_metadata` gesetzt ist (Gerät sendet wieder):
       - Sende Telegram-Entwarnung: `"🟢 *Verbindung wiederhergestellt:* [Gerät] sendet wieder Signale."`
       - Lösche das Alert-Flag in `system_metadata`.

---

## Verification Plan

### Automated Tests
- In `tests/test_watchdog.py` testen wir:
  - Ob die Timeout-Berechnung bei verschiedenen Zeitabständen korrekt anschlägt.
  - Ob die Warnung bei wiederkehrenden Signalen ordnungsgemäß zurückgesetzt wird.
  - Ob die Unterdrückung von Folgealarmen (Spam-Schutz) funktioniert.

### Manual Verification
1. Setze in `.env` ein sehr niedriges Limit (z. B. `WATCHDOG_VALVE_TIMEOUT_HOURS=0.01` für 36 Sekunden).
2. Starte den Daemon und warte, bis die Warnung für das Ventil gesendet wird.
3. Sende einen künstlichen Status-Eintrag für das Ventil oder triggere den Simulator, um zu prüfen, ob die Entwarnung gesendet wird.
