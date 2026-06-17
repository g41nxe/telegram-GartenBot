# 28. Lokaler Regensensor als primäre Niederschlagsquelle

Supersedes ADR 0003.

## Kontext

ADR 0003 entschied, auf physische Regensensoren zu verzichten und stattdessen die Open-Meteo API zu nutzen. Seitdem hat sich die Situation geändert:

- Ein lokaler Regensensor (Aqua Scope RANWIE01) ist vorhanden und sendet per MQTT.
- ADR 0024 dokumentierte bereits die Schwäche des Forecast-Modells (ERA5-Reanalyse schlägt Open-Meteo-Forecast, aber bleibt hinter lokalen Messungen zurück).
- Lokale Schauer werden von regionalen Stationsdaten oft nicht erfasst — das Mikroklima des Gartens weicht ab.

## Entscheidung

Der lokale Regensensor ist die primäre Quelle für `rain_last_24h`. Die ERA5-Reanalyse bleibt als automatischer Fallback, wenn der Sensor länger als `RAIN_SENSOR_OFFLINE_HOURS` keine Messung gesendet hat.

Die Open-Meteo Forecast-API bleibt unverändert für `rain_next_24h` (Vorhersage), da der Sensor keine Zukunft kennt.

## Konsequenzen

- Genauere Skip-Entscheidungen durch lokale Messung statt regionaler Stationsinterpolation.
- Echtzeit-Reaktion möglich: Bewässerung wird gestoppt sobald der Sensor aktiven Regen meldet (`rainlevel_mm > RAIN_SENSOR_ACTIVE_THRESHOLD_MM`).
- Zusätzliche Abhängigkeit von Batterie-Hardware; bei Ausfall greift ERA5 transparent ein.
- `rain_last_source` im `WeatherDataFetched`-Event zeigt an, welche Quelle aktiv ist (`"sensor"` oder `"measured"`/`"forecast"`).
