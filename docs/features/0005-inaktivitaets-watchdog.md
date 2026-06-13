# Feature: Inaktivitäts-Watchdog (Ventil-Überwachung)

## Problemstellung (Problem Statement)

Batteriebetriebene Bewässerungsventile können unbemerkt ausfallen. Mögliche Ursachen sind leere Batterien, Verbindungsabbrüche (Zigbee) oder physische Störungen. Ein unbemerkter Ausfall führt zu ausbleibender Bewässerung im Garten.

Da das System mehrere Ventile unterstützen kann, wird eine einheitliche Lösung benötigt, die alle registrierten Ventile überwacht und proaktiv alarmiert, wenn ein Ventil über einen konfigurierten Zeitraum kein Lebenszeichen gesendet hat.

## Lösung (Solution)

Wir implementieren einen **Inaktivitäts-Watchdog** im Bewässerungs-Daemon als eigenes Adapter-Modul (`adapters/watchdog.py`). Dieses Modul führt stündlich eine Aktivitätsprüfung aller registrierten Ventile durch und reagiert sofort auf Entwarnungssignale.

Überschreitet die Zeit seit dem letzten Lebenszeichen eines Ventils (Feld `last_update` in der Tabelle `valves`) den konfigurierten Schwellenwert, publiziert der Watchdog ein `InactivityAlertTriggered`-Event auf dem Ereignis-Kanal. Der Telegram-Bot fängt dieses Event ab und benachrichtigt alle autorisierten Benutzer per Push-Nachricht.

**Unterstützte Geräte in diesem Feature:**
- **Ventile (Sonoff Hydro ONE):** Alle in der Datenbank (`valves`) registrierten Ventile, geprüft anhand des Feldes `last_update`. Standard-Timeout: 24 Stunden.

## User Stories

1. Als Betreiber des GartenBots möchte ich sofort benachrichtigt werden, wenn eines meiner Ventile offline geht, unter Angabe seines Wunschnamens (z. B. "Rasen"), um Ausfälle frühzeitig zu beheben.
2. Als Betreiber möchte ich eine Entwarnung erhalten, sobald das betroffene Ventil wieder ein Signal sendet (unter Angabe des Wunschnamens), damit ich weiß, dass das Problem gelöst ist.
3. Als Betreiber möchte ich nicht wiederholt mit der gleichen Warnung benachrichtigt werden, solange das Problem andauert.
4. Als Betreiber möchte ich im täglichen Statusbericht sehen, ob aktuell ein Ventil als inaktiv markiert ist.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Neues Modul `adapters/watchdog.py`:**
  - Enthält die Funktion `run_watchdog_check()`, die stündlich vom Scheduler in einem eigenen Thread aufgerufen wird (Muster: analog zur Wetter-Hintergrundabfrage in `scheduler.py`).
  - Enthält eine `initialize(event_bus)`-Funktion, die beim Daemon-Start einmalig aufgerufen wird und die dauerhaften Ereignis-Kanal-Abonnements registriert.
  - Das Modul selbst ist zustandslos — der gesamte persistente Zustand liegt in `system_metadata`.

- **Neue Event-Typen in `core/watchdog_events.py`:**
  - `InactivityAlertTriggered(device_name: str, valve_id: int, hours_silent: float, timeout_hours: int)`
  - `InactivityAlertResolved(device_name: str, valve_id: int)`
  - Platzierung in `core/` folgt dem Muster von `core/valve_events.py`, damit `telegram_ui.py` ohne Adapter-Import abonnieren kann.

- **Konfiguration:**
  - `WATCHDOG_ENABLED=true` — globaler Schalter; bei `false` registriert `initialize()` keine Abonnements und `run_watchdog_check()` kehrt sofort zurück.
  - `WATCHDOG_VALVE_TIMEOUT_HOURS=24` — konfigurierbares Timeout pro Ventil.

- **Hintergrund-Task (stündliche Prüfung):**
  - Der Scheduler (`scheduler.py`) nutzt denselben `last_check`-Guard wie die Wetter-Hintergrundabfrage (`time.time()`-Vergleich).
  - `run_watchdog_check()` wird in einem Daemon-Thread gestartet, damit HTTP-Aufrufe der Telegram-Benachrichtigungen den Scheduler-Loop nicht blockieren.

- **Verhalten bei `last_update IS NULL`:**
  - Ventile ohne bisher empfangenes Signal werden übersprungen. Die Überwachung beginnt erst nach dem ersten empfangenen MQTT-Signal.

- **Warnzustand & Spam-Schutz:**
  - Der Sendezustand wird in `system_metadata` hinterlegt: `watchdog_alert_active_valve_<id> = "1"`.
  - Ist das Flag gesetzt, wird bei der nächsten Prüfung keine erneute Warnung gesendet.
  - Das Flag wird gelöscht, sobald das Ventil wieder ein Signal sendet (siehe Entwarnung).

- **Sofortige Entwarnung via Ereignis-Kanal:**
  - `watchdog.py` abonniert `ValveStatusReported` dauerhaft auf Modulebene (ADR-0016 konform: kein `unsubscribe()` nötig).
  - Sobald ein `ValveStatusReported`-Event eintrifft, prüft der Handler, ob `watchdog_alert_active_valve_<id>` gesetzt ist. Falls ja: Flag löschen, `InactivityAlertResolved` publizieren.
  - Dies stellt sicher, dass die Entwarnung sofort erfolgt — nicht erst beim nächsten stündlichen Check.

- **Täglicher Statusbericht:**
  - Der Tagesbericht liest alle aktiven `watchdog_alert_active_valve_*`-Schlüssel aus `system_metadata` und fügt für jedes betroffene Ventil eine Warnzeile ein (Ventil-Wunschname + Angabe der Funkstille).

- **Entkoppelte Alarmierung:**
  - `watchdog.py` erzeugt ausschließlich Events. Die Formatierung und der Versand der Telegram-Nachrichten erfolgt in `telegram_ui.py`.

## Test-Entscheidungen (Testing Decisions)

- **Unit-Tests für die Timeout-Erkennung:**
  - Testen von `run_watchdog_check()` mit kontrollierten Zeitstempeln in der Testdatenbank.
  - Validierung: korrektes Event bei Überschreitung, kein doppeltes Event bei gesetztem Flag, Überspringen bei `last_update IS NULL`.
- **Integrationstests für Entwarnung:**
  - Simulieren einer Ventil-Funkstille (Flag setzen), dann `ValveStatusReported`-Event publizieren und prüfen, ob `InactivityAlertResolved` gefeuert und das Flag gelöscht wird.
- **Test-Nahtstelle:** Alle Tests klinken sich am Ereignis-Kanal ein und verifizieren publizierte Events.

## Nicht im Leistungsumfang (Out of Scope)

- Überwachung des Füllstandssensors (Klärgrube) — wird in Feature 0003 nachgezogen, sobald der Sensor implementiert ist.
- Pingen von Netzwerkgeräten (wie dem Raspberry Pi selbst).
- Automatische Behebung der Störungen.
