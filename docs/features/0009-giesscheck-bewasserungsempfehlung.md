# Feature: Gießcheck — Bewässerungs-Empfehlung

## Problemstellung (Problem Statement)

Der Bewässerungs-Daemon verfügt über Wetterdaten und Bewässerungshistorien, zieht daraus aber keine nutzbaren Schlüsse. Der tägliche Statusbericht zeigt Zahlen (Niederschlag letzte 24h, Vorhersage, Temperatur) — er bewertet sie nicht. Der Benutzer muss selbst entscheiden, ob heute gegossen werden soll, und trägt dabei das Risiko, Hitzeperioden zu übersehen, weil kein einzelner Datenpunkt den kumulierten Bodenfeuchte-Verlust über mehrere heiße Tage abbildet.

## Lösung (Solution)

Ein neuer Telegram-Befehl `/giesscheck` gibt auf Anfrage eine **Gieß-Empfehlung** mit kurzem Begründungstext aus. Die Empfehlung wird über einen neuen Hauptmenü-Button `💧 Gießcheck` zugänglich gemacht. Sie basiert auf drei unabhängigen Signalen: dem Regen-Fenster (Niederschlag der letzten + nächsten 24h), der heutigen Höchsttemperatur und der **Hitzestrecke** (Anzahl aufeinanderfolgender abgeschlossener Vortage über dem konfigurierten Temperaturschwellenwert). Das Ergebnis ist ein Verdict (vier Stufen) mit 1–3 erklärenden Sätzen — keine reinen Datenpunkte, sondern verständlicher Kontext.

## User Stories

1. Als Benutzer des Telegram-Bots möchte ich über den Button `💧 Gießcheck` im Hauptmenü eine Bewässerungs-Empfehlung abrufen können, ohne einen Befehl tippen zu müssen.
2. Als Benutzer möchte ich denselben Befehl auch als `/giesscheck` tippen können, damit er in der Telegram-Befehlsliste auffindbar ist.
3. Als Benutzer möchte ich ein klares Verdict erhalten (`✅ Kein Gießen nötig`, `ℹ️ Situationsabhängig`, `⚠️ Gießen empfohlen`, `🔴 Dringend gießen`), damit ich auf einen Blick die Dringlichkeit erkenne.
4. Als Benutzer möchte ich zum Verdict 1–3 erklärende Sätze sehen (z.&nbsp;B. „Kein nennenswerter Regen in den letzten/nächsten 48h (0.6&nbsp;mm gesamt). Temperatur heute 28°C. Bereits 4 heiße Tage in Folge."), damit ich die Begründung verstehe, ohne selbst die Zahlen interpretieren zu müssen.
5. Als Benutzer möchte ich, dass eine mehrtägige Hitzeperiode auch dann als erhöhter Bedarf gemeldet wird, wenn heute zufällig etwas kühler ist, damit kumulierter Bodenfeuchte-Verlust nicht übersehen wird.
6. Als Benutzer möchte ich eine verständliche Fehlermeldung erhalten, wenn noch keine Wetterdaten in der Datenbank vorhanden sind (z.&nbsp;B. direkt nach der Erstinstallation).
7. Als Benutzer möchte ich die Temperaturschwelle für einen „heißen Tag" und die Mindestanzahl aufeinanderfolgender heißer Tage über Umgebungsvariablen konfigurieren können, damit ich die Empfehlung an meinen Standort anpassen kann.

## Implementierungs-Entscheidungen (Implementation Decisions)

### Architektur

- Die Bewertungslogik lebt als pure Funktion `evaluate()` in `core/watering_advice.py` — kein I/O, kein Zustand, keine Adapter-Abhängigkeiten (ADR-0021). Beide möglichen Aufruforte (Telegram-Handler, zukünftige Tagesbericht-Integration) rufen dieselbe Funktion auf.
- **Koordination mit Feature 0014:** Falls 0014 vor diesem Feature umgesetzt wird, legt es `core/watering_advice.py` bereits an und liefert dort `evaluate_rain_window(rain_last_mm, rain_next_mm, threshold_mm)` als pure Basis-Entscheidung für das Regen-Fenster. Das Signal „Regen-Fenster trocken" (siehe unten) soll dann **diese Funktion wiederverwenden** statt die Schwellenwert-Logik zu duplizieren; `evaluate()` komponiert sie und legt Temperatur und Hitzestrecke darüber.
- Der Telegram-Handler lebt in `ui/telegram_ui.py`, konsistent mit allen anderen Befehlen.

### Signale und Verdict-Matrix

`evaluate()` empfängt: `rain_last_24h_mm`, `rain_next_24h_mm`, `temp_max_today`, `past_daily_temps: list[tuple[str, float]]` (Vortage ohne heute, neueste zuerst).

Drei Signale:
- **Regen-Fenster trocken:** `rain_last_24h_mm + rain_next_24h_mm < RAIN_THRESHOLD_MM` (bestehendes Config-Feld, kein neues nötig)
- **Heiß heute:** `temp_max_today >= GIESSCHECK_HOT_TEMP_C`
- **Hitzestrecke aktiv:** datums-aware Zähler aufeinanderfolgender Vortage ≥ `GIESSCHECK_HOT_TEMP_C`, ab `GIESSCHECK_HOT_DAYS_COUNT` Tagen positiv (ADR-0022)

Verdict-Matrix:

| Regen-Fenster trocken | Heiß heute | Hitzestrecke aktiv | Verdict |
|-----------------------|------------|---------------------|---------|
| ❌ | beliebig | beliebig | `✅ Kein Gießen nötig` |
| ✅ | ❌ | ❌ | `ℹ️ Situationsabhängig` |
| ✅ | ❌ | ✅ | `⚠️ Gießen empfohlen` |
| ✅ | ✅ | ❌ | `⚠️ Gießen empfohlen` |
| ✅ | ✅ | ✅ | `🔴 Dringend gießen` |

### Datenbank

Neue Funktion `get_daily_max_temps(days: int = 5) -> list[tuple[str, float]]`:
- Gruppiert `weather_history` nach Kalendertag (`date(timestamp)`).
- Schließt den heutigen Tag aus (`WHERE date(timestamp) < date('now')`), da nur abgeschlossene Tage für die Hitzestrecke relevant sind.
- Gibt `(date_str, MAX(temp_max))` pro Tag zurück, neueste zuerst.
- Tage ohne Einträge (z.&nbsp;B. Steuerzentrale offline) werden übersprungen — kein Padding. `evaluate()` erkennt Lücken anhand der Datumsdifferenz und bricht die Hitzestrecke ab.

### Konfiguration

Zwei neue Variablen (mit Standardwerten, die auf DWD-Definitionen und dt. Gartenliteratur basieren):
- `GIESSCHECK_HOT_TEMP_C=25.0` — Temperaturschwelle für einen „heißen Tag" (DWD: warmer Tag ≥ 25°C)
- `GIESSCHECK_HOT_DAYS_COUNT=3` — Mindest-Hitzestrecke für `🔴 Dringend gießen`

`RAIN_THRESHOLD_MM` (bereits vorhanden, Standard: 3.0&nbsp;mm) wird direkt wiederverwendet — kein neues Konzept nötig.

### Telegram-UX

Hauptmenü-Keyboard wird von drei auf drei Zeilen umgebaut (gleiche Anzahl, andere Anordnung):

```
[ 📊 Status anzeigen  ] [ 💧 Gießcheck        ]
[ 🟢 Bewässern starten] [ 🔴 Sofort Stopp     ]
[ 📅 Zeitpläne        ] [ 🔧 Ventil koppeln   ]
```

Der Handler matcht sowohl Button-Text als auch Slash-Befehl:
```python
elif text == "💧 Gießcheck" or text.startswith("/giesscheck"):
```

`"💧 Gießcheck"` wird in beide Wizard-Abbruchlisten in `on_telegram_update` aufgenommen, damit ein laufender Wizard beim Antippen des Buttons abbricht.

Antwort-Format: Verdict-Zeile, Leerzeile, Begründungspunkte als erklärende Sätze (nicht reine Datenpunkte).

## Test-Entscheidungen (Testing Decisions)

Getestet wird ausschließlich das **externe Verhalten** — was gibt die Funktion zurück, welche Nachricht wird gesendet. Keine Assertions auf SQL-Queries oder interne Zustände.

### `tests/core/test_watering_advice.py` (neue Datei)

Pure-Funktions-Tests ohne jegliche Mocks. Referenz-Pattern: `tests/core/test_watering_controller.py`.

Szenarien (alle fünf Zeilen der Verdict-Matrix):
- Ausreichend Regen → `✅ Kein Gießen nötig`, unabhängig von Temperatur und Streak
- Trocken + mild + kein Streak → `ℹ️ Situationsabhängig`
- Trocken + heute kalt + Hitzestrecke (3 konsekutive Vortage) → `⚠️ Gießen empfohlen`
- Trocken + heiß heute + kein Streak → `⚠️ Gießen empfohlen`
- Trocken + heiß heute + Hitzestrecke → `🔴 Dringend gießen`
- Hitzestrecke bricht bei Datumslücke ab (fehlender Tag zwischen zwei Einträgen)
- Hitzestrecke bricht bei einem kühlen Vortag ab
- Leere `past_daily_temps`-Liste → kein Streak, kein Absturz

### `tests/adapters/test_database.py` (Erweiterung)

Referenz-Pattern: bestehende DB-Tests mit temporärer SQLite-Datei in `setUp`/`tearDown`.

Szenarien:
- `get_daily_max_temps()` gibt Einträge neueste zuerst zurück
- Heutiger Tag wird nicht zurückgegeben
- Tage ohne Einträge erzeugen keine Lücken-Einträge (kein Padding)
- Rückgabe ist leer, wenn keine Wetterdaten vorhanden

### `tests/ui/test_telegram_ui.py` (Erweiterung)

Referenz-Pattern: bestehende `_process_message()`-Tests. Telegram-Client-Sendefunktionen werden via `patch` gemockt (ADR-0017).

Szenarien:
- Button `"💧 Gießcheck"` und Befehl `/giesscheck` lösen denselben Handler aus
- Kein Wetter-Cache → `send_message` wird mit Fehlermeldung aufgerufen
- Normaler Pfad → `send_message` wird aufgerufen und der Nachrichtentext enthält das Verdict-Emoji

## Nicht im Leistungsumfang (Out of Scope)

- Integration der Gieß-Empfehlung in den täglichen Statusbericht (`daily_report.py`) — separates Follow-up-Feature
- Per-Ventil- oder Per-Beet-Empfehlung (erfordert Feature 0008 — Gartenmodell)
- Automatisches Auslösen einer Bewässerung auf Basis der Empfehlung
- Push-Benachrichtigung bei kritischer Empfehlung
- Interpolation fehlender Wetterdaten bei Steuerzentrale-Ausfall

## Weitere Anmerkungen (Further Notes)

- ADR-0021 dokumentiert, warum die Bewertungslogik in `core/` und nicht im Handler lebt.
- ADR-0022 dokumentiert, warum die Hitzestrecke datums-aware und nicht list-index-basiert berechnet wird.
- Der Design-Spec liegt unter `docs/superpowers/specs/2026-06-14-giesscheck-design.md` und enthält die vollständige Verdict-Matrix, Begründungszeilen-Beispiele und die Herleitung der Standardwerte.
