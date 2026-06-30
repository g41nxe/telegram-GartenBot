# Implementierungsplan: Feature 0036 — Tagesbericht nach Zeitachse gliedern

Referenz: `docs/features/0036-tagesbericht-nach-zeitachse.md` · ADR 0037 · CONTEXT.md
(Tagesbericht, Gestern-/Heute-/Zustands-Block, Messquelle-Kennzeichnung)

Betroffen: `src/daemon/adapters/daily_report.py`, `src/daemon/adapters/weather.py`,
`src/daemon/ui/telegram_ui.py` & `src/daemon/core/watering_advice.py` (nur ERA5→Open-Meteo),
`docs/design/telegram-design-system.html` (SOLL) & `telegram-nachrichten.html` (IST),
Tests in `tests/adapters/test_daily_report.py`.

## Schritt 1 — Tests (RED)

In `tests/adapters/test_daily_report.py` (Vorbild: bestehende `TestVerbal*`- und
`TestDailyReportDesignSystem`-Klassen):

- **Aktivitätszeile:** Guss-Varianten (1×, N×, nicht bewässert, übersprungen) jeweils mit und
  ohne Nebel-Intervall; Nebel korrekt `·`-angehängt; Wassermenge in Klein-`l`.
- **Wetterzeile:** Normalfall ohne Tag; Sensor-Ausfall → Regen **und** Temperatur von Open-Meteo
  mit **einem** `(Open-Meteo)`-Tag am Zeilenende; 🌡 mit Ø + max.
- **Heute-Zeile:** Emoji aus `get_wmo_description` (z. B. `☁️` bei Code 3, **kein** ☀️);
  erwartete Regenmenge in die Zeile gefaltet (`… mm (… % ☂)`), keine Extrazeile.
- **Zustands-Block:** grün endet mit `✅ System: alles in Ordnung` (keine Ampel-Headline);
  Problemfall listet Issues direkt, inkl. Sensor-Issues im Ventil-Format.
- **`_is_report_green`:** flippt auf Problem bei schwachem Sensor-Akku bzw. aktivem
  Sensor-Watchdog.
- **Reihenfolge:** Gestern → Heute → Zustand; Verdikt steht am Schluss (kein Inhalt danach).

## Schritt 2 — Wetter-Adapter: gestrige Temperatur für den Fallback

- `get_weather_data` um die **gestrige** Ø/max-Temperatur erweitern: `temperature_2m_mean` zur
  `daily`-Abfrage hinzufügen und den Vortags-Index auswählen (`past_days=1` ist bereits gesetzt).
  Rückgabe minimal erweitern (oder Helfer), sodass `daily_report` bei Sensor-Ausfall Ø + max von
  gestern aus Open-Meteo bekommt. Forecast-Fall (API-Ausfall) bleibt sicher (Defaults).

## Schritt 3 — Gestern-Block: zwei reine Formatierer

- **Aktivitätszeile** `_format_gestern_aktivitaet(...)`: `💧 <Guss>` plus `· 🌫️ <N> Fenster ·
  <Min>`, falls genebelt. Guss-Skip ohne doppelte mm-Zahl (`💧 Guss übersprungen (Regen)`).
- **Wetterzeile** `_format_gestern_wetter(...)`: `🌧 <mm> · 🌡 Ø <avg> °C, max <max> °C`. Quelle:
  lokaler Sensor → ohne Tag; Sensor-Ausfall → Open-Meteo-Werte + ein `(Open-Meteo)` am Ende.

## Schritt 4 — Heute-Block: eine Vorhersagezeile

- `_format_heute(...)`: `<get_wmo_description(code)> · <min>–<max> °C · [<mm> ](<prob> % ☂)`.
  Das regenmengen-basierte Emoji (`☀️/🌦/🌧`) und die separate „… mm erwartet"-Zeile entfallen.

## Schritt 5 — Zustands-Block + Regensensor als Issue-Quelle

- Grün: `✅ System: alles in Ordnung`. Problem: Issues direkt gelistet (Dienst, Ventile) — wie
  heute, **ohne** Ampel-Headline.
- **Sensor-Issues** im Ventil-Format ergänzen: `🟡 Regensensor: Batterie schwach (X%)` und
  `⚠️ Regensensor: kein Signal (Watchdog aktiv)`. Datenquelle: `get_last_rain_measurement()`
  (Akku) und das Sensor-Watchdog-Metadaten-Flag (Schlüssel im Code verifizieren).
- `_is_report_green()` zusätzlich gegen Sensor-Akku (`BATTERY_WARNING_THRESHOLD`) und
  Sensor-Watchdog prüfen.
- Toten Code entfernen: `_valve_warnings`, `_camera_warnings`, sowie die nicht mehr genutzte
  `_format_rain_sensor_line` (der `🔋`-Akku der Regenzeile entfällt).

## Schritt 6 — Zusammenbau `generate_daily_report`

- Blöcke in fester Reihenfolge **Gestern → Heute → Zustand** zusammensetzen. Die bisherigen
  nachgelagerten `rain_sensor_line`/`nebel_line`-Anhänge entfernen (Nebel steckt jetzt in der
  Aktivitätszeile).

## Schritt 7 — Benennung vereinheitlichen (ERA5 → Open-Meteo)

- Benutzersichtbare „ERA5"-Strings auf „Open-Meteo" umstellen:
  `daily_report.py` (Wetter-/Sensor-Texte), `telegram_ui.py` (/status: „Regen-24h via ERA5"),
  `watering_advice.py` (Quell-Label `measured`). Technischer Glossar-Begriff bleibt.

## Schritt 8 — Design-Doku

- **SOLL** (`telegram-design-system.html`): beide Tagesbericht-Karten auf das finale Format
  (kombinierte Wetterzeile, Nebel in Aktivitätszeile, `✅`-grün ohne Headline, Sensor-Issues im
  Ventil-Format, kein `🔋` auf der Regenzeile).
- **IST** (`telegram-nachrichten.html`): bei der Umsetzung mitpflegen (Regel
  `telegram_messages.md`).

## Schritt 9 — Coverage & Abschluss

- `.\scripts\run_coverage.ps1` — Coverage darf nicht regredieren.

## Definition of Done

- [ ] Alle Tests grün (bestehende + neue), Coverage nicht regriert
- [ ] Gestern-Block = Aktivitäts- + Wetterzeile; Nebel in der Aktivitätszeile
- [ ] Heute-Emoji aus `get_wmo_description`; erwartete Regenmenge gefaltet
- [ ] Zustand am Schluss; grün `✅ System: alles in Ordnung` ohne Ampel-Headline
- [ ] Regensensor als Issue-Quelle im Ventil-Format; `_is_report_green` erweitert
- [ ] Open-Meteo-Fallback für Regen **und** Temperatur, gemeinsamer `(Open-Meteo)`-Tag
- [ ] Wassermenge in Klein-`l`; „ERA5" benutzersichtbar durch „Open-Meteo" ersetzt
- [ ] Toter Code (`_valve_warnings`, `_camera_warnings`, `_format_rain_sensor_line`) entfernt
- [ ] `telegram-design-system.html` (SOLL) und `telegram-nachrichten.html` (IST) aktualisiert
- [ ] Beads-Issue geschlossen
- [ ] Feature- und Plan-Dokument nach `completed/` verschoben
