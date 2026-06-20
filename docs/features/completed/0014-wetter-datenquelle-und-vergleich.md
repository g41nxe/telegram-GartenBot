# Feature: Gemessene Regendaten und deterministischer Vorhersage-Vergleich

## Problemstellung (Problem Statement)

Der Tagesbericht meldete „1.0 mm gefallen", obwohl tatsächlich rund 6 mm Regen fielen. Ursache ist nicht ein Rechenfehler, sondern die **Datenquelle**: Der Bewässerungs-Daemon liest den gefallenen Regen (`rain_last`) aus dem Vorhersage-Produkt des Wetter-Dienstes (Open-Meteo `/v1/forecast`). Dessen Werte für die jüngste Vergangenheit sind Modelldaten, keine Messungen, und werden nicht nachkorrigiert — im untersuchten Fall unterschätzten sie den Regen um den Faktor ~5.

Daraus folgen drei Probleme aus Sicht des Benutzers:

1. **Falsche Überspring-Entscheidung:** Das Regen-Fenster (gefallener + erwarteter Regen) bestimmt, ob ein geplanter Guss übersprungen wird. Mit unterschätztem `rain_last` wird gegossen, obwohl es geregnet hat — der Garten wird überwässert.
2. **Verkehrter Bericht:** Der Abweichungssatz („mehr/weniger Regen als erwartet") vergleicht gestrige Vorhersage gegen heute „gemessenen" Regen. Solange beides Modelldaten sind, ist der Vergleich aussagelos und kann ins Gegenteil verkehrt sein.
3. **Unzuverlässiger Vergleichswert:** Der Vergleich greift den gestrigen Wert über eine unscharfe Zeitfenster-Suche (±6h) aus einer Tabelle, die auch durch manuelles `/report` befüllt wird. Ein `/report` zwischendurch kann die Vergleichsbasis verschieben.

## Lösung (Solution)

Der gefallene Regen kommt künftig aus dem **gemessenen** Produkt des Wetter-Dienstes (Open-Meteo Archiv-/ERA5-Endpunkt), die Vorhersage weiterhin aus dem Forecast-Modell. Damit funktioniert das Regen-Fenster so, wie es die Domäne definiert — als Summe aus *gemessenem* Niederschlag der letzten 24h und *vorhergesagtem* der nächsten 24h.

Der Benutzer erhält dadurch korrekte Überspring-Entscheidungen (kein Gießen nach echtem Regen), einen ehrlichen Bericht (keine erfundene Zahl bei Daten-Ausfall) und einen stabilen, deterministischen Abweichungsvergleich, der von manuellen Berichts-Abrufen nicht mehr beeinflusst wird. Skip-Logik und Chart-Caption treffen ihre Gieß-Aussage über dieselbe Funktion und können sich nicht mehr widersprechen.

## User Stories

1. Als Gartenbesitzer möchte ich, dass ein geplanter Guss übersprungen wird, wenn in den letzten 24h tatsächlich nennenswert Regen gefallen ist, damit mein Garten nicht überwässert wird.
2. Als Gartenbesitzer möchte ich, dass der gefallene Regen im Tagesbericht der real gemessenen Menge entspricht, damit ich der Anzeige vertrauen kann.
3. Als Gartenbesitzer möchte ich, dass der Abweichungssatz („mehr/weniger Regen als erwartet") gestrige Vorhersage gegen heute *gemessenen* Regen vergleicht, damit die Aussage stimmt.
4. Als Gartenbesitzer möchte ich, dass ein manueller `/report`-Abruf zwischendurch den morgigen Vergleich nicht verfälscht, damit der Bericht reproduzierbar bleibt.
5. Als Gartenbesitzer möchte ich, dass die Gieß-Aussage der Chart-Caption und die der Überspring-Logik übereinstimmen, damit ich nicht widersprüchliche Hinweise erhalte.
6. Als Gartenbesitzer möchte ich bei einem Ausfall der gemessenen Regendaten im Bericht einen ehrlichen Hinweis statt einer geschätzten Zahl sehen, damit ich nicht in die Irre geführt werde.
7. Als Gartenbesitzer möchte ich, dass eine geplante Bewässerung auch dann eine Entscheidung trifft, wenn die gemessenen Regendaten gerade nicht abrufbar sind, damit ein Guss nicht ungeprüft durchläuft.
8. Als Gartenbesitzer möchte ich, dass das System bei instabilem WLAN robust bleibt — fällt nur die Messung aus, soll die Vorhersage weiter funktionieren und umgekehrt die bestehende Cache-Logik greifen.
9. Als Gartenbesitzer möchte ich, dass die Regenwahrscheinlichkeit weiterhin im Bericht erscheint, auch nachdem die Datenquelle für gefallenen Regen umgestellt wurde.
10. Als Wartender des Systems möchte ich, dass die Stunden-Zuordnung der Wetterdaten robust gegen Zeitzonen-Versatz ist, damit das 24h-Fenster nicht versehentlich auf Mitternacht statt die aktuelle Stunde verrutscht.

## Implementierungs-Entscheidungen (Implementation Decisions)

### Datenquellen-Trennung (ADR 0024)

- Der Wetter-Dienst-Adapter bezieht zwei Produkte: den gefallenen Regen (`rain_last`) aus dem Archiv-/ERA5-Endpunkt (gemessen, Fenster `[jetzt−24h, jetzt]`), die Vorhersage (`rain_next`, `rain_prob`, Temperatur, Wettercode, Stundenchart) wie bisher aus dem Forecast-Modell `best_match`. Letzteres bleibt, weil nur `best_match` die Regenwahrscheinlichkeit liefert.
- Die Wetterabfrage macht damit zwei HTTP-Calls statt einem, speist aber weiterhin **ein** `WeatherDataFetched`-Ereignis und **eine** `weather_history`-Zeile. Cache- und Ereignis-Struktur (ADR 0020) bleiben unverändert.
- Der gefallene Regen trägt ein **Herkunfts-Kennzeichen** (`measured` oder `forecast`). Der Adapter ersetzt bei Archiv-Ausfall nicht still durch den Modellwert, sondern markiert die Herkunft — die Reaktion darauf ist Sache des Aufrufers.

### Aufruferspezifisches Ausfallverhalten (ADR 0024)

- Fällt die Vorhersage aus, gilt die gesamte Abfrage als gescheitert; die bestehende Cache-first-Fallback-Kette (ADR 0020) greift unverändert.
- Fällt nur die Messung aus (Vorhersage erfolgreich), wird die Herkunft als `forecast` markiert und eine Warnung protokolliert.
- Die **Überspring-Logik** ist zeitkritisch und läuft je geplantem Guss ggf. mehrfach am Tag. Sie nutzt den gefallenen Regen unabhängig von der Herkunft (degradiert) und entscheidet trotzdem.
- Der **Tagesbericht** ist nicht zeitkritisch. Ist die Herkunft nicht `measured`, zeigt er **keine** „gefallener Regen"-Zahl und **unterdrückt den Abweichungs-Vergleich**; stattdessen erscheint ein ehrlicher Hinweis, dass gemessene Regendaten zurzeit nicht verfügbar sind.

### Deterministischer Vorhersage-Tagessnapshot (ADR 0025)

- Der Abweichungsvergleich liest die gestrige Vorhersage künftig aus einem datums-gekoppelten Snapshot statt aus einer unscharfen Zeitfenster-Suche.
- Der Snapshot lebt als einzelner Eintrag in `system_metadata` (konsistent mit ADR 0012, wo der Bericht-Zustand wohnt) und enthält Datum, vorhergesagten Regen der nächsten 24h und den Fensteranfang.
- **Geschrieben** wird er ausschließlich im geplanten 08:00-Pfad (in der Tagesbericht-Versandfunktion, die nur der Scheduler aufruft): erst gestrigen Snapshot lesen, dann mit dem heutigen Wert überschreiben.
- **Gelesen** wird er im gemeinsamen Berichtspfad (geplant und manuell). Ein Datums-Guard verwendet den Snapshot nur, wenn sein Datum dem Vortag entspricht; sonst entfällt der Vergleich (deckt Offline-Tage und Erstlauf ab).
- Manuelles `/report` ist gegenüber dem Snapshot schreib-frei (konsistent mit ADR 0012). Damit hat ein zwischengeschalteter `/report` keinen Einfluss mehr auf den Vergleich.

### Gemeinsame Gieß-Entscheidung in `core/` (Notiz an ADR 0021)

- Neue pure Funktion `evaluate_rain_window(rain_last_mm, rain_next_mm, threshold_mm)` in `core/watering_advice.py`. Sie gibt die Überspring-Entscheidung und die Fenstersumme zurück — ohne I/O, ohne Strings, ohne Zeitbezug; der Schwellenwert wird hereingereicht, `core/` importiert keine Konfiguration.
- Die Überspring-Logik und die Chart-Caption rufen beide diese Funktion. Die deutschen Texte (Log-/Ereignis-Begründung, Caption-Text) bleiben je Aufrufer unterschiedlich, das Ja/Nein darunter ist identisch — Widersprüche sind ausgeschlossen. Präsentation bleibt aus `core/` heraus.
- Diese Funktion ist zugleich die gemeinsame Basis für das geplante `evaluate()` aus Feature 0009 (Gießcheck): dessen Signal „Regen-Fenster trocken" entspricht dieser Entscheidung; `evaluate()` komponiert sie und legt Temperatur und Hitzestrecke darüber. So entsteht keine doppelte Schwellenwert-Logik.

### Ein Abruf pro Bericht

- Im manuellen `/report`-Pfad wird zuerst der Berichtstext erzeugt (frische Abfrage schreibt die neue `weather_history`-Zeile), danach das Chart erzeugt (liest genau diese Zeile). Caption und Text basieren so auf demselben Abruf und derselben Entscheidung. Bisher las die Caption die vorige Cache-Zeile und der Text eine neue Abfrage.

### Robuste Stunden-Zuordnung (Bugfix, Konsequenz in ADR 0024)

- Die Zuordnung der aktuellen Stunde im Stunden-Array verwendet künftig „letzter Stunden-Zeitstempel ≤ jetzt" statt „exakter Treffer, sonst fester Index". Das ist robust gegen Zeitzonen-Versatz und fehlenden Exakt-Treffer; der bisherige Mitternachts-Rückfall entfällt. Da der gefallene Regen nun aus dem Archiv kommt, dient diese Zuordnung im Forecast-Pfad nur noch der Vorhersage und dem Chart-Fenster.

### Schema-Änderung

- `weather_history` erhält eine Spalte für das Herkunfts-Kennzeichen des gefallenen Regens, ergänzt per `ALTER`-in-`try/except` in der DB-Initialisierung (bestehendes Migrationsmuster, kein Framework).
- Kein neues Table — der Snapshot nutzt `system_metadata`.

### Domänensprache (CONTEXT.md)

- „Regen-Fenster" wird geschärft: der gefallene Anteil stammt aus gemessenen/Reanalyse-Daten (Archiv/ERA5) des Wetter-Dienstes, der erwartete Anteil aus dem Forecast-Modell.
- „Wetter-Dienst" wird präzisiert: liefert über zwei Produkte (Vorhersage und gemessene Vergangenheit). Das _Avoid_ „Wetterstation/Wettersensoren" meint eigene Hardware im Garten, nicht die observations-gestützte Reanalyse-API — „gemessen" bleibt zulässig.

## Test-Entscheidungen (Testing Decisions)

Getestet wird ausschließlich das **externe Verhalten** — Rückgabewerte, veröffentlichte Ereignisse, gesendete Nachrichten. Keine Assertions auf interne Zustände oder SQL-Queries. Alle Tests laufen offline. Bestehendes Muster für Wetterabfragen: `urllib.request.urlopen` wird gepatcht; für den Zwei-Call-Fall verzweigt ein `side_effect` nach Ziel-URL (Forecast- vs. Archiv-Endpunkt).

- **`tests/core/test_watering_advice.py` (neu):** pure Tests für `evaluate_rain_window` ohne Mocks — unter, genau auf und über der Schwelle. Referenzmuster: `tests/core/test_watering_controller.py`.
- **`tests/adapters/test_weather.py` (Erweiterung):** Zwei-Call-Glücksfall (gefallener Regen aus Archiv, Vorhersage aus Forecast, Ereignis trägt Herkunft `measured`); Archiv-Ausfall bei intakter Vorhersage (Herkunft `forecast`, Ereignis sonst vollständig); Vorhersage-Ausfall (gesamte Abfrage scheitert); Degradation der Überspring-Logik bei Cache-Herkunft `forecast`; robuste Stunden-Zuordnung im Offset-Fall ohne Mitternachts-Rückfall.
- **`tests/adapters/test_daily_report.py` (Erweiterung):** Bericht-Ehrlichkeit bei nicht-gemessener Herkunft (keine Regenzahl, kein Abweichungsvergleich, Hinweistext); deterministischer Vergleich gegen den Snapshot; Datums-Guard, wenn der gestrige Snapshot fehlt.
- **`tests/adapters/test_database.py` (Erweiterung):** Snapshot schreiben/lesen über `system_metadata`; manuelles `/report` überschreibt den Snapshot nicht.
- **`tests/adapters/test_chart.py` (Erweiterung):** Caption ruft dieselbe `evaluate_rain_window` und stimmt mit der Überspring-Entscheidung überein.
- **`tests/ui/test_telegram_ui.py` (Erweiterung):** Ein-Abruf-pro-Bericht — Caption und Text nutzen dieselben abgerufenen Werte.

Coverage darf nicht regredieren (`scripts/run_coverage.ps1`).

## Nicht im Leistungsumfang (Out of Scope)

- Anpassung des Schwellenwerts `RAIN_THRESHOLD_MM` — reine Konfigurationssache, kein Code; die Schwelle funktioniert mit gemessenen Daten wie in ADR 0003 ursprünglich gedacht.
- Verfeinerung des Entscheidungsmodells (Gewichtung der Zukunft per Regenwahrscheinlichkeit, Verdunstungs-/Drainage-Betrachtung) — Folgearbeit.
- Die vollständige Gieß-Empfehlung mit Temperatur und Hitzestrecke (Feature 0009) — eigenständig; dieses Feature legt nur die gemeinsame Basisfunktion an.
- Wechsel des Vorhersage-Modells (z.B. auf ICON-EU) — `best_match` bleibt, weil es die Regenwahrscheinlichkeit liefert.
- Ein Live-Indikator „gemessen/geschätzt" in der `/status`-Abfrage (im Geiste ADR 0006) — Folgearbeit.

## Weitere Anmerkungen (Further Notes)

- Empirisch verifiziert (Koordinate 52.50/13.51, 14.06.): gefallener Regen letzte 24h — Forecast `best_match` 1.2 mm, Forecast `icon_eu` 5.2 mm, Archiv/ERA5 6.1 mm. Pinnen auf ein ICON-Modell scheidet aus, weil dann die Regenwahrscheinlichkeit zu `null` wird.
- Bekannte Einschränkung: Der Archiv-/ERA5-Wert für die jüngste Vergangenheit ist vorläufig (ERA5T) und kann später revidiert werden. Da der Bericht den Wert einmal zum Abrufzeitpunkt nutzt, ist das akzeptabel.
- Koordination mit Feature 0009: beide nutzen `core/watering_advice.py`. Dieses Feature liefert `evaluate_rain_window`; 0009 ergänzt dort später `evaluate()`, das die Basis komponiert. Ein entsprechender Hinweis wurde in Feature 0009 ergänzt.
- Dokumentations-Deliverables (in der Umsetzung zu schreiben): ADR 0024, ADR 0025, Notiz an ADR 0021, Schärfungen in `CONTEXT.md`.
