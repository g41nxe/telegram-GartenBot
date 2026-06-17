# Design: Regensensor-Integration (Aqua Scope RANWIE01)

Datum: 2026-06-17

## Ziel

Integration des Aqua Scope RANWIE01 WLAN-Regensensors in den Bewässerungs-Daemon als primäre lokale Niederschlagsquelle. Der Sensor ersetzt ERA5-Reanalyse-Daten für `rain_last_24h`, ermöglicht Echtzeit-Guss-Unterbrechung bei Regen und legt die Datenbasis für spätere Analyse-Features.

## Entscheidungen (Grill-Session)

| Thema | Entscheidung |
|---|---|
| Kommunikationsprotokoll | MQTT-nativ (Ansatz A) |
| MQTT-Topic | `sensor/rain` (konfigurierbar via `RAIN_SENSOR_TOPIC`) |
| Guss-Stop-Events | `WateringCycleStopped` (manuell) / `WateringCycleInterrupted` (System), gemeinsames Eltern-Event `WateringCycleTerminated` |
| Starkregen-Schwelle | Entfällt — Notification bei genereller Regenerkennung (`is_raining=True`) |
| Regen-Notification | Flanken-Trigger: nur wenn Regen einsetzt, nicht bei jeder Messung |
| Mehrere Ventile | Alle aktiven Ventile werden bei Regen gestoppt |
| Datenhaltung | Kein Aufräum-Job — Tabelle wächst unbegrenzt (SQLite problemlos) |
| Tests | Events direkt auf EventBus publishen, kein SimulatedMqttAdapter-Roundtrip |
| Watchdog-Timeout | 7 Stunden (`RAIN_SENSOR_OFFLINE_HOURS=7`) |
| ADR-Abweichung | ADR 0028 supersedes ADR 0003 |

## Datenfluss

```
Aqua Scope RANWIE01
  → MQTT Topic: sensor/rain
  → Mosquitto Broker (bereits auf Pi)
  → PahoMqttAdapter (subscribe + JSON parse)
  → EventBus: RainSensorMeasured
       ├── DatabaseLoggerAdapter  → rain_measurements (Zeitreihe)
       ├── WateringController     → _interrupt_watering() bei is_raining=True
       └── TelegramUI             → Flanken-Trigger Notification, /status
```

`weather.py` liest `rain_last_24h` aus `database.sum_rain_last_24h()`. Fallback auf ERA5 wenn letzter Eintrag älter als `RAIN_SENSOR_OFFLINE_HOURS`.

## Neue Konfigurationswerte (.env)

| Variable | Default | Bedeutung |
|---|---|---|
| `RAIN_SENSOR_TOPIC` | `sensor/rain` | MQTT-Topic des Sensors |
| `RAIN_SENSOR_ACTIVE_THRESHOLD_MM` | `0.2` | Ab wann `is_raining=True` gilt (mm/Intervall) |
| `RAIN_SENSOR_OFFLINE_HOURS` | `7` | Fallback auf ERA5 nach X Stunden ohne Messung |

## Neue Datei: `core/sensor_events.py`

```python
class RainSensorMeasured(Event):
    def __init__(self,
        rainlevel_mm: float,   # mm dieses Intervalls
        raintotal_mm: float,   # kumuliert seit Reset
        temperature_c: float,  # °C (Sensor liefert 1/10°C → Adapter dividiert durch 10)
        battery_pct: int,      # %
        is_raining: bool       # rainlevel_mm > RAIN_SENSOR_ACTIVE_THRESHOLD_MM
    ): ...
```

## Neue Datei: `core/watering_events.py`

Die bestehenden Watering-Events (`WateringCycleStarted`, `WateringCycleCompleted`, `WateringCycleFailed`, `WateringCycleStopped`) werden aus `watering_controller.py` hierher ausgelagert. Zusätzlich kommen hinzu:

```python
class WateringCycleTerminated(Event):
    """Gemeinsames Eltern-Event für alle vorzeitigen Guss-Abbrüche."""
    def __init__(self, duration_run: int, volume_run: float, source: str, details: str): ...

class WateringCycleStopped(WateringCycleTerminated):
    """Manueller Stop durch den Benutzer."""

class WateringCycleInterrupted(WateringCycleTerminated):
    """Systemseitiger Abbruch (Guss-Unterbrechung), z.B. durch Regen."""
```

**Hinweis:** Der Ereignis-Kanal matcht auf `type(event)` — Abonnenten des Eltern-Events `WateringCycleTerminated` empfangen keine Kind-Events. Komponenten, die beide Typen verarbeiten (z.B. `DatabaseLoggerAdapter`), subscriben zweimal.

## Neue DB-Tabelle: `rain_measurements`

```sql
CREATE TABLE IF NOT EXISTS rain_measurements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,      -- ISO-8601, lokale Zeit
    rainlevel_mm  REAL NOT NULL,      -- mm im letzten Intervall
    raintotal_mm  REAL NOT NULL,      -- kumulierter Gesamtwert
    temperature_c REAL,               -- °C
    battery_pct   INTEGER             -- %
);
CREATE INDEX IF NOT EXISTS idx_rain_ts ON rain_measurements(timestamp);
```

Migration läuft automatisch in `database.init_db()` (try/except OperationalError, bestehendes Muster).

Neues DB-Query: `sum_rain_last_24h() → float | None` — summiert `rainlevel_mm` der letzten 24 Stunden.

## Echtzeit-Guss-Unterbrechung (`WateringController`)

Der `WateringController` abonniert `RainSensorMeasured` in `__init__`. Bei `is_raining=True`:

- Alle aktiven Zyklen werden gestoppt (iteriert über `_active_cycles`)
- Publiziert `WateringCycleInterrupted` (nicht `WateringCycleStopped`)
- `details` enthält die gemessene Regenmenge: `"Regen erkannt (X.X mm). Guss nach N Min gestoppt."`

## Telegram-Notification: Regenerkennung (Flanken-Trigger)

Status in DB: `get_metadata("rain_alert_active")` → `"1"` / `"0"` (identisches Muster wie Watchdog).

- `is_raining=True` + Flag nicht gesetzt → Notification senden + Flag setzen
- `is_raining=False` + Flag gesetzt → Entwarnung senden + Flag löschen
- Notification-Text: `"🌧 Regen erkannt: X.X mm"`
- Entwarnung-Text: `"🌤 Regen aufgehört"`

## Watchdog-Erweiterung

In `watchdog.py`:

- `_on_rain_measurement(event: RainSensorMeasured)` — sofortige Entwarnung (subscribe in `initialize()`)
- `run_watchdog_check()` — prüft letzten Eintrag in `rain_measurements`; bei Stille > `RAIN_SENSOR_OFFLINE_HOURS` → Alert

Flag-Key: `watchdog_alert_active_rain` (analog zu `watchdog_alert_active_valve_<id>`).

## Telegram-UI Änderungen

### `/status`
Neue Sektion nach dem Ventil-Block:
```
🌧 Regensensor
   Intervall: X.X mm · Gesamt: XX.X mm
   Temperatur: XX.X°C
   🔋 XX% · vor N Min
```
Bei Offline: `⚠️ Regensensor offline seit N Stunden`

### Tagesbericht
Neue Sektion `🌧 REGENSENSOR`:
- Gestern gesamt (mm)
- Max. Intervall mit Uhrzeit
- Temperatur Ø / Max
- Batterie

`rain_last_24h`-Zeile zeigt Quelle: `(Sensor)` oder `(ERA5)`.

Bei Guss-Unterbrechung in der Bewässerungs-Sektion: `⚠️ Guss HH:MM unterbrochen — Regen erkannt (X.X mm) nach N Min · V.V L`

## Betroffene Dateien

| Datei | Art |
|---|---|
| `core/sensor_events.py` | NEU — `RainSensorMeasured` |
| `core/watering_events.py` | NEU — `WateringCycleTerminated`, `WateringCycleStopped`, `WateringCycleInterrupted`; bestehende Events aus `watering_controller.py` ausgelagert |
| `core/watering_controller.py` | ERWEITERT — `RainSensorMeasured` abonnieren, `_interrupt_watering()` |
| `adapters/mqtt_client.py` | ERWEITERT — `subscribe("sensor/rain")`, JSON-Parse inkl. Temperatur-Konvertierung |
| `adapters/database.py` | ERWEITERT — Tabelle `rain_measurements`, `sum_rain_last_24h()` |
| `adapters/database_adapter.py` | ERWEITERT — `RainSensorMeasured` → DB schreiben; `WateringCycleInterrupted` subscriben |
| `adapters/weather.py` | ERWEITERT — `rain_last_24h` aus Sensor-DB, ERA5 als Fallback |
| `adapters/watchdog.py` | ERWEITERT — Regensensor-Inaktivität überwachen |
| `adapters/daily_report.py` | ERWEITERT — Regensensor-Sektion im Tagesbericht |
| `ui/telegram_ui.py` | ERWEITERT — `/status`-Sektion, Flanken-Notifications, Guss-Unterbrechungs-Meldung |
| `config.py` | ERWEITERT — 3 neue Env-Vars |
| `.env.template` | ERWEITERT — neue Variablen dokumentiert |
| `docs/adr/0028-*.md` | NEU — supersedes ADR 0003 |
| `CONTEXT.md` | ERWEITERT — Regensensor, Regenmessung, Guss-Unterbrechung |

## Ausblick (außerhalb dieses Features)

- **Temperatur-basierte Gieß-Mengen**: `temperature_c` aus `rain_measurements` als Grundlage für dynamische Volumenlimits im `WateringController`
- **Täglicher Forecast-vs-gemessen-Vergleich**: `rain_measurements` + `weather_history` als Datenbasis für Genauigkeits-Analyse der Open-Meteo-Vorhersage
