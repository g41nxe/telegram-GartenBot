# Feature: Gießcheck & graduierte Gieß-Steuerung

## Problemstellung (Problem Statement)

Der Bewässerungs-Daemon verfügt über Wetterdaten und Bewässerungshistorien, zieht daraus aber nur grobe Schlüsse. Heute existiert ausschließlich eine **binäre Überspringlogik** (`evaluate_rain_window`): Liegt die Summe aus gefallenem und vorhergesagtem Regen über `RAIN_THRESHOLD_MM`, fällt der geplante Guss komplett aus — sonst läuft er unverändert. Daraus ergeben sich vier Schwächen:

1. **Nur Angebotsseite, keine Nachfrageseite.** Die Entscheidung kennt nur Regen. Wie viel Wasser die Pflanze *braucht* (Tagestemperatur, mehrtägige Hitze) fließt nicht ein. 3 mm bei 12 °C bewölkt und 3 mm bei 35 °C Hitzewelle führen zur identischen Entscheidung.
2. **Gemessen und vorhergesagt werden gleich gewichtet.** Unsicherer Forecast wird wie bereits gefallener Regen behandelt; die ohnehin abgerufene Regenwahrscheinlichkeit (`rain_prob`) wird verworfen.
3. **Alles-oder-nichts.** Bei teilweisem Regen gibt es nur „voller Guss" oder „Komplettausfall" — kein dosiertes Reduzieren.
4. **Keine nutzbare Empfehlung.** Der Tagesbericht zeigt Zahlen, bewertet sie aber nicht; der Benutzer muss selbst interpretieren und trägt das Risiko, kumulierten Bodenfeuchte-Verlust über mehrere heiße Tage zu übersehen.

## Lösung (Solution)

Eine gemeinsame Bewertungslogik liefert künftig einen **stufenlosen Skalierungsfaktor (0–100 %)** statt einer reinen Ja/Nein-Entscheidung. Der Faktor steuert zwei Dinge:

- **Geplante Güsse** werden vom Scheduler automatisch auf diesen Faktor **skaliert** (Zeit- *und* Volumenlimit). Der bisherige binäre Skip ist damit nur noch der Sonderfall *Faktor = 0 %*; ein Wert dazwischen ergibt einen kürzeren/kleineren Guss statt Komplettausfall.
- **Auf Anfrage** gibt der neue Telegram-Befehl `/giesscheck` (Button `💧 Gießcheck`) denselben Faktor als **Gieß-Empfehlung** mit Verdict und 1–3 Begründungssätzen aus.

Die Bewertung berücksichtigt drei Signale: das **Regen-Fenster** (gefallener Regen der letzten 24 h, Forecast der nächsten 24 h **nach Wahrscheinlichkeit diskontiert**), die **heutige Höchsttemperatur** und die **Hitzestrecke** (aufeinanderfolgende heiße Vortage). Hitze hebt die effektive Regenschwelle: An heißen Tagen reduziert dieselbe Regenmenge die Bewässerung weniger.

Der manuelle Guss bleibt bewusst **außen vor** — dort greift weiterhin die Rückfrage aus Feature 0020 (der Mensch entscheidet selbst).

### Leitprinzip: Entscheidung ist punktuell, Chart ist nur Anzeige

Die Gieß-Entscheidung ist **zeitpunktbezogen** und fällt **immer zum Auslösezeitpunkt der Zeitsteuerung** (bzw. on-demand bei `/giesscheck`). Nur dort wirkt der Faktor steuernd. Der Wetterchart **löst keine Bewässerung aus** — er ist reine Anzeige, nutzt für seine Caption aber **dieselbe Logik und dasselbe 48-h-Fenster** wie die Entscheidung. Dadurch spiegelt die Caption die Entscheidung wider; es gibt **keine Divergenz** zwischen „was der Chart sagt" und „was der Bot tut".

## User Stories

1. Als Benutzer möchte ich, dass ein geplanter Guss bei teilweisem Regen **anteilig reduziert** statt komplett übersprungen wird, damit ich Wasser spare, ohne den Garten trockenfallen zu lassen.
2. Als Benutzer möchte ich, dass an heißen Tagen und während einer Hitzestrecke **mehr Regen nötig ist**, bevor der Guss reduziert wird, damit kumulierter Bodenfeuchte-Verlust nicht übersehen wird.
3. Als Benutzer möchte ich, dass vorhergesagter Regen nach seiner **Wahrscheinlichkeit gewichtet** wird, damit ein unsicherer Forecast die Bewässerung nicht voreilig kappt.
4. Als Benutzer möchte ich über den Button `💧 Gießcheck` bzw. `/giesscheck` eine Empfehlung abrufen, die ein klares Verdict (`🌧 Kein Gießen nötig`, `💧 Reduzierter Guss`, `🚿 Voller Guss`) **plus den Faktor** und 1–3 Begründungssätze zeigt.
5. Als Benutzer möchte ich in der Begründung die **Datenquelle** des gefallenen Regens sehen („lokal gemessen" / „ERA5-Reanalyse" / „Vorhersage"), um die Verlässlichkeit einzuschätzen.
6. Als Benutzer möchte ich benachrichtigt werden, wenn ein geplanter Guss reduziert wurde (nicht nur, wenn er ganz ausfiel), damit ich die Entscheidung nachvollziehen kann.
7. Als Benutzer möchte ich, dass meine **manuell** gestarteten Güsse nicht automatisch reduziert werden, sondern weiterhin nur die Rückfrage aus Feature 0020 erhalten.
8. Als Benutzer möchte ich eine verständliche Fehlermeldung erhalten, wenn noch keine Wetterdaten vorhanden sind (z. B. direkt nach der Erstinstallation).
9. Als Benutzer möchte ich Temperaturschwelle und Hitze-Empfindlichkeit über Umgebungsvariablen anpassen können, damit die Steuerung zu meinem Standort passt.

## Implementierungs-Entscheidungen (Implementation Decisions)

### Architektur

- Die Bewertung lebt als **pure Funktion** `evaluate_watering()` in `core/watering_advice.py` — kein I/O, kein Zustand, keine Adapter-Abhängigkeiten (ADR 0021). Sie **komponiert** die bestehende `evaluate_rain_window()`, statt deren Schwellenwert-Logik zu duplizieren.
- Rückgabe ist eine `NamedTuple` `WateringDecision(factor: float, verdict: str, reasons: list[str], skip: bool)`. `skip = (factor == 0)` ist die Bequemlichkeits-Ableitung für Aufrufer, die nur die binäre Frage brauchen.
- Der Wetter-Dienst-Pfad orchestriert: `weather.evaluate_watering_factor()` liefert den Faktor (cache-first wie bisher, ADR 0020) und liest dafür zusätzlich `get_daily_max_temps()`, den heutigen Forecast-Tageshöchstwert und `rain_last_source`.
- **`should_skip_watering()` bleibt** als dünner Kompatibilitäts-Wrapper erhalten: Er berechnet intern den Faktor und gibt `(decision.skip, details)` zurück. So funktioniert das geplante Feature 0020 (manuelle Rückfrage) unverändert mit binärer Semantik — **ein Gehirn, zwei Sichten**.
- Der Telegram-Handler lebt in `ui/telegram_ui.py`, konsistent mit allen anderen Befehlen.

### Rechenmodell (Modell A — linearer Regen-Quotient mit hitze-angepasster Schwelle)

```
R_eff        = rain_last + rain_next_eff                          # erwarteter Regen (s. u.)
hitze_faktor = 1 + (heiß_heute ? B_today : 0) + min(streak, Cap) * B_streak
T_eff        = RAIN_THRESHOLD_MM * hitze_faktor
faktor_roh   = clamp(1 - R_eff / T_eff, 0, 1)
```

- **`rain_next_eff` = erwarteter Niederschlag**, stundenweise mit der jeweiligen Wahrscheinlichkeit gewichtet: `Σ precip[h] * prob[h] / 100`. Berechnet wird er **zur Aufrufzeit** aus der gecachten Stundenreihe (re-zentriert auf „jetzt", siehe „Caching & Re-Zentrierung"); die pure Funktion erhält ihn als fertigen Skalar. Das ist die textbuch-korrekte Diskontierung und fail-safe-konformer als eine Multiplikation der 24h-Summe mit der Maximal-Wahrscheinlichkeit. Die rohe 24h-Summe `rain_next` und die Spitzen-`rain_prob` bleiben für **Anzeige** (Reasons-Text, Tagesbericht, Chart) erhalten.
- `rain_last` = gefallener Regen (quellen-agnostisch, siehe unten). Fehlen Wahrscheinlichkeitsdaten, geht `rain_next_eff → 0` → höherer Faktor → eher gießen (**bewusst fail-safe**, konsistent mit „keine Daten → bewässern").
- `heiß_heute` = `temp_max_today >= GIESSCHECK_HOT_TEMP_C`, wobei `temp_max_today` der **vorhergesagte** Tageshöchstwert ist (das gemessene Tagesmaximum existiert früh am Tag noch nicht; der Forecast-Wert ist rund um die Uhr verfügbar und über den Tag stabil).
- `streak` = aufeinanderfolgende abgeschlossene Vortage ≥ `GIESSCHECK_HOT_TEMP_C` aus `get_daily_max_temps()` (gespeicherte Tagesmaxima), datums-aware mit Lücken-Abbruch (ADR 0022).
- Aus dem einen Regler `GIESSCHECK_HEAT_SENSITIVITY` (Standard `0.5`) leiten sich ab: `B_today = sensitivity` (`0.5`), `B_streak = sensitivity / 2` (`0.25`), `Cap = GIESSCHECK_HOT_DAYS_COUNT` (`3`). `sensitivity = 0` schaltet die Bedarfsseite ab (reines Regen-Fenster wie heute).

**Totzonen** (im Faktor, als Code-Konstanten — nicht als Config):

- `faktor_roh >= 0.9` → **1.0** (eine ~10-%-Reduktion lohnt den Eingriff nicht).
- `faktor_roh <= 0.1` → **0.0** (entspricht dem bisherigen vollständigen Skip; ein 10-%-Rinnsal verschwendet einen Zyklus).
- dazwischen auf 5-%-Schritte gerundet.

**Verdict-Ableitung** (3 Stufen, ADR-0029-konforme Wasser-Emojis — die Ampelfarben 🟢/🟡/🔴 bleiben dem Gesundheits-Status vorbehalten):

| Faktor | Verdict |
|--------|---------|
| `0 %` | `🌧 Kein Gießen nötig` (Regen reicht) |
| `1–99 %` | `💧 Reduzierter Guss` (inkl. Prozentwert) |
| `100 %` | `🚿 Voller Guss` |

**Beispiel** (Schwelle 3 mm): 1 mm gefallen + erwartete 2 mm (4 mm Forecast, im Mittel ~50 % Wahrscheinlichkeit) → `R_eff = 3.0`. Kühl (`hitze_faktor 1.0`): `T_eff 3.0` → Faktor **0 %** → 🌧. Hitzestrecke (`hitze_faktor 2.25`): `T_eff 6.75` → `1 − 3/6.75` = **56 %** → 💧 56-%-Guss statt Komplettausfall.

### Skalierung im Scheduler

- Der Faktor wird **einmal pro Auslösung** in `_trigger_scheduled_watering()` berechnet und multipliziert das *eine* `duration_minutes` + das *eine* `target_volume_liters` des Zeitplans. Die skalierten Werte fließen unverändert in **jedes** Ventil (parallel wie sequentiell) — es gibt kein per-Ventil-Limit, und Regen betrifft den ganzen Garten gleich.
- **Dauer-Rundung:** `duration_scaled = max(1, round(duration * faktor))`, solange Faktor > 0. So erzeugt ein Faktor > 0 nie eine ungültige 0-Minuten-Dauer (`start_watering()` lehnt `<= 0` als Fehler ab — das würde fälschlich den `ScheduleFailed`-Pfad auslösen). Worst Case ist ein 1-Minuten-Guss.
- **Volumen-Rundung:** `volume_scaled = round(volume * faktor)` ohne Floor; `0` ist gültig und degradiert den Lauf sauber auf zeitbegrenzt (First-to-Hit). Kein Überwässerungs-Risiko, weil die skalierte Dauer (≤ Original) den Lauf deckelt. Da **beide** Limits mit demselben Faktor skaliert werden, bleibt das bindende Limit erhalten.
- **Verzweigung:** `faktor == 0` → wie heute `WateringSkipped` + Historie `"skipped"`. `0 < faktor < 1` → Guss mit skalierten Limits starten **und** `WateringScaled` veröffentlichen. `faktor == 1` → unverändert.

### Ereignisse

- Neues Domänen-Ereignis `WateringScaled` in `core/scheduler_events.py` (Faktor, Original- und skalierte Werte, Begründung). Es ist ein **reines Benachrichtigungs-Ereignis**: Die Telegram-UI abonniert es (`_on_watering_scaled`, Broadcast wie die übrigen `_on_*`) und sendet eine Nachricht. **Keine eigene Historie-Zeile** — die *skalierten Limits* stehen über die bestehende `WateringCycleStarted`-Zeile ohnehin schon in der Historie (eine dedizierte Zeile wäre die dritte pro Lauf); die *Reduktions-Begründung* lebt in der Nutzer-Nachricht.

### Wetterchart (`chart.py`)

- `chart.py` bleibt eine **Anzeige/Sicht** (löst keine Bewässerung aus), nutzt für die Caption nun aber **dieselbe Logik und dasselbe 48-h-Fenster** wie die Entscheidung: `evaluate_watering()` mit `rain_last` (gefallener Regen der letzten 24 h) **plus** erwartetem Niederschlag der nächsten 24 h, gleichen Hitze-Eingaben und gleicher 🌧/💧/🚿-Sprache. Damit stimmen Chart-Caption, `/giesscheck` und Scheduler-Entscheidung bei gleichen Daten überein — **keine Divergenz** mehr.
- **Grafik auf ±24 h erweitert:** Der Chart zeigt den **gefallenen *und* den erwarteten** Verlauf (48 Stundenwerte, -24 h … +24 h), mit einer senkrechten **„Jetzt"-Markierung** an der Grenze und dem Titel **„letzte & nächste 24 h"** (statt „nächste 24h").
- **Vergangenheit aus dem Archiv, nicht aus dem Forecast:** Die Niederschlags- (und Temperatur-)Balken der **letzten 24 h** stammen aus den **Archiv-/Reanalyse-Daten (ERA5)** — *nicht* aus der Forecast-Historie —, konsistent mit `rain_last` und ADR 0024. Die **nächsten 24 h** kommen aus dem Forecast-Modell. Dazu wird `_fetch_measured_rain_last()` so erweitert, dass es die **stündliche** Archivreihe liefert; daraus speisen sich sowohl `rain_last` (Summe) als auch die Vergangenheits-Balken des Charts — *eine* Quelle, kein Auseinanderdriften. Fehlen jüngste Archiv-Stunden (ERA5T-Verzögerung), greift für diese der Forecast als Fallback (über `rain_last_source` kenntlich). Sobald der Regensensor (Feature 0016) primäre Quelle ist, folgen die Vergangenheits-Balken ebenfalls `rain_last_source`.
- Feasibility: `chart.py` importiert bereits `database` und `config`; `get_daily_max_temps()` ist ohne neue Cross-Adapter-Kopplung erreichbar.

### Datenquellen & Vorbereitung auf Feature 0016 (Regensensor)

- **Quellen-agnostisch:** `evaluate_watering()` erhält `rain_last` als Wert. Woher dieser stammt (lokaler Regensensor, ERA5-Archiv, Forecast-Fallback), entscheidet allein die Quellenauswahl in `weather.py`. Sobald Feature 0016 landet, fließt der **lokale Messwert automatisch** in den Faktor — ohne Änderung am Rechenkern (Fortführung von ADR 0024).
- **Auch die stündliche Vergangenheits-Reihe ist quellen-abstrahiert:** Nicht nur `rain_last` (Summe), sondern auch die für die Chart-Vergangenheit genutzte Stundenreihe folgt `rain_last_source`. Vorgesehene Reihenfolge: **Regensensor** (Intervall-/Stundenwerte aus `rain_measurements`, Feature 0016) → **ERA5-Archiv** (stündlich) → **Forecast** (Fallback). Die Schnittstelle wird hier als *eine* Funktion „liefere die letzten 24 h stündlich + Quelle" angelegt, sodass Feature 0016 nur seine Sensor-Zeitreihen-Abfrage einklinkt — `rain_last` (Summe) und die Chart-Balken bleiben dauerhaft aus **einer** Quelle. Wechselt die Quelle auf den Sensor, wechseln Summe *und* Verlauf gemeinsam.
- **`rain_last_source` wird in die Funktion gereicht.** Das Feld existiert bereits systemweit (künftig auch mit Wert `"sensor"`) und dient (a) der Quellenangabe im Begründungstext und (b) als **Naht für späteres Quellen-Vertrauen**. Bewusst wird *jetzt noch kein* Quellen-Discount eingebaut (YAGNI); gemessener/Sensor-Regen erhält volles Gewicht.
- **Orthogonalität:** Dieses Feature skaliert die geplante Menge *vor* dem Start. Feature 0016 kann denselben Lauf *während* der Bewässerung per `WateringCycleInterrupted` (Guss-Unterbrechung) kappen, sobald der Sensor aktiven Regen meldet. Beide greifen an verschiedenen Punkten und ergänzen sich konfliktfrei.
- **Zukunfts-Naht Temperatur:** Der Regensensor liefert auch lokale Temperatur (0016 speichert sie). Sie könnte das Hitze-Signal später genauer machen; vorerst bleibt die Wetterdienst-Temperatur die Quelle.

### Datenbank

- Neue Funktion `get_daily_max_temps(days: int = 5) -> list[tuple[str, float]]`: gruppiert `weather_history` nach Kalendertag, schließt den heutigen Tag aus (`WHERE date(timestamp) < date('now')`), gibt `(date_str, MAX(temp_max))` pro Tag zurück (neueste zuerst). Tage ohne Einträge werden übersprungen (kein Padding) — `evaluate_watering()` erkennt Lücken anhand der Datumsdifferenz und bricht die Hitzestrecke ab.
- Die gecachte **Stundenreihe** wird so erweitert, dass sie die letzten 24 h (Archiv) und mindestens die nächsten 24 h (Forecast) mit Niederschlag, Wahrscheinlichkeit und Temperatur abdeckt. Sie **ersetzt** das zuvor angedachte gecachte Skalar `rain_next_eff_mm` (dieser wird zur Aufrufzeit berechnet, s. u.). Die bestehenden fetch-zeitlichen Skalare (`rain_last_24h_mm`, `rain_next_24h_mm`) bleiben für Anzeige/Tagesbericht/ADR 0025 erhalten. Schema-Änderungen über das bestehende `ALTER TABLE … try/except OperationalError`-Muster (kein Migrations-Framework).

### Caching & Re-Zentrierung zur Aufrufzeit (verfeinert ADR 0020)

Gecacht werden **Rohdaten, keine fenster-abhängigen Skalare**: die stündliche Reihe (Zeitstempel, Niederschlag, Wahrscheinlichkeit, Temperatur) für die letzten 24 h (Archiv) und mindestens die nächsten 24 h (Forecast — geholt werden ohnehin 48 h via `forecast_days=2`). `weather.evaluate_watering_factor()` und der Chart bilden `rain_last`, `rain_next_eff` und `temp_max_today` **zur Aufrufzeit** aus dieser Reihe gegen `_find_current_index(now)` — das 24h-Fenster wird also stets auf „jetzt" re-zentriert.

Folge: Der in ADR 0020 als Nachteil akzeptierte **Fenster-Drift** (bis 2 h bei frischem, bis 24 h beim Stale-Cache) entfällt. „Frische" betrifft danach nur noch das (höchstens stündlich aktualisierte) Forecast-Modell, nicht die Fenster-Position. Die Cache-first-Fallback-Kette aus ADR 0020 bleibt unverändert — sie bestimmt weiterhin, *welcher* Datensatz gelesen wird; nur die *Auswertung* wandert vom Abruf- zum Aufrufzeitpunkt. Reicht die gecachte Vorwärts-Reihe nicht bis `now + 24 h` (sehr alter Cache), wird der fehlende Teil konservativ behandelt (fail-safe Richtung Gießen).

### Konfiguration

- **`RAIN_THRESHOLD_MM` wird auf `3.0` vereinheitlicht.** `config/garden.conf` wird von `2.0` auf `3.0` angeglichen (README und ADR 0003 nennen bereits `3.0`). Begründung: `3.0 mm ≈ 1/8″` ist der wassersparende Industrie-Default und passt zum humiden, temperaten Standort; zusammen mit der hitze-angepassten `T_eff` ergibt der Basiswert automatisch die in der Literatur empfohlene Saison-Spanne (kühl ≈ 1/8″ … Hitzestrecke ≈ 1/4″). Recherche-Quellen in den weiteren Anmerkungen.
- **`GIESSCHECK_HOT_TEMP_C=25.0`** — Schwelle „heißer Tag" (DWD: warmer Tag ≥ 25 °C).
- **`GIESSCHECK_HEAT_SENSITIVITY=0.5`** — *ein* Regler für die Bedarfsseite (siehe Rechenmodell).
- **`GIESSCHECK_HOT_DAYS_COUNT=3`** — Deckel der berücksichtigten Hitzestrecke.

### Telegram-UX

Hauptmenü erhält den Button `💧 Gießcheck`; der Handler matcht Button-Text *und* `/giesscheck` und bricht laufende Wizards ab. Antwort-Format: Verdict-Zeile mit Faktor, Leerzeile, 1–3 Begründungssätze (erklärende Sätze mit Quellenangabe). Die `WateringScaled`-Benachrichtigung nutzt verspieltes Regen-/Wasser-Framing analog zum Skip.

Alle neuen/geänderten Nachrichten folgen verbindlich dem Design-System (ADR 0029): Anrede „du", Header `*Emoji Titel*` ohne Doppelpunkt, Einheiten mit Leerzeichen (`3.0 mm`), Wasser-Emojis statt Ampelfarben. IST- und SOLL-Referenz sind im selben Arbeitsschritt nachzuziehen (`.claude/rules/telegram_messages.md`).

## Test-Entscheidungen (Testing Decisions)

Getestet wird ausschließlich das **externe Verhalten** — Rückgabe der Funktion, gesendete Nachricht, veröffentlichte Ereignisse, skalierte Limits. Keine Assertions auf SQL-Queries oder interne Zustände. TDD (Rot-Grün-Refaktor), Thread-Hygiene (Daemon-Timer), Coverage darf nicht regredieren.

### `tests/core/test_watering_advice.py` (Erweiterung)

Pure-Funktions-Tests ohne Mocks (Referenz: `test_watering_controller.py`):

- Kein Regen → Faktor 100 % (`🚿`); genug Regen, kühl → 0 % (`🌧`); identischer Regen bei Hitzestrecke → Teil-Faktor (`💧`).
- Forecast-Diskontierung über `rain_next_eff` (erwarteter Niederschlag); fehlende Wahrscheinlichkeit → `rain_next_eff = 0` → Forecast trägt nicht bei.
- Totzonen: `faktor_roh ≥ 0.9` → 100 %, `≤ 0.1` → 0 %.
- Hitzestrecke bricht bei Datumslücke bzw. kühlem Vortag ab; leere `past_daily_temps` → kein Streak, kein Absturz.
- `rain_last_source` erscheint korrekt benannt im Begründungstext.

### `tests/adapters/test_database.py` (Erweiterung)

- `get_daily_max_temps()`: neueste zuerst, heutiger Tag ausgeschlossen, keine Lücken-Einträge, leer bei fehlenden Daten.
- `rain_next_eff_mm` wird korrekt geschrieben/gelesen (inkl. Migration auf Bestands-DB).

### `tests/adapters/test_weather.py` (Erweiterung)

- `rain_next_eff` = stundenweise gewichtete Summe; `rain_prob` (max) bleibt für die Anzeige unverändert.
- `_fetch_measured_rain_last()` liefert die **stündliche Archivreihe** *und* die Summe; `rain_last` = Summe der Archiv-Stunden (nicht Forecast). Fehlende jüngste Archiv-Stunden → Forecast-Fallback nur für diese Stunden, `rain_last_source` korrekt gesetzt.
- **Re-Zentrierung zur Aufrufzeit:** Bei identischer gecachter Stundenreihe, aber unterschiedlichem „jetzt", verschiebt sich das 24h-Fenster entsprechend (Skalare werden zur Aufrufzeit gebildet, nicht eingefroren). Ein z. B. 90 Min alter Cache liefert ein korrekt auf „jetzt" zentriertes Fenster.

### `tests/test_irrigation.py` / Scheduler (Erweiterung)

- Faktor 0 → `WateringSkipped`, kein Ventil-Befehl.
- 0 < Faktor < 1 → Ventil startet mit **skalierter** Dauer *und* skaliertem Volumen; `WateringScaled` wird veröffentlicht; **keine** zusätzliche Historie-Zeile über das Bestehende hinaus.
- Dauer-Rundung: `max(1, …)` verhindert 0-Minuten-Fehler bei kurzen Plänen × kleinem Faktor.
- Volumen darf auf 0 runden (zeitbegrenzter Lauf).
- Faktor 1 → Originalwerte, kein `WateringScaled`.
- Multi-Ventil: derselbe Faktor wirkt auf alle Ventile (parallel und sequentiell).

### `tests/adapters/test_chart.py` (Erweiterung)

- Caption nutzt dasselbe 48-h-Fenster wie die Entscheidung (gefallener Regen **fließt ein**); Verdict-Sprache und -Ergebnis identisch zu `/giesscheck` bei gleichen Daten.
- `hourly_forecast_json` umfasst -24 h … +24 h (48 Stundenwerte); „Jetzt"-Markierung vorhanden.
- Vergangenheits-Balken stammen aus den (gemockten) **Archiv-Daten**, nicht aus dem Forecast.

### `tests/ui/test_telegram_ui.py` (Erweiterung)

- Button `💧 Gießcheck` und `/giesscheck` lösen denselben Handler aus.
- Kein Wetter-Cache → Fehlermeldung via `send_message`.
- Normaler Pfad → Nachricht enthält Verdict-Emoji und Faktor.
- `WateringScaled` → `_on_watering_scaled` sendet die Reduktions-Benachrichtigung.

## Nicht im Leistungsumfang (Out of Scope)

- **Boden-Wasserbilanz / „Eimer"-Modell (Modell C)** mit persistentem Defizit und ET-Schätzung — der Goldstandard und Nordstern, aber ein eigenständiges Feature, das sinnvoll auf dem lokalen Regensensor (Feature 0016) aufbaut.
- **Automatische Skalierung manueller Güsse** — bleibt bei Feature 0020 (Rückfrage „Trotzdem gießen?").
- **Boost > 100 %** (über den geplanten Wert hinaus) — bewusst ausgeschlossen, konsistent mit dem Überflutungsschutz.
- **Quellen-abhängiger Vertrauens-Discount** — nur die Naht (`rain_last_source` als Input) wird gelegt.
- **Durable Reduktions-Begründung in Historie/Tagesbericht** — kleiner Folgepunkt; Report-Integration ist ohnehin separat.
- **Per-Ventil- / Per-Beet-Empfehlung** (erfordert Feature 0008 — Gartenmodell).
- **Echte Messwerte für die Hitzestrecke** (`MAX(current_temp)` statt gespeichertem Forecast-Tagesmax) — bewusst nicht gewählt; gespeicherte Tagesmaxima genügen.

## Weitere Anmerkungen (Further Notes)

- ADR 0021 (pure Funktion in `core/`), ADR 0022 (datums-aware Hitzestrecke), ADR 0024 (gemessene Vergangenheit vs. Vorhersage getrennt), ADR 0020 (Cache-first), ADR 0008 (Ereignis-Kanal), ADR 0028 / Feature 0016 (Regensensor als künftige Quelle), ADR 0029 (Design-System), ADR 0030 (Konfigurationstrennung).
- Dieses Feature löst die bisher rein binäre Überspringlogik durch eine graduierte Steuerung ab; der binäre Skip bleibt als Sonderfall (Faktor 0 %) und als `should_skip_watering()`-Wrapper erhalten.
- **Kandidat für eine ADR:** der Übergang von binärem Skip zu graduierter Gieß-Steuerung (Modell A) — abgewogen gegen Modell B (diskrete Verdict-Stufen) und Modell C (Boden-Wasserbilanz).
- Recherche-Grundlage für `RAIN_THRESHOLD_MM = 3.0` und die Hitze-Spanne: UF/IFAS AE221 (Rain Sensors), LSU AgCenter Pub. 3365, Grijseels et al. 2023 (Evapotranspiration of Residential Lawns). Smart-Controller-Defaults: 1/4″ (≈ 6.4 mm) regulär, 1/8″ (≈ 3.2 mm) wassersparend.
