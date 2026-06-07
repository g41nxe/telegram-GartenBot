# 12. Täglicher Statusbericht und System-Metadaten

Wir implementieren einen automatischen täglichen Statusbericht über Telegram und führen eine Metadaten-Tabelle in der Datenbank ein, um den Sendezustand geräteübergreifend und restartsicher zu speichern.

## Kontext

Der Benutzer wünscht täglich um 08:00 Uhr einen zusammenfassenden Statusbericht per Telegram über die Bewässerungs-Aktivitäten der letzten 24 Stunden sowie den Wetterverlauf und die Wettervorhersage. Zusätzlich sollen Warnungen zum Ventil-Zustand (niedriger Batteriestand, Verbindungsverlust oder gerätespezifische Fehler) enthalten sein.

Um diesen Bericht zuverlässig zu versenden, müssen wir:
1. Das geflossene Wasservolumen der vergangenen Zyklen persistent speichern.
2. Sicherstellen, dass bei Systemneustarts nach 08:00 Uhr nicht mehrfach Berichte für denselben Tag gesendet werden.
3. Im Falle eines Ausfalls (z. B. Pi offline für mehrere Tage) beim Wiederhochfahren nur den neuesten/aktuellen Bericht nachholen, anstatt alle verpassten Tage auf einmal nachzusenden (Spam-Schutz).

## Entscheidung

1. **Einführung der Tabelle `system_metadata`:**
   Wir fügen eine neue SQLite-Tabelle `system_metadata` (Schlüssel-Wert-Paare) ein. Darin wird der Schlüssel `last_daily_report_date` mit dem Datum (`YYYY-MM-DD`) des zuletzt erfolgreich gesendeten Statusberichts persistiert.

2. **Erweiterung von `watering_history`:**
   Die Tabelle `watering_history` erhält eine zusätzliche Spalte `watered_volume` (REAL, Standard: `0.0`), um die tatsächlich ausgebrachten Liter je Zyklus persistent zu protokollieren.

3. **Restartsichere 8-Uhr-Triggerung mit Einmaligkeits-Garantie:**
   Die Scheduler-Schleife prüft jede Minute, ob die aktuelle Uhrzeit `>= "08:00"` ist. Ist dies der Fall, vergleicht sie das heutige Datum mit dem Wert `last_daily_report_date` aus den Datenbank-Metadaten. 
   - Weicht das Datum ab, wird der Bericht generiert, versendet und das Metadatenfeld aktualisiert.
   - Dadurch ist sichergestellt, dass der Bericht täglich genau einmal gesendet wird – auch dann, wenn der Daemon tagsüber neu gestartet wird oder das System erst nach 08:00 Uhr hochfährt (z. B. um 08:15 Uhr nach einem Stromausfall).
   - Es wird dabei stets nur der Bericht des aktuellen Tages nachgeholt.

4. **Konfigurierbare Batteriewarnung:**
   Wir führen die Variable `BATTERY_WARNING_THRESHOLD` in der `.env` und der zentralen Konfiguration ein, um die Warnschwelle für den Batterietausch des Ventils flexibel anpassbar zu machen.

5. **Ventil-Anomalieüberwachung:**
   Der globale Ventilstatus im MQTT-Adapter speichert nun den Zustand `valve_abnormal_state`, welcher per MQTT vom Sonoff Hydro ONE geliefert wird. Dieser Wert wird im Tagesbericht ausgewertet.

6. **Manueller Trigger für Testzwecke:**
   Wir fügen die Telegram-Befehle `/report` und `/statusbericht` hinzu. Damit kann der tägliche Statusbericht jederzeit manuell angefordert werden. Dies generiert den Bericht für den heutigen Tag und sendet ihn direkt an den anfragenden Chat zurück, ohne das persistente Datum des letzten automatischen Berichts in `system_metadata` zu überschreiben.

7. **Aktive Abfrage (Status-Update) beim Abruf:**
   Da das Ventil batteriebetrieben ist und schläft, triggern wir bei jeder `/status`-Abfrage, bei manuellem `/report` und vor dem automatischen Statusbericht um 08:00 Uhr eine MQTT-Abfrage (`{"state": "", "battery": ""}`) auf dem Topic `garden_valve/get`. Um dem Ventil Zeit zu geben, die Anfrage bei seinem nächsten periodischen Aufwachen (Poll) zu verarbeiten, wartet der Telegram-Bot bei `/status`/`/report` für 1,5 Sekunden und der automatische Scheduler für 5 Sekunden vor der Generierung der Nachricht.

8. **Passives Verbindungs-Monitoring und Statistik:**
   Um die Batterie des Ventils maximal zu schonen, protokollieren wir eintreffende Status-Meldungen passiv in der Tabelle `device_status_log`. Hierbei werden `battery` und `linkquality` (LQI) bei jedem Signal aufgezeichnet. Im täglichen Statusbericht aggregieren wir diese Daten für die vergangenen 24 Stunden, um die Gesamtzahl der empfangenen Signale, die durchschnittliche Signalqualität und die längste aufgetretene Funkstille (maximale Funklücke) im Textformat darzustellen.

9. **Erweitertes Wetter-Reporting:**
   Die Open-Meteo-Wetterabfrage wird um tägliche Daten erweitert (`temperature_2m_max`, `temperature_2m_min`, `precipitation_probability_max`). Diese zusätzlichen Daten (minimale/maximale Tagestemperatur und die maximale Regenwahrscheinlichkeit des aktuellen Tages) werden in der Tabelle `weather_history` gespeichert (`temp_min`, `temp_max`, `rain_probability`) und sowohl im täglichen Statusbericht als auch in der interaktiven Status-Abfrage übersichtlich dargestellt.

## Konsequenzen

- **Datenintegrität und Ausfallsicherheit:** Das System sendet den Tagesbericht zuverlässig und absolut dopplungsfrei, selbst bei häufigen Service-Restarts oder Stromausfällen.
- **Transparente Ventil-Diagnose:** Der Anwender erhält proaktiv Warnungen bei schleichendem Batterieverfall oder physischen Geräte-Blockaden.
- **Erweitertes Reporting:** Die persistente Speicherung des Wasservolumens in der Guss-Historie ermöglicht eine exakte Erfassung des Gesamtverbrauchs.
- **Detailliertere Wetterprognosen:** Der Anwender erhält eine genauere Übersicht über die erwartete Temperaturspanne und die Regenwahrscheinlichkeit, was manuelle Bewässerungsentscheidungen zusätzlich erleichtert.
