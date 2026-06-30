# Feature: Tagesbericht nach Zeitachse gliedern

Referenz: ADR 0037 · CONTEXT.md (Tagesbericht, Gestern-Block, Heute-Block, Zustands-Block,
Messquelle-Kennzeichnung) · Amendment zu ADR 0029 (Telegram-Design-System)

## Problemstellung (Problem Statement)

Der tägliche **Tagesbericht** (08:00 Uhr) mischt Zeitebenen innerhalb weniger Zeilen:
Wettervorhersage (heute), Guss-Bilanz (gestern), gefallener Regen und Ø/max-Temperatur (letzte
24 h, lokaler Sensor) sowie Systemzustand und Sensor-Akku (jetzt) stehen ungeordnet
nebeneinander. Konkret stört:

- Die Regensensor-Zeile steht **nach** dem Abschluss-Verdikt `✅ System: alles in Ordnung`.
- Das führende Wetter-Emoji richtet sich nach der erwarteten **Regenmenge**, nicht nach dem
  Himmelszustand → `☀️` neben „Bedeckt / Bewölkt".
- Die Temperatur trägt kein 🌡; die Regenmenge keine Quellenangabe, obwohl die Zeile bei
  Sensor-Ausfall still auf den Wetter-Dienst zurückfällt.
- Guss, gefallener Regen und Temperatur stammen aus demselben 24-h-Fenster, stehen aber getrennt.
- Wassermenge als `245 L` (Großbuchstabe, gegen das Einheiten-Token `l`).

## Lösung (Solution)

Der Tagesbericht wird entlang einer klaren **Zeitachse Rückblick → Ausblick → Zustand**
gegliedert — ohne neue Entscheidungslogik, nur eine konsistente Darstellung:

- **`*Gestern*` (Rückblick)** — zwei kompakte Zeilen im `·`-gebündelten Stil: eine
  **Aktivitätszeile** (`💧 Guss` inkl. `🌫️ Nebel-Intervall`, falls genebelt) und eine
  **Wetterzeile** (`🌧 Regen · 🌡 Ø/max Temperatur`).
- **`*Heute*` (Ausblick)** — eine Vorhersagezeile: emoji-präfixierte WMO-Beschreibung ·
  Temperatur-Spanne · bei Regen erwartete Menge und Wahrscheinlichkeit (in die Zeile gefaltet).
- **Zustands-Block** (Abschluss) — grün `✅ System: alles in Ordnung`; im Problemfall die
  Warnungen direkt gelistet. Der Regensensor wird zur Issue-Quelle im selben Format wie ein
  Ventil.

Quellen-Tag nur als Ausnahme: Normalfall ohne Tag, bei Sensor-Ausfall tragen Regen **und**
Temperatur gemeinsam `(Open-Meteo)`.

## User Stories

1. Als Bot-Nutzer möchte ich, dass der Tagesbericht zuerst zeigt, was **gestern** war, dann was
   **heute** kommt, und zum Schluss **wie es gerade steht**, damit der Bericht einer klaren
   Zeitachse folgt.
2. Als Bot-Nutzer möchte ich Guss und Nebel-Intervalle **gemeinsam** in einer Aktivitätszeile
   sehen, weil beide gestrige Ventil-Aktivitäten sind.
3. Als Bot-Nutzer möchte ich gefallenen Regen und die Ø/max-Temperatur in **einer** Wetterzeile
   sehen, weil sie aus derselben Messung stammen.
4. Als Bot-Nutzer möchte ich, dass das Heute-Emoji den **tatsächlichen Himmelszustand** zeigt
   (nicht die Regenmenge), damit `☀️` nicht neben „Bedeckt" steht.
5. Als Bot-Nutzer möchte ich die erwartete Regenmenge **in der Heute-Zeile** statt in einer
   Extrazeile, damit der Ausblick einzeilig bleibt.
6. Als Bot-Nutzer möchte ich, dass der Systemzustand **am Schluss** des Berichts steht, da
   kritische Lagen ohnehin sofort als Echtzeit-Benachrichtigung kommen.
7. Als Bot-Nutzer möchte ich im Normalfall **keine** Quellenangabe an der Wetterzeile, damit der
   Block ruhig bleibt.
8. Als Bot-Nutzer möchte ich bei **Sensor-Ausfall** sehen, dass Regen und Temperatur vom
   Wetter-Dienst stammen (`(Open-Meteo)`), damit ich die Daten einordnen kann.
9. Als Bot-Nutzer möchte ich, dass auch die **gestrige Temperatur** angezeigt wird, wenn der
   Sensor ausfällt (Fallback auf den Wetter-Dienst), statt dass die Angabe verschwindet.
10. Als Bot-Nutzer möchte ich einen **schwachen Sensor-Akku** oder einen **stummen Sensor** als
    Warnung im selben Format wie bei Ventilen sehen, damit ich rechtzeitig reagieren kann.
11. Als Bot-Nutzer möchte ich die Wassermenge in Klein-`l` sehen (konsistent mit dem
    Design-System).
12. Als Bot-Nutzer möchte ich, dass der Bericht im Normalfall **kompakt** bleibt (grün:
    Aktivitäts-, Wetter-, Heute- und eine Verdikt-Zeile).

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Reine Formatierungs-Bausteine.** Die Block-Formatierung in `daily_report.py` wird in
  getrennte, rein testbare Funktionen gegliedert (Aktivitätszeile, Wetterzeile, Heute-Zeile,
  Zustands-Block). Keine neue Entscheidungslogik im Scheduler oder Core.
- **Heute-Emoji aus `get_wmo_description`.** Diese Funktion liefert die Beschreibung bereits
  **emoji-präfixiert** (`"☁️ Bedeckt / Bewölkt"`); sie ersetzt das regenmengen-basierte Emoji.
  Keine neue WMO→Emoji-Tabelle nötig.
- **Open-Meteo-Fallback für Regen UND Temperatur.** Bei Sensor-Ausfall liefert die bestehende
  Wetter-Abfrage (`past_days=1` enthält bereits gestrige Temperatur und Regen) die Werte; beide
  tragen gemeinsam `(Open-Meteo)`. Im Normalfall kein Tag.
- **Regensensor als Issue-Quelle, Format wiederverwendet.** Im Problemfall erzeugt ein schwacher
  Sensor-Akku bzw. ein aktiver Sensor-Watchdog eine Zeile im exakten Ventil-Format
  (`🟡 Regensensor: Batterie schwach (X%)` / `⚠️ Regensensor: kein Signal (Watchdog aktiv)`).
  `_is_report_green()` berücksichtigt dafür zusätzlich Sensor-Akku und Sensor-Watchdog. Der
  bisherige `🔋`-Akku auf der Regenzeile entfällt.
- **Quellen-Benennung vereinheitlichen.** Benutzersichtbar gilt durchgängig „Open-Meteo" statt
  „ERA5" (auch in `/status` und der Gieß-Empfehlung). Der technische Begriff „ERA5-Reanalyse"
  bleibt im Domänen-Glossar.
- **Design-Doku.** `telegram-design-system.html` (SOLL) wird auf das Zielbild gebracht;
  `telegram-nachrichten.html` (IST) bei der Umsetzung gepflegt (Regel `telegram_messages.md`).
- **Toter Code.** `_valve_warnings`/`_camera_warnings` in `daily_report.py` werden nicht
  aufgerufen; sie können im Zuge der Umstrukturierung entfernt werden.

## Test-Entscheidungen (Testing Decisions)

- **Höchste, bestehende Nahtstelle.** Tests in `tests/adapters/test_daily_report.py` (Vorbild:
  bestehende `TestVerbal*`- und `TestDailyReportDesignSystem`-Klassen). Geprüft wird das
  **sichtbare Verhalten** der reinen Formatierungs-Funktionen bzw. von `generate_daily_report`.
- **Abgedeckte Fälle:** Aktivitätszeile mit/ohne Nebel und Guss-Varianten (1×, N×, nicht
  bewässert, übersprungen); Wetterzeile normal (kein Tag) vs. Sensor-Ausfall (`(Open-Meteo)` auf
  Regen + Temp); Heute-Zeile mit korrektem WMO-Emoji und gefalteter Regenmenge; Zustands-Block
  grün vs. Problem mit Ventil- **und** Sensor-Issues; `_is_report_green` flippt bei Sensor-Akku/
  -Watchdog; Wassermenge in `l`.
- **Design-System-Wächter:** kein `**`-Doppelasterisk (Legacy-Markdown), Verdikt steht am
  Schluss.
- **Coverage** darf nicht regredieren.

## Nicht im Leistungsumfang (Out of Scope)

- **Kamera-Akku als Issue-Quelle** — bleibt unberücksichtigt (wie bisher).
- **Roh-Geräte-Werte der Problem-Texte** — der englische `{abnormal}`-String und `(14%)` ohne
  Leerzeichen bleiben unverändert (echte, etablierte Strings).
- **Keine Ampel-Headline** im Tagesbericht (grün bleibt `✅ System: alles in Ordnung`,
  Problemfall listet Issues direkt — wie heute).
- **Keine neue Entscheidungslogik** für Guss/Skip/Reduzierung.

## Weitere Anmerkungen (Further Notes)

- Bei Sensor-Ausfall signalisieren zwei Dinge denselben Zustand auf verschiedenen Ebenen: der
  `(Open-Meteo)`-Tag (Daten-Herkunft) auf der Wetterzeile und ggf. `⚠️ Regensensor: kein Signal`
  (Geräte-Gesundheit) im Zustands-Block. Das ist gewollt — analog zu einem Ventil, das zugleich
  veraltete Daten und einen Watchdog-Alarm zeigt.
