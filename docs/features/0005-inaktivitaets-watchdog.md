# Feature: Inaktivitäts-Watchdog (Systemweite Geräteüberwachung)

## Problemstellung (Problem Statement)

Batteriebetriebene Smart-Home-Komponenten (wie das Bewässerungsventil oder Füllstandssensoren) können unbemerkt ausfallen. Mögliche Ursachen sind leere Batterien, Verbindungsabbrüche (WLAN oder Zigbee) oder physische Störungen. Ein unbemerkter Ausfall kann kritische Folgen haben (z. B. unbemerkte Überläufe oder ausbleibende Bewässerung). 

Es wird eine einheitliche, systemweite Lösung benötigt, die alle verbundenen Geräte überwacht und proaktiv alarmiert, wenn ein Gerät über einen längeren Zeitraum kein Lebenszeichen gesendet hat.

## Lösung (Solution)

Wir implementieren einen **Inaktivitäts-Watchdog** im Bewässerungs-Daemon. Dieser Dienst läuft als periodischer Hintergrund-Task (z. B. stündlich) und überwacht die Aktivitäts-Zeitstempel aller registrierten Hardware-Komponenten. 

Für jedes Gerät wird in der Konfiguration (`.env`) ein individuelles Timeout-Intervall definiert. Überschreitet die Zeit seit dem letzten Lebenszeichen (dem letzten Datenbankeintrag für dieses Gerät) den konfigurierten Schwellenwert, sendet der Bot eine Warnmeldung per Telegram.

Unterstützte Geräte in der ersten Version:
1. **Ventil (Sonoff Hydro ONE):** Auswertung der Zeitstempel in `device_status_log`. Standard-Timeout: 24 Stunden.
2. **Füllstandssensor (Klärgrube):** Auswertung der Zeitstempel in `septic_tank_readings`. Standard-Timeout: 18 Stunden.

## User Stories

1. Als Betreiber des GartenBots möchte ich sofort benachrichtigt werden, wenn ein wichtiges Gerät (wie das Ventil) offline geht, um Ausfälle frühzeitig zu beheben.
2. Als Betreiber möchte ich für jedes Gerät ein eigenes Zeit-Timeout festlegen können, da manche Geräte häufiger senden (Ventil bei Aktivität) und manche seltener (Füllstandssensor 2x täglich).
3. Als Betreiber möchte ich eine Entwarnung erhalten, sobald das betroffene Gerät wieder ein Signal sendet, damit ich weiß, dass das Problem gelöst ist.
4. Als Entwickler möchte ich ein generisches System haben, bei dem neue Gerätetypen (z. B. Bodenfeuchtesensoren) mit minimalem Aufwand in die Überwachung integriert werden können.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Konfiguration:**
  - Jedes Gerät hat ein eigenes konfigurierbares Limit in Stunden (z. B. `WATCHDOG_VALVE_TIMEOUT_HOURS=24` und `WATCHDOG_SEPTIC_TIMEOUT_HOURS=18`).
  - Ein globaler Schalter `WATCHDOG_ENABLED=true` erlaubt das Deaktivieren des gesamten Watchdogs.
- **Hintergrund-Task:**
  - Ein stündlicher Task im `scheduler.py` prüft alle aktiven Überwachungs-Regeln.
- **Warnzustand & Entwarnung:**
  - Der Sendezustand einer Warnung wird in `system_metadata` hinterlegt (z. B. `watchdog_alert_active_<device_id> = 1`).
  - Erst wenn dieser Wert gesetzt ist, wird bei Inaktivität keine erneute Warnung geschickt (Spam-Schutz).
  - Sobald ein neuer Datenbankeintrag für das Gerät registriert wird, wird die Warnung zurückgesetzt und eine Entwarnungsnachricht gesendet (z. B. `🟢 Verbindung zu [Gerätename] wiederhergestellt.`).
- **Erweiterbarkeit:**
  - Die Watchdog-Prüfung verwendet eine Registry oder eine Liste von Watchdog-Regeln (jeweils definiert durch einen Gerätenamen, ein Timeout, eine Datenbank-Abfragefunktion für das letzte Signal und das entsprechende Alert-Flag in den Metadaten).

## Test-Entscheidungen (Testing Decisions)

- **Unit-Tests für die Timeout-Erkennung:**
  - Testen der Abfragefunktionen mit mockierten Zeitstempeln (z. B. letztes Signal vor 25 Stunden triggert Alarm bei 24h Limit).
  - Testen der Entwarnungslogik (Empfang eines aktuellen Signals löscht das Alert-Flag in `system_metadata`).
- **Integrationstest:**
  - Simulieren des Watchdog-Durchlaufs im Test-Framework ohne echten Scheduler, um den korrekten Telegram-Versand zu validieren.

## Nicht im Leistungsumfang (Out of Scope)

- Pingen von Netzwerkgeräten (wie dem Raspberry Pi selbst) – der Watchdog läuft lokal auf dem Pi und überwacht nur Peripheriegeräte.
- Automatische Behebung der Störungen (z. B. Neustart von Diensten).
