# 20. Cache-first-Strategie für Wetterdaten-Abfragen

Wir lesen beim Wetter-Skip-Check primär aus dem DB-Cache und rufen die Live-API nur bei veralteten oder fehlenden Daten ab.

## Kontext

`should_skip_watering()` rief bisher bei jedem Zeitplan-Auslöser direkt die Open-Meteo API ab. Der stündliche Hintergrund-Poll schrieb Wetterdaten in die `weather_history`-Tabelle, diese wurden aber bei der Skip-Entscheidung nie gelesen. Auf dem Pi Zero W mit instabilem WLAN ist ein Live-Call im kritischen Pfad des Schedulers fehleranfällig — scheitert er, wurde bisher immer `skip=False` zurückgegeben (Guss läuft durch), auch wenn brauchbare Daten im Cache vorhanden wären.

## Entscheidung

Wir führen eine **Cache-first-Fallback-Kette** in `should_skip_watering()` ein:

1. **Frischer Cache** (`cache_alter < 4 × WEATHER_REFRESH_INTERVAL_SECONDS`): DB-Eintrag direkt nutzen, kein API-Call.
2. **Veralteter Cache, Live verfügbar**: Live-API abrufen, Ergebnis nutzen.
3. **Veralteter Cache, Live nicht erreichbar**: Stale Cache nutzen, sofern `cache_alter < 24h` (Vorhersagefenster deckt den aktuellen Zeitpunkt noch ab). Warnung ins Log.
4. **Cache älter als 24h oder kein Eintrag, Live nicht erreichbar**: `skip=False` — Guss wird durchgeführt.

Das maximale Cache-Alter (`max_age`) wird als Formel `4 × WEATHER_REFRESH_INTERVAL_SECONDS` berechnet, kein eigener Konfigwert. Die 24h-Grenze ist eine Domänen-Konstante (`WEATHER_FORECAST_WINDOW_SECONDS = 86400`) in `weather.py`, da Open-Meteo genau 24h vorausschaut.

Der Hintergrund-Poll-Takt wird von 3600s auf **1800s (30 min)** reduziert (neuer Default für `WEATHER_REFRESH_INTERVAL_SECONDS`), sodass `max_age` = 7200s (2h) einem Puffer von 4 verpassten Polls entspricht.

Die gesamte Cache-Logik sitzt in `should_skip_watering()` (`weather.py`). Der Scheduler kennt keine Caching-Details.

Bei Nutzung des stale Cache wird nur ein Log-Eintrag geschrieben — keine aktive Benutzerbenachrichtigung.

## Konsequenzen

- **Vorteile**: Skip-Entscheidung ist robust gegen Netzwerkausfälle; Live-API wird weniger häufig im kritischen Pfad belastet; bestehende Cache-Infrastruktur (DB + Hintergrund-Poll) wird sinnvoll genutzt.
- **Nachteile**: Leicht erhöhte Komplexität in `should_skip_watering()`; bei instabilem WLAN kann eine bis zu 2h alte Vorhersage genutzt werden (inhaltlich für ein 24h-Niederschlagsfenster jedoch vertretbar).
