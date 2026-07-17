# 25. Deterministischer Vorhersage-Tagessnapshot für Abweichungsvergleiche

Datum: 2026-06-15

## Status

Akzeptiert

## Kontext

Der tägliche Bericht um 08:00 Uhr (sowie Aufrufe über `/report`) enthielt bislang einen Vergleich zwischen der gestrigen Vorhersage und dem tatsächlich gefallenen Regen ("Mehr/Weniger Regen als erwartet"). Dieser Vergleich basierte auf der Datenbankfunktion `get_weather_around_hours_ago(24)`, welche dynamisch den Datensatz suchte, dessen Zeitstempel am nächsten an "vor exakt 24 Stunden" lag (mit ±6 Stunden Toleranz).

Dies erwies sich als nicht deterministisch: Wurde `/report` mehrfach an einem Tag oder zu stark abweichenden Zeiten aufgerufen, verschob sich der 24h-Bezugspunkt. Der Abweichungsvergleich änderte sich somit für denselben Tag inhaltlich, was Benutzer verwirrte.

## Entscheidung

Wir frieren die Vorhersage, die für den morgigen Tag gilt, in einem deterministischen Snapshot ein.
Der Snapshot (`daily_forecast_snapshot`) wird als Schlüssel-Wert-Paar in der Tabelle `system_metadata` (gemäß ADR 0012) gespeichert.

Der Schreibvorgang erfolgt ausschließlich und genau einmal im regulären, vom Scheduler gesteuerten `send_daily_report()`-Pfad (nachdem der frische Wetterbericht geladen und gesichert wurde).
Jeder spätere Aufruf am selben Tag (z.B. manuelles `/report` oder Neustarts) ist bezüglich des Snapshots streng lesend (Read-only).
Beim Lesen wird zusätzlich durch einen Datums-Guard sichergestellt, dass der Snapshot auch wirklich zum gestrigen Tag gehört, um alte Snapshots nach Ausfallzeiten zu ignorieren.

## Konsequenzen

- Der Abweichungsvergleich im Bericht ist für den gesamten Kalendertag stabil und reproduzierbar.
- Klarere Trennung von planmäßigen Mutationen (`send_daily_report`) und manuellen Ad-Hoc-Abfragen (`generate_daily_report`).
- Referenziert: ADR 0012 (Metadata-Tabelle).

## Ergänzung: Warum der Bericht live abruft statt aus dem Cache zu lesen

`generate_daily_report()` ruft bewusst `weather.get_weather_data()` **live** ab und liest die Wetterwerte **nicht** aus dem DB-Cache (`get_last_weather()`). Das ist eine load-bearing Entscheidung, die im Widerspruch zur Cache-first-Strategie (ADR 0020) zu stehen scheint, aber durch das Zeitfenster begründet ist:

- Der gecachte Skalar `rain_next_24h_mm` wird **zum Poll-Zeitpunkt** des stündlichen Hintergrund-Polls über `precip[current_idx:current_idx+24]` summiert. Sein 24h-Fenster hängt damit an der letzten Hintergrund-Abfrage (z. B. 07:30), nicht am Berichtszeitpunkt.
- Der Morgen-Bericht zeigt „Heute X mm erwartet" und benötigt das auf den **Berichtszeitpunkt** (≈ 08:00) zentrierte Fenster. Genau dieses liefert der frische Live-Call, der `current_idx` für „jetzt" bestimmt.
- Zusätzlich frischt der Live-Call den Cache, den `send_daily_report()` unmittelbar danach für den oben beschriebenen deterministischen Snapshot liest. Ein Cache-Read würde beide Mechanismen brechen.

**Konsequenz für künftige Architektur-Reviews:** „Lies die Wetterwerte aus dem Cache statt live" ist hier **kein** gültiger Vereinfachungsvorschlag, solange die Berichts-Anzeigewerte fenster-abhängige Skalare sind.

**Auflösungspfad:** Sobald die Berichts-Anzeigewerte — analog zur graduierten Gieß-Entscheidung — **zur Aufrufzeit** aus den gecachten Rohdaten (`hourly_forecast_json`) gegen `_find_current_index(now)` re-zentriert werden, ist das Fenster stets auf „jetzt" zentriert und der Live-Call kann entfallen. Bis dahin bleibt er erforderlich.

_(Hinweis: Die frühere Fassung verwies hier auf „ADR 0031" — ein Vorwärtsverweis auf eine nie unter dieser Nummer geschriebene ADR; `docs/adr/0031` ist tatsächlich „Graduierte Gieß-Steuerung". ADR 0042 greift das Ausfall-Problem auf, wählt aber bewusst den **Cache-Rückfall** statt der vollständigen Re-Zentrierung — der Live-Call bleibt Primärquelle, die Ablösung oben bleibt offen.)_
