# Feature: Morgen-Bericht Redesign & Status-Schärfung

## Problemstellung (Problem Statement)

Der tägliche Statusbericht (`/report`, automatisch um 08:00 Uhr) hat eine unklare Zielgruppe: Er mischt Gärtner-relevante Zusammenfassungen (Wie viel wurde bewässert? Kommt heute Regen?) mit technischen Metriken (Ø 187 LQI, 48 Meldungen, max. 2h Funkstille), die im Normalfall kein Handeln erfordern. Das Ergebnis: Die Nachricht ist täglich gleich lang und gleich detailliert — egal ob alles problemlos läuft oder ein Gerät ausgefallen ist. Der Nutzer gewöhnt sich an die Länge, liest oberflächlich, und verpasst den Tag, an dem etwas wirklich drin steht.

Der Status (`/status`) beantwortet nicht die wichtigste Folgefrage nach der Ampel: *Wann kommt der nächste Guss?* Außerdem enthält er englische Begriffe ("schedule", "manual") in einem deutschen Interface und zeigt eine Versionszeile, die keinen Informationswert für den täglichen Gebrauch hat.

## Lösung (Solution)

Der Morgen-Bericht wird kontextsensitiv: Wenn alle Systemkomponenten im Normalzustand sind, fasst er sich in 3–4 Zeilen — Wetter, Bewässerung gestern, System OK. Gibt es ein Problem (Batterie, Anomalie, Watchdog, Systemdienst), expandiert der Bericht automatisch und stellt genau die betroffenen Details in den Vordergrund. Technische Metriken (LQI-Zahlenwert, Meldungsanzahl) verschwinden dauerhaft aus dem Bericht; stattdessen wird Signal-Qualität als lesbares Label kommuniziert.

Der Status erhält eine neue Sektion "Nächster Guss" und wird um Rauschen bereinigt: Versionsnummer entfällt, Dienste-Status erscheint nur bei nicht-grünem Systemzustand, Quell-Bezeichnungen werden eingedeutscht, Bewässerungs-Einträge bekommen das Volumen.

## User Stories

1. Als Gärtner möchte ich den Morgen-Bericht auf einen Blick erfassen können, ohne lange Texte lesen zu müssen, wenn alles gut läuft.
2. Als Gärtner möchte ich beim Morgen-Bericht sofort sehen, ob etwas Aufmerksamkeit erfordert, ohne das Problem in einer langen Liste suchen zu müssen.
3. Als Gärtner möchte ich im Morgen-Bericht wissen, ob gestern bewässert wurde und wie viel Wasser geflossen ist.
4. Als Gärtner möchte ich im Morgen-Bericht wissen, ob heute Regen erwartet wird, damit ich entscheiden kann, ob ich manuell gießen muss.
5. Als Gärtner möchte ich im Morgen-Bericht einen Hinweis sehen, wenn ein Zeitplan wegen Regen übersprungen wurde.
6. Als Gärtner möchte ich im Morgen-Bericht eine Warnung sehen, wenn die Batterie eines Ventils schwach ist — aber nur dann, wenn das tatsächlich der Fall ist.
7. Als Gärtner möchte ich im Morgen-Bericht keine technischen Metriken wie LQI-Zahlenwerte oder Meldungsanzahlen sehen, solange der Betrieb normal läuft.
8. Als Gärtner möchte ich beim Lesen des Morgen-Berichts das Gefühl haben, dass der Bot für mich arbeitet — der Ton soll freundlich sein, nicht bürokratisch.
9. Als Gärtner möchte ich im Status-Befehl sehen, wann der nächste Bewässerungs-Zeitplan ausgeführt wird, damit ich weiß, ob mein Garten versorgt ist.
10. Als Gärtner möchte ich im Status-Befehl deutsche Bezeichnungen für den Bewässerungs-Ursprung sehen ("Zeitplan" statt "schedule", "Manuell" statt "manual").
11. Als Gärtner möchte ich in der Bewässerungs-Historie die geflossene Wassermenge in Litern sehen, nicht nur die Dauer.
12. Als Gärtner möchte ich die Versionsangabe nicht im Status sehen — sie gehört in eine separate Info-Ansicht.
13. Als Gärtner möchte ich den Dienste-Status ("MQTT aktiv") im Status nur dann sehen, wenn er nicht grün ist — bei normaler Lage lenkt er ab.
14. Als Gärtner möchte ich, dass der automatische 08:00-Bericht und der manuell ausgelöste `/report`-Befehl identisch aussehen.

## Implementierungs-Entscheidungen (Implementation Decisions)

### Grün-Bedingung für den Morgen-Bericht

Ein Bericht gilt als "grün" (Kurzform), wenn alle folgenden Bedingungen gleichzeitig erfüllt sind:
- Systemdienste: MQTT-Broker verbunden und Mittelweg-Dienst (Zigbee2MQTT) online — oder Simulationsmodus aktiv
- Kein aktiver Watchdog-Alert für irgendein Ventil (geprüft via Metadata-Flag)
- Kein Ventil im abnormalen Zustand (`valve_abnormal_state == "normal"` für alle)
- Batterie aller Ventile über `BATTERY_WARNING_THRESHOLD`

Trifft mindestens eine Bedingung nicht zu, wird die erweiterte Darstellung verwendet.

### Grün-Kurzform (3–4 Zeilen)

```
🌿 *Guten Morgen, {Wochentag} {TT.MM.}!*

{Wetter-Zeile}
{Bewässerungs-Zeile}
✅ System: alles in Ordnung
```

**Wetter-Zeile:**
- Basisformat: `☀️ Heute {temp_min}–{temp_max} °C · {kurze Beschreibung} ({rain_prob} % ☂)`
- Wenn `rain_next >= 0.5 mm` und kein Skip: zusätzliche Zeile `🌧 Heute {rain_next} mm erwartet`
- Wenn Zeitplan übersprungen wurde: `🌧 Heute {rain_next} mm — Guss '{Name}' pausiert`

**Bewässerungs-Zeile:**
- 1 Guss: `💧 Gestern 1× bewässert · {volume} L`
- N Güsse: `💧 Gestern {n}× bewässert · {volume} L gesamt`
- Kein Guss, kein Skip: `💧 Gestern nicht bewässert`
- Skip wegen Regen (und kein Fehler): `🌧 Guss übersprungen · {rain_last} mm gefallen`

### Problem-Darstellung (expandiert)

Reihenfolge im Problem-Block nach Schwere:
1. 🔴 Systemdienst-Ausfall (Broker / Mittelweg-Dienst)
2. 🚨 Ventil-Anomalie
3. 🟡 Batterie unter Schwellenwert
4. ⚠️ Watchdog-Alert (Funkstille)

Pro betroffenes Ventil eine Problem-Zeile. Nicht betroffene Ventile erscheinen nicht.

Diagnose-Zeile pro Ventil (nur bei Problem): Signal-Qualität als Label ohne Zahlenwert — "gut", "ausreichend", "schwach", "keine Verbindung". Kein LQI-Wert, keine Meldungsanzahl, keine `max_gap_hours` (außer bei aktivem Watchdog-Alert: "seit {X}h kein Signal").

### Entfernte Felder (dauerhaft)

Folgende Felder werden aus dem Morgen-Bericht dauerhaft entfernt:
- LQI-Zahlenwert (Ø 187 LQI)
- Meldungsanzahl
- `max_gap_hours` (außer Watchdog-Fall)
- `mqtt_name`
- Header "Täglicher Statusbericht vom…"

### /status — Neue Sektion "Nächster Guss"

Neue Sektion zwischen Ventile und Wetter. Berechnung: aus allen aktiven Zeitplänen wird derjenige ermittelt, der als nächstes feuert, ausgehend von der aktuellen Uhrzeit und den eingetragenen Wochentagen.

Format: `⏰ Nächster Guss: {heute|morgen} {HH:MM} Uhr · {Name} · {Dauer} Min`

Kein aktiver Zeitplan → Sektion entfällt.

### /status — Bereinigungen

- Versionszeile `v{x.y.z}` entfällt
- `🔌 Dienste: 🟢 Aktiv` wird nur bei nicht-grünem Systemzustand eingeblendet (Progressive Disclosure)
- Quell-Bezeichnungen in "Zuletzt": "schedule" → "Zeitplan", "manual" → "Manuell"
- "Zuletzt"-Einträge: Volumen in Litern ergänzen: `✅ 17.06. 06:00 · 12 Min · 30 L · Zeitplan`

### Befehlsnamen und Aliase

Keine Änderung: `/report` und `/statusbericht` bleiben als Aliase erhalten. Automatischer 08:00-Bericht und manuell ausgelöster `/report` verwenden dieselbe Generierungsfunktion.

### Modul-Änderungen

- `adapters/daily_report.py`: Grün-Prüf-Logik + zwei separate Format-Pfade (Kurzform / Problemfall)
- `ui/telegram_ui.py` (`handle_status`): Nächste-Bewässerung-Sektion, Bereinigungen
- `docs/reference/telegram-nachrichten.html`: Alle neuen und geänderten Nachrichten synchron aktualisieren (Pflicht gemäß Design-System-Regel)

## Test-Entscheidungen (Testing Decisions)

**Was einen guten Test ausmacht:** Nur das externe Verhalten testen — die Ausgabe-Strings und die Bedingungen, unter denen sie entstehen. Keine Assertions auf interne Hilfsfunktions-Namen oder Modul-Interna.

**Primäre Nahtstelle: `generate_daily_report()`**

Die Funktion gibt einen String zurück — an diesem Output-String greifen alle Tests an. Das entspricht dem bestehenden Testmuster in `tests/adapters/` und `tests/test_irrigation.py`.

Szenarien, die gedeckt sein müssen:
- Grün-Fall: Ausgabe enthält "Guten Morgen", kein LQI-Zahlenwert, keine Meldungsanzahl, genau 3–4 inhaltliche Zeilen
- Problem-Fall Batterie: Batterie-Warnung erscheint, nicht betroffene Ventile erscheinen nicht
- Problem-Fall Watchdog: Alert mit "seit Xh kein Signal" erscheint
- Problem-Fall Systemdienst: Systemausfall-Zeile erscheint zuerst
- Regen-Skip im Grün-Fall: "Guss übersprungen" erscheint in Bewässerungs-Zeile
- LQI-Zahlenwert nie im Output (auch nicht im Problem-Fall)

**Sekundäre Nahtstelle: Grün-Prüf-Logik**

Die Funktion, die bestimmt ob Kurzform oder Problemfall, ist eine reine Funktion (keine I/O) — direkt unit-testbar mit kontrollierten Eingaben.

**Sekundäre Nahtstelle: Nächster-Guss-Berechnung**

Neue reine Funktion ohne I/O — testbar mit Dummy-Zeitplänen und kontrollierten Uhrzeiten. Testfälle: heute noch ein Guss, heute kein Guss mehr (Sprung auf morgen), keine aktiven Zeitpläne.

**Referenz-Testmuster:** `tests/adapters/test_daily_report.py` (falls vorhanden) und `tests/ui/test_telegram_ui.py` für Status-Tests.

## Nicht im Leistungsumfang (Out of Scope)

- Neue Befehle oder Umbenennungen (`/diagnose`, `/bericht`)
- Langzeit-Trending oder Statistiken (Wasserverbrauch über mehrere Tage)
- Änderungen am Wetter-Chart (QuickChart.io bleibt unverändert)
- Push-Benachrichtigungen basierend auf Bericht-Inhalten
- Kamera-Abschnitt im Bericht (bleibt unverändert)
- Änderungen an der Bewässerungs-Logik oder den Zeitplänen

## Weitere Anmerkungen (Further Notes)

Der Name "Morgen-Bericht" ist intern — nach außen heißt der Befehl weiterhin `/report`. Die freundliche Anrede "Guten Morgen!" folgt dem Ton-Register "verspielt/neutral-freundlich" aus ADR 0029 (Design-System), das für Push-Benachrichtigungen und tägliche Zusammenfassungen vorgesehen ist.

Die `telegram-nachrichten.html` muss im selben Commit aktualisiert werden, der die neuen Nachrichten einführt — dies ist Pflicht gemäß `.claude/rules/telegram_messages.md`.
