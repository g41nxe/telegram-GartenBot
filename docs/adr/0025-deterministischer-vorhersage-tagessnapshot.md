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
