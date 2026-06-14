# Feature: Verbaler Tagesbericht

## Problemstellung (Problem Statement)

Der tägliche Statusbericht (automatisch um 08:00 Uhr und manuell über `/report`) gibt alle Daten in Form von aufgelisteten Fakten aus. Das macht den Bericht schwer auf einen Blick erfassbar. Außerdem unterscheiden sich die Code-Pfade beider Report-Varianten geringfügig (Sleep-Dauer, fehlender Chart-Fallback), was zu inkonsistentem Verhalten führen kann.

## Lösung (Solution)

Der Statusbericht wird auf eine verbale, satzförmige Darstellung umgestellt. Jeder Abschnitt (Bewässerung, Wetter, Ventil) wird als lesbarer Satz formuliert statt als Stichpunktliste. Zusätzlich wird eine Abweichungsanzeige eingeführt: Wenn der tatsächlich gefallene Regen um mehr als 2 mm von der gestrigen Vorhersage abweicht, wird dies im Bericht erwähnt. Beide Report-Varianten (08:00 und `/report`) laufen über denselben Code-Pfad.

## User Stories

1. Als Benutzer des Telegram-Bots möchte ich den Tagesbericht als lesbare Sätze erhalten, um die Situation auf einen Blick zu erfassen, ohne Stichpunkte lesen zu müssen.
2. Als Benutzer möchte ich wissen, ob heute mehr oder weniger Regen gefallen ist als gestern vorhergesagt, um besser einschätzen zu können, ob der Garten Wasser braucht.
3. Als Benutzer möchte ich den Ventil-Status als einzeilige verbale Aussage sehen (z. B. „gutes Signal"), ohne numerische Rohwerte interpretieren zu müssen.
4. Als Benutzer möchte ich, dass der manuelle `/report`-Befehl exakt dasselbe Format und dieselben Daten liefert wie der automatische 08:00-Bericht.
5. Als Benutzer möchte ich im Bericht erkennen, ob starker, mäßiger oder kein Regen für heute vorhergesagt wird, ohne selbst mm-Werte einordnen zu müssen.
6. Als Benutzer möchte ich Warnungen (Batterie, Anomalie, Watchdog) inline beim jeweiligen Ventil sehen, ohne einen separaten Warnungsabschnitt lesen zu müssen.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Neue DB-Abfrage:** Eine neue Datenbankfunktion `get_weather_around_hours_ago(hours, max_offset_hours)` liefert den Wettereintrag, dessen Zeitstempel am nächsten an N Stunden in der Vergangenheit liegt. Damit wird die gestrige Regenvorhersage (`rain_next_24h_mm` von vor 24h) für den Abweichungsvergleich ausgelesen.

- **Drei neue Hilfsfunktionen in der Report-Erzeugung:**
  - `_format_watering_section(success, failed, volume)` → verbaler Bewässerungssatz
  - `_format_weather_section(temp, temp_min, temp_max, weather_desc, rain_last, rain_next, rain_prob, yesterday_rain_next)` → verbaler Wettersatz
  - `_format_valve_line(...)` → einzeilige Ventilbeschreibung

- **Regenklassifikation nach DWD-Schwellenwerten (für Berlin):**
  - < 2 mm Vorhersage → „trocken"
  - 2–10 mm → „mäßiger Regen erwartet"
  - > 10 mm → „starker Regen erwartet"

- **Abweichungsschwellenwert:** 2 mm (DWD-Untergrenze für mäßigen Regen, entspricht einem durchschnittlichen Berliner Regentag). Abweichungen ≤ 2 mm werden nicht angezeigt.

- **LQI-Qualitätsstufen** (unverändert aus bestehendem `_lqi_label`-Code):
  - ≥ 180 → „sehr gutes Signal"
  - ≥ 120 → „gutes Signal"
  - ≥ 60 → „ausreichendes Signal"
  - < 60 → „schwaches Signal"
  - 0 Meldungen → „Keine Verbindung ⚠️"

- **Ventil-Warnungen inline:** Batterie-Warnung (`🪫`) und Ventil-Anomalie (`🚨`) werden in der Ventilzeile hinter dem Signalstatus angehängt, nicht mehr in einem separaten Warnungsabschnitt. System-Warnungen (MQTT-Broker, Mittelweg-Dienst, Watchdog) bleiben als separater Block erhalten.

- **`/report`-Handler vereinfacht:** Der Handler ruft `generate_daily_report()` direkt auf (wie bisher), jedoch wird der Sleep auf 5 Sekunden angeglichen (war 1,5s). Der stündliche Text-Fallback für das Wetterchart wird entfernt — das ist Verantwortung des Chart-Adapters, nicht des Handlers.

- **Keine Broadcast-Änderung:** `/report` sendet weiterhin nur an den anfragenden `chat_id`. Der automatische 08:00-Bericht broadcastet weiterhin über den Ereignis-Kanal. Beide Varianten rufen `generate_daily_report()` auf.

## Test-Entscheidungen (Testing Decisions)

- **Gute Tests** testen das externe Verhalten der Hilfsfunktionen: Was steht im zurückgegebenen String? Keine Assertions über interne Variablen oder Zwischenwerte.

- **Getestete Module:**
  - `_format_watering_section`: Nullfall, ein Zyklus, mehrere Zyklen, Fehlschläge
  - `_format_weather_section`: Normalfall, signifikante positive/negative Abweichung, nicht-signifikante Abweichung, starker/mäßiger Regenvorhersage
  - `_format_valve_line`: Alle LQI-Stufen, Keine Verbindung, Watchdog, Batterie, Anomalie
  - `get_weather_around_hours_ago`: Nächster Treffer, kein Eintrag, Treffer außerhalb Toleranz

- **Vorarbeiten:** `tests/adapters/test_database.py` (Muster: temporäre DB per `_make_temp_db`, Patch auf `DB_PATH`), `tests/ui/test_telegram_ui.py` (Muster: `_process_message` mit gemocktem `telegram_client`).

- **Neue Testdatei:** `tests/adapters/test_daily_report.py` für die Hilfsfunktionen. Kein End-to-End-Test von `generate_daily_report()` erforderlich — die Funktion ist nur eine Komposition der drei getesteten Hilfsfunktionen.

## Nicht im Leistungsumfang (Out of Scope)

- Änderung des `/status`-Befehls (zeigt weiterhin die bisherige Stichpunkt-Darstellung)
- Mehrsprachigkeit oder konfigurierbare Berichtssprache
- Historischer Vergleich über mehr als 24h (z. B. Wochendurchschnitt)
- Push-Notification bei starker Regenabweichung

## Weitere Anmerkungen (Further Notes)

- ADR 0012, Punkt 7 wird angepasst: Der Sleep für `/report` wird von 1,5s auf 5s angeglichen, um identisches Verhalten mit dem automatischen Bericht sicherzustellen.
- Die neue DB-Abfrage `get_weather_around_hours_ago` ist generisch gehalten und kann später auch für andere Vergleiche (z. B. Temperaturtrend) genutzt werden.
