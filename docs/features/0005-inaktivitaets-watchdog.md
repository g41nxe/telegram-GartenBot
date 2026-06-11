# Feature: Inaktivitäts-Watchdog (Systemweite Geräteüberwachung)

## Problemstellung (Problem Statement)

Batteriebetriebene Smart-Home-Komponenten (wie Bewässerungsventile oder Füllstandssoren) können unbemerkt ausfallen. Mögliche Ursachen sind leere Batterien, Verbindungsabbrüche (WLAN oder Zigbee) oder physische Störungen. Ein unbemerkter Ausfall kann kritische Folgen haben (z. B. unbemerkte Überläufe der Klärgrube oder ausbleibende Bewässerung im Garten). 

Da das System mehrere Ventile unterstützen kann, wird eine einheitliche, systemweite Lösung benötigt, die alle verbundenen Ventile sowie den Füllstandssensor überwacht und proaktiv alarmiert, wenn eine Komponente über einen längeren Zeitraum kein Lebenszeichen gesendet hat.

## Lösung (Solution)

Wir implementieren einen **Inaktivitäts-Watchdog** im Bewässerungs-Daemon. Dieser Dienst läuft als periodischer Hintergrund-Task (stündlich) und überwacht die Aktivitäts-Zeitstempel aller registrierten Hardware-Komponenten. 

Für jeden Gerätetyp wird in der Konfiguration (`.env`) ein individuelles Timeout-Intervall definiert. Überschreitet die Zeit seit dem letzten Lebenszeichen (dem letzten Signalzeitpunkt in der DB) den konfigurierten Schwellenwert, publiziert der Watchdog ein Alarm-Event (`InactivityAlertTriggered`) auf dem systemweiten `EventBus`. Der Telegram-Bot fängt dieses Event ab und benachrichtigt alle angemeldeten Benutzer per Push-Nachricht.

Unterstützte Geräte:
1. **Ventile (Sonoff Hydro ONE):** Dynamische Prüfung aller in der Datenbank (`valves`) registrierten Ventile anhand des Feldes `last_update`. Standard-Timeout: 24 Stunden.
2. **Füllstandssensor (Klärgrube):** Auswertung des Zeitstempels der letzten Füllstandsmeldung. Standard-Timeout: 18 Stunden.

## User Stories

1. Als Betreiber des GartenBots möchte ich sofort benachrichtigt werden, wenn eines meiner Ventile offline geht, unter Angabe seines Wunschnamens (z. B. "Rasen"), um Ausfälle frühzeitig zu beheben.
2. Als Betreiber möchte ich für jedes Gerät ein eigenes Zeit-Timeout festlegen können, da manche Geräte häufiger senden (Ventile bei Aktivität) und manche seltener (Füllstandssensor 2x täglich).
3. Als Betreiber möchte ich eine Entwarnung erhalten, sobald das betroffene Gerät wieder ein Signal sendet (unter Angabe des Wunschnamens), damit ich weiß, dass das Problem gelöst ist.
4. Als Entwickler möchte ich ein generisches System haben, bei dem neue Gerätetypen (z. B. Bodenfeuchtesensoren) mit minimalem Aufwand in die Überwachung integriert werden können.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Konfiguration:**
  - Jedes Gerät hat ein eigenes Limit in Stunden (z. B. `WATCHDOG_VALVE_TIMEOUT_HOURS=24` und `WATCHDOG_SEPTIC_TIMEOUT_HOURS=18`).
  - Ein globaler Schalter `WATCHDOG_ENABLED=true` erlaubt das Deaktivieren.
- **Hintergrund-Task & Throttling:**
  - Ein periodischer Task im `scheduler.py` führt stündlich die Aktivitätsprüfungen aus.
- **Isolierung der Status-Logs:**
  - Die Datenbanktabelle `device_status_log` wird um die Spalte `device_name` erweitert. Dies erlaubt die separate Berechnung der Funkstille und LQI pro Gerät statt eines vermischten globalen Durchschnitts.
- **Warnzustand & Entwarnung (Spam-Schutz):**
  - Der Sendezustand einer Warnung wird in `system_metadata` hinterlegt.
  - Für Ventile wird das Flag anhand der Datenbank-ID benannt: `watchdog_alert_active_valve_<id> = 1`.
  - Für den Füllstandssensor lautet das Flag: `watchdog_alert_active_septic = 1`.
  - Ist das Flag gesetzt, wird keine erneute Warnung geschickt.
  - Sobald ein neues Signal eingeht, wird ein `InactivityAlertResolved` Event gefeuert, das Flag gelöscht und der Benutzer über Telegram informiert.
- **Decoupled Messaging:**
  - Die Alarmierung erfolgt vollständig entkoppelt. Der Watchdog-Task erzeugt lediglich `InactivityAlertTriggered` bzw. `InactivityAlertResolved` Events. Der Telegram-Bot-Code in `telegram_ui.py` empfängt diese und sendet die formatierte Nachricht.

## Test-Entscheidungen (Testing Decisions)

- **Unit-Tests für die Timeout-Erkennung:**
  - Testen der Erkennungslogik mit mockierten Zeitstempeln und Verifizieren der Event-Veröffentlichungen.
- **Integrationstests:**
  - Simulieren des Watchdog-Durchlaufs im Test-Framework mit mehreren Ventilen und Validierung des Spam-Schutzes und der EventBus-Kopplung.

## Nicht im Leistungsumfang (Out of Scope)

- Pingen von Netzwerkgeräten (wie dem Raspberry Pi selbst) – der Watchdog überwacht nur die Sensor-Peripherie.
- Automatische Behebung der Störungen.
