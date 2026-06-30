# 37. Tagesbericht nach Zeitachse gliedern (Rückblick → Ausblick → Zustand)

Wir strukturieren den **Tagesbericht** entlang einer klaren Zeitachse: ein Rückblick-Block
(`*Gestern*`), ein Ausblick-Block (`*Heute*`) und der System-Zustand als Abschluss. Daten
werden nach **Zeitbezug** gruppiert statt nach Zufall der bisherigen Reihenfolge.

## Kontext

Der bisherige Tagesbericht mischte Zeitebenen innerhalb weniger Zeilen: Wettervorhersage
(heute), Guss-Bilanz (gestern/letzte 24 h), gefallener Regen und Ø/max-Temperatur (letzte
24 h, lokaler Sensor) sowie Systemzustand und Sensor-Akku (jetzt) standen ungeordnet
nebeneinander. Konkrete Folgen:

- Die Regensensor-Zeile stand **nach** dem Abschluss-Verdikt `✅ System: alles in Ordnung` —
  Inhalt nach der vermeintlichen Schlusszeile.
- Das führende Wetter-Emoji wurde nach erwarteter **Regenmenge** gewählt (`< 0.5 mm → ☀️`),
  nicht nach dem tatsächlichen Himmelszustand → `☀️` neben „Bedeckt / Bewölkt".
- Die Temperatur trug kein 🌡 (Emoji-Semantik), die Regenmenge keine Quellenangabe, obwohl die
  Zeile bei Sensor-Ausfall still auf den Wetter-Dienst zurückfällt.
- Guss-Volumen, gefallener Regen und Temperatur stammen aus **demselben 24-h-Fenster**, standen
  aber optisch getrennt.

Das verbindliche Zielbild (ADR 0029, telegram-design-system.html) sah für den Problemfall vor:
„Issues zuerst, dann Wetter + Bewässerung". Diese Vorgabe wird hier bewusst geändert (siehe
Konsequenzen).

## Entscheidung

- **Zeitachse Rückblick → Ausblick → Zustand.** Drei Blöcke in fester Reihenfolge:
  - **`*Gestern*` (Rückblick)** — zwei kompakte Zeilen im Heute-Stil: **Aktivität**
    (`💧 Guss` inkl. `🌫️ Nebel`, falls genebelt) und **Wetter** (`🌧 Regen · 🌡 Ø/max
    Temperatur`, kombiniert). Quelle ist das 24-h-Fenster.
  - **`*Heute*` (Ausblick)** — einzeilige Vorhersage: die bereits **emoji-präfixierte
    WMO-Beschreibung** (`get_wmo_description`, behebt den ☀️/Bedeckt-Widerspruch) ·
    Temperatur-Spanne · bei Regen die erwartete Menge und Wahrscheinlichkeit, in **eine** Zeile
    gefaltet (kein doppeltes 🌧).
  - **Zustands-Block** — Abschluss: grün `✅ System: alles in Ordnung` (keine Ampel-Headline);
    im Problemfall die Warnungen direkt gelistet (wie bisher). **Neu:** der Regensensor wird zur
    Issue-Quelle im selben Format wie Ventile — `🟡 Regensensor: Batterie schwach (X%)` und
    `⚠️ Regensensor: kein Signal (Watchdog aktiv)`; `_is_report_green` berücksichtigt dafür
    Sensor-Akku und -Watchdog. Der bisherige `🔋`-Akku auf der Regenzeile entfällt.
- **Abschnitts-Überschriften nur fett** (`*Gestern*` / `*Heute*`), kein Emoji — 📅 ist für
  „Zeitplan" reserviert, ☀️ für die Bedingung; die Kategorie-Emojis tragen die Bedeutung auf den
  Datenzeilen.
- **Warnungen am Schluss statt zuvorderst.** Der Bericht erzählt konsequent eine Zeitachse und
  endet mit „wie steht's gerade". Dringlichkeit ist abgedeckt: kritische Lagen (Broker/Dienst
  offline, Watchdog, Anomalie) lösen ohnehin **sofort** eine eigene Echtzeit-Benachrichtigung
  aus; der 08:00-Bericht ist die Zusammenfassung, nicht der Alarmkanal.
- **Messquelle-Kennzeichnung — nur die Ausnahme.** Im Normalfall stammen Regen **und**
  Temperatur vom lokalen Regensensor und tragen **keinen** Tag (stiller Standard). Fällt der
  Sensor aus, liefern **beide** Werte der Wetter-Dienst (Open-Meteo) und tragen den Tag
  `(Open-Meteo)`. Die gestrige Open-Meteo-Temperatur liegt bereits in der vorhandenen
  Wetter-Abfrage (`past_days=1`) — kein Extra-Abruf nötig. Guss (eigene Historie) wird nie
  getaggt. „geschätzt", „(lokal gemessen)" und das benutzersichtbare „ERA5" werden verworfen.
- **Einheiten.** Wassermenge in Klein-`l` (Einheiten-Token des Design-Systems).

## Konsequenzen

- **Amendment zu ADR 0029.** Die Regel „Problemfall zeigt Issues zuerst" wird für den
  Tagesbericht ersetzt durch „Zustand/Warnungen als Abschluss". telegram-design-system.html
  (SOLL) wird entsprechend angepasst; telegram-nachrichten.html (IST) bei der Umsetzung
  (Regel `telegram_messages.md`).
- Die Kern-Formatierung in `daily_report.py` wird neu gegliedert (Gestern-/Heute-/Zustands-Block
  als getrennte, rein testbare Bausteine). Das Wetter-Emoji stammt künftig aus der bestehenden
  emoji-präfixierten `get_wmo_description` (keine neue Tabelle nötig) statt aus der Regenmenge.
- **Quellen-Benennung vereinheitlichen.** Der benutzersichtbare Fallback-Name lautet künftig
  durchgängig `Open-Meteo` (statt teils „ERA5", z. B. in `/status`). Der technische Begriff
  „ERA5-Reanalyse" bleibt im Domänen-Glossar erhalten; benutzersichtbar gilt „Open-Meteo".
- Eine bestehende, katalogisierte Nutzer-Nachricht ändert sich grundlegend — bewusst, da die
  alte Form die Zeitebenen vermischte und teils widersprüchliche Angaben (☀️/Bedeckt) zeigte.
- Bei Sensor-Ausfall fallen Regen **und** Temperatur des Gestern-Blocks auf den Wetter-Dienst
  zurück und tragen gemeinsam einen `(Open-Meteo)`-Tag; die gestrige Open-Meteo-Temperatur liegt
  bereits in der vorhandenen Wetter-Abfrage (`past_days=1`).
- Bewusst **außerhalb des Scopes**: Kamera-Akku als Issue-Quelle bleibt unberücksichtigt; die
  Roh-Geräte-Werte der Problem-Texte (englischer `{abnormal}`-String, `(14%)` ohne Leerzeichen)
  bleiben unverändert.
