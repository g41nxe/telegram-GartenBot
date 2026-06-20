# Plan: Regensensor-Integration (telegram-GartenBot-uwz)

Referenz: docs/features/0016-regensensor-integration.md

## Dateien die neu angelegt werden

- `src/daemon/core/sensor_events.py` — `RainSensorMeasured`-Ereignis
- `src/daemon/core/watering_events.py` — `WateringCycleTerminated`, `WateringCycleStopped`, `WateringCycleInterrupted`
- `tests/adapters/test_rain_sensor.py` — Tests für alle neuen Komponenten

## Dateien die geändert werden

- `config/garden.conf` — `RAIN_SENSOR_TOPIC`, `RAIN_SENSOR_THRESHOLD_MM`, `RAIN_SENSOR_OFFLINE_HOURS`
- `src/daemon/config.py` — Konstanten für die 3 neuen Keys
- `src/daemon/core/watering_controller.py` — Events aus `watering_events.py` importieren (re-export für Abwärtskompatibilität), `RainSensorMeasured`-Subscriber, neue Methode `interrupt_watering()` die `WateringCycleInterrupted` publiziert
- `src/daemon/adapters/database.py` — `rain_measurements`-Tabelle, `log_rain_measurement()`, `get_rain_sum_last_24h()`, `get_last_rain_measurement()`
- `src/daemon/adapters/database_adapter.py` — Subscribe auf `RainSensorMeasured` und `WateringCycleInterrupted`
- `src/daemon/adapters/mqtt_client.py` — Topic-Subscription und Payload-Parsing für Regensensor; `RainSensorMeasured` publizieren
- `src/daemon/adapters/weather.py` — Sensorwert als primäre Quelle; ERA5 als Fallback wenn Sensor älter als `RAIN_SENSOR_OFFLINE_HOURS`; `rain_last_source="sensor"` möglich
- `src/daemon/adapters/watchdog.py` — Inaktivitäts-Check für Regensensor; `_on_rain_measurement()` Handler für Sofort-Entwarnung
- `src/daemon/ui/telegram_ui.py` — `_on_watering_interrupted()`, `_on_rain_started()`, `_on_rain_stopped()` Handler; `/status` Zeile; `subscribe_event_handlers()` erweitern
- `src/daemon/adapters/daily_report.py` — Regensensor-Sektion und Quellen-Marker

## Architektur-Entscheidungen

1. **Neue Ereignis-Datei `watering_events.py`:** `WateringCycleTerminated` (gemeinsame Felder), `WateringCycleStopped` (manuell), `WateringCycleInterrupted` (System/Regen). Die bestehenden Klassen in `watering_controller.py` werden durch Imports aus `watering_events.py` ersetzt und per `__all__` re-exportiert — keine Breaking Changes für Tests.

2. **`interrupt_watering()` in WateringController:** Analog zu `stop_watering()`, aber publiziert `WateringCycleInterrupted` statt `WateringCycleStopped`. Wird durch `RainSensorMeasured`-Subscriber aufgerufen wenn `is_raining=True`.

3. **Sensor-Quelle in weather.py:** `get_rain_sum_last_24h()` prüft ob jüngster Eintrag jünger als `RAIN_SENSOR_OFFLINE_HOURS` ist. Wenn ja: `rain_last_source="sensor"`; sonst ERA5-Fallback.

4. **Flankensteuerung:** Zustand in `system_metadata` als `rain_sensor_raining_flag` ("1" = Regen aktiv). Nur beim Übergang 0→1 `_on_rain_started`, nur bei 1→0 `_on_rain_stopped`.

5. **Watchdog:** Prüft ob `rain_measurements` jünger als `RAIN_SENSOR_OFFLINE_HOURS` + Puffer. Metadaten-Key: `watchdog_alert_active_rain_sensor`. Sofort-Entwarnung via `_on_rain_measurement()` Handler.

## Test-Nahtstellen (Seams)

- Alle Tests konstruieren die jeweilige Komponente mit einem frischen `EventBus()` und publizieren Ereignisse direkt — kein MQTT-Roundtrip.
- DB-Tests nutzen `_make_temp_db()` Pattern aus `test_watchdog.py`.

## Implementierungs-Reihenfolge

1. `core/sensor_events.py` + `core/watering_events.py` — Ereignis-Signaturen
2. `watering_controller.py` — Events importieren, `interrupt_watering()` + Subscriber
3. `config.py` + `garden.conf` — 3 neue Keys
4. `database.py` — `rain_measurements` Tabelle + Queries
5. `mqtt_client.py` — Topic-Subscription + Payload-Parsing
6. `database_adapter.py` — neue Subscriptions
7. `weather.py` — Sensor als primäre Quelle
8. `watchdog.py` — Regensensor-Watchdog
9. `telegram_ui.py` — Benachrichtigungen + Status
10. `daily_report.py` — Regensensor-Sektion
11. Tests schreiben und grün machen
