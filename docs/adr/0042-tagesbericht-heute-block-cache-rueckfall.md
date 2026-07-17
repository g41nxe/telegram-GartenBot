# 42. Heute-Block fällt bei Live-Ausfall auf den Wetter-Cache zurück

Scheitert der Live-Abruf des Wetter-Diensts, zeigt der **Heute-Block** des **Tagesberichts**
nicht länger erfundene Nullwerte, sondern die zuletzt erfolgreich gepollten Cache-Werte —
mit ehrlichem **Wetterdaten-Stand**. Ist auch der Cache zu alt oder leer, tritt eine ehrliche
„nicht verfügbar"-Zeile an die Stelle der Vorhersage.

## Kontext

`generate_daily_report()` ruft die Wettervorhersage bewusst **live** ab (ADR 0025: der
Regen-Skalar `rain_next_24h_mm` im Cache ist auf den Poll-Zeitpunkt zentriert, der Bericht
braucht ihn auf die Berichtszeit zentriert). Bei einem einzelnen Fehlversuch liefert
`get_weather_data()` jedoch `None`, und der Bericht fiel bislang auf einen Default-Tupel
`(…, weather_code=0, temp_min=0.0, temp_max=0.0, rain_prob=0, …)` zurück.

Das ist doppelt irreführend: WMO-Code `0` ist kein neutraler Sentinel, sondern „klarer Himmel"
→ der Bericht behauptete **„☀️ Sonnig / Klar · 0–0 °C · 0 % ☂"** und verschickte das als echte
Prognose.

Die Diagnosedaten (Log 12.–17. Juli) belegen die Ursache eindeutig: der Wetter-Dienst
(Open-Meteo, kostenlos) antwortet um **06:00 UTC = 08:00 Lokal** an **jedem** der sechs Tage mit
`HTTP 503 Service Unavailable` — offenbar ein tägliches Last-/Update-Fenster auf Anbieterseite.
Der geplante 08:00-Bericht trifft dieses Fenster deterministisch; ein manuell später ausgelöster
`/tagesbericht` trifft den wieder gesunden Dienst und funktioniert. Der Ausfall dauert länger als
der Burst (zwei Versuche 08:00:01 und 08:00:06 beide 503), ein kurzer Retry rettet den Fall daher
nicht.

Der Cache trägt zur Berichtszeit fast immer frische Daten: der 30-Minuten-Hintergrund-Poll war
kurz zuvor erfolgreich (z. B. 07:05, 07:30). `get_last_weather()` liefert die vollständige Zeile
inkl. `hourly_forecast_json`, `temp_min`/`temp_max`, `weather_code` und `rain_probability`.

## Entscheidung

- **Live bleibt Primärquelle, Cache wird Rückfall (nicht Ersatz).** Der Bericht ruft weiter live
  ab (ADR 0025 unberührt); nur wenn `get_weather_data()` `None` liefert, greift der Rückfall.
  Der Live-Call durch reine Cache-Re-Zentrierung zu **ersetzen** (der von ADR 0025 skizzierte
  Auflösungspfad) bleibt bewusst **außerhalb des Scopes** — er wäre der größere Umbau; hier zählt
  die Ehrlichkeit bei Ausfall, nicht die Ablösung des Live-Calls.

- **Cache-Werte unverändert übernehmen.** Im Rückfall werden die Cache-Skalare `weather_code`,
  `temp_min`, `temp_max`, `rain_next`, `rain_prob` **so wie gepollt** angezeigt — keine
  Re-Zentrierung der Regen-Skalare. `temp_min`/`temp_max` sind Tageswerte (stabil), der Code ist
  max. ~30–60 Min alt. Die leichte Fenster-Verschiebung des Regen-Skalars ist im seltenen
  Ausnahmepfad vertretbar und wird durch den Stand ehrlich ausgewiesen.

- **Wetterdaten-Stand nur im Rückfall.** Ist die Vorhersage live-frisch, trägt der Heute-Block
  **keinen** Stand (implizit „jetzt"). Nur im Cache-Rückfall erscheint `*(Stand: HH:MM Uhr)*` —
  analog zur Messquelle-Kennzeichnung des Gestern-Blocks: die Marke benennt **nur die Ausnahme**
  und wird so zum Signal „nicht live", statt im Normalfall Rauschen zu sein.

- **Altersgrenze 3 Stunden.** Ist der jüngste Cache-Eintrag älter als
  `REPORT_WEATHER_MAX_AGE_HOURS` (Default 3 h) oder fehlt er ganz (Kaltstart), wird der Heute-Block
  durch die bereits katalogisierte Zeile `❌ Keine Wetterdaten verfügbar. Bitte später erneut
  versuchen.` ersetzt. Ein Morgen-Digest mit über drei Stunden alter Vorhersage wäre wertlos; die
  ehrliche Aussage ist dann die richtige.

- **Entscheidung als pure Funktion in `core/`.** Der Drei-Wege-Zweig (Live-OK → Live-Werte;
  Live-`None` + Cache frisch → Cache-Werte + Stand; sonst → nicht-verfügbar) wird als reine
  Funktion in `core/` gekapselt, die `(Live-Resultat | None, Cache-Zeile | None, now)` entgegennimmt
  und die anzuzeigenden Werte samt Modus zurückgibt. Der Adapter (`daily_report.py`) macht nur das
  I/O (`get_weather_data`, `get_last_weather`) und reicht die Daten hinein — konform zur
  Stateless-Adapter-Regel und zum Muster „Entscheidung als pure Funktion in core" (ADR 0021).

- **Kein Retry.** Der 503-Ausfall überdauert kurze Retries; die Resilienz liefert der Cache-Rückfall.
  Eine allgemeine Poll-Retry-Härtung gegen *sporadische* Einzel-5xx ist als eigenes Ticket
  ausgegliedert (`telegram_GartenBot-lca`).

## Konsequenzen

- Der 08:00-Bericht zeigt echte, wenige Minuten alte Werte mit `(Stand: HH:MM Uhr)` statt der
  0-0-Lüge; nur bei echtem Dauerausfall (>3 h) erscheint die ehrliche „nicht verfügbar"-Zeile.
- **Neuer Config-Wert** `REPORT_WEATHER_MAX_AGE_HOURS` (Default 3) in `config/garden.conf`
  (nicht-geheime Einstellung, ADR 0030).
- **Bestätigt unberührt: der deterministische Snapshot (ADR 0025).** `send_daily_report` liest den
  Snapshot weiterhin aus `get_last_weather()`. Der Rückfall **schreibt nicht** in die DB, er liest
  nur — der Snapshot verhält sich exakt wie bisher.
- **Zwei Nutzer-sichtbare Zustände am Heute-Block** kommen hinzu (Cache-Stand-Zeile,
  „nicht verfügbar"-Zeile). `telegram-nachrichten.html` (IST) wird bei der Umsetzung nachgezogen
  (Regel `telegram_messages.md`); die „nicht verfügbar"-Zeile ist der bereits bestehende String aus
  dem Gießcheck, kein neuer Wortlaut.
- **Löst die schwebende Referenz in ADR 0025 auf.** Deren „Auflösungspfad (ADR 0031)" zeigte auf
  eine nie unter dieser Nummer geschriebene ADR. Der Verweis wird auf diese ADR (0042) korrigiert,
  mit dem Hinweis, dass hier der Rückfall gewählt wurde — die vollständige Ablösung des Live-Calls
  bleibt offen.
- Der latente Fehler `max()` über eine `precipitation_probability` mit `null`-Werten
  ([weather.py:160](../../src/daemon/adapters/weather.py)) ist **nicht** die Ursache dieses Falls,
  bleibt aber ein eigenständiger Bug (eigenes Ticket).
