# 45. Modulort folgt der Kohäsion, nicht der Reinheit

Wo Code physisch liegt, richtet sich nach seiner **Kopplung** und den Import-Regeln —
nicht danach, ob er zufällig rein ist. Zwei wiederkehrende Architektur-Vorschläge
(„zieh die reine Logik nach `core`", „kapsle den Key-Value-Store in ein eigenes Modul")
klingen richtig, kollidieren aber mit den Regeln bzw. der Kohäsion. Diese ADR hält die
Grenze fest, damit künftige Architektur-Reviews sie nicht erneut aufwerfen.

## Kontext

Im Architektur-Review vom 24.07. tauchten zwei Platzierungs-Entscheidungen auf, die auf den
ersten Blick gegen die Hexagonal-Regeln zu verstoßen scheinen, es aber nicht tun:

1. **Format-gekoppelte reine Funktionen.** Beim Zerlegen von `get_weather_data` (Ticket
   `6xy`) entstehen reine Helfer (`select_rain_last`, `aggregate_rain_window`,
   `max_rain_prob`, `build_hourly_forecast`). Sie sind rein und ohne Netz unit-testbar — aber
   an das **Open-Meteo-Array-Layout** gekoppelt. Der Reflex „reine Funktion → nach `core`"
   würde das externe API-Format in den Kern leaken.

2. **Typisierte Zustands-Zugriffe.** Der Vorschlag, `system_metadata` in ein eigenes
   Zustands-Modul zu kapseln (Ticket `l97`), scheitert an Regel 1: ein Adapter, der
   `database` ruft, importiert einen anderen Adapter. Ein separates `state`-Modul wäre genau
   das.

Beide Fälle drehen sich um dieselbe Verwechslung: die Regeln 1 und 3 beschränken die
**Abhängigkeitsrichtung** (wer wen importiert), nicht den physischen Ort reinen Codes.

## Entscheidung

- **Reiner Code, der an ein externes Datenformat oder einen konkreten Adapter gekoppelt ist,
  bleibt beim Adapter.** Regel 3 verbietet `core → adapters`-**Importe**, nicht reinen Code
  außerhalb von `core`. Format-gekoppelte reine Funktionen (z. B. die Open-Meteo-Aggregationen)
  leben als modulweite reine Funktionen **neben ihrem Parser** in `adapters/weather.py`; sie
  sind dort genauso rein unit-testbar. Der Test für den Ort ist die **Kopplung**, nicht die
  Reinheit.

- **Reiner Code ohne Format-/Adapter-Kopplung, der Domänenlogik ist, gehört weiterhin nach
  `core`.** `core/weather_report.py::resolve_heute_weather`, `core/watering_advice.py`,
  `core/version_announce.py` sind die Referenz: sie entscheiden über *Werte*, nicht über
  API-Layouts, und der Adapter reicht ihre Eingaben herein (ADR 0017/0021/0042).

- **Typisierte Persistenz-Zugriffe leben im Persistenz-Adapter (`adapters/database.py`), nicht
  in einem separaten Zustands-Modul.** `database.py` ist ohnehin der **Domänen**-Persistenz-
  Adapter (`get_schedules`, `log_watering`, `get_valve_by_id`), kein generischer KV-Store;
  benannte, typisierte Metadaten-Accessoren (`gemeldete_version()`,
  `regen_uebersteuerung(schedule_id)`, `tagesbericht_gesendet(datum)`) gehören zu seinem
  Charakter und halten die Key-Namen + das Encoding an einem Ort. Ein **reines** Key-Registry
  in `core` (nur Key-Konstanten + Codecs, kein I/O) bliebe zulässig — aber die Accessoren, die
  tatsächlich lesen/schreiben, bleiben in `database.py`.

## Konsequenzen

- Architektur-Reviews schlagen „reine Funktion → nach `core`" und „Key-Value-Store → eigenes
  Modul" **nicht mehr pauschal** vor. Der Ort folgt Kopplung/Kohäsion **plus** den
  Import-Regeln 1/3.
- Betrifft konkret die Tickets `6xy` (reine Wetter-Helfer bleiben in `weather.py`) und `l97`
  (Metadaten-Accessoren in `database.py`).
- `database.py` wächst durch die typisierten Accessoren — bewusst akzeptiert; es sind
  Persistenz-Funktionen mit Domänennamen, kein Fremdkörper.
- Die Enforcement-Greps der Regeln 1 und 3 bleiben unverändert gültig (sie prüfen Importe, und
  genau die verletzt keiner der beiden Fälle). ARCHITECTURE.md verweist bei den Regeln 1 und 3
  auf diese ADR.
