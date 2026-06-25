# Geräte-Fixtures: Sonoff SWV-ZFE (Ventil)

Echte, aus MQTT-Mitschnitten extrahierte Payloads des Ventils (Topic
`zigbee2mqtt/garden_valve`), aufgenommen am 2026-06-25. Sie dienen als realitätstreue
Testdaten für die Volumen-Logik der Guss-Steuerung und belegen das Verhalten, das zu
ADR 0007 (Volumen-Quelle) geführt hat.

Format: JSON Lines — eine Geräte-Nachricht pro Zeile, auf relevante Zustandsänderungen
dedupliziert (Reihenfolge erhalten, volle Original-Payloads).

## Dateien

- **`swv_zfe_single_guss.jsonl`** — ein einzelner Guss (2 min). Zeigt den Kernbefund:
  `irrigation_schedule_status.actual_irrigation_amount` läuft live `0 → 40` mit
  (`schedule_status == "running"`), während der kumulative `real_time_irrigation_volume`
  **eingefroren** bleibt und erst nach dem Schließen springt.
- **`swv_zfe_back_to_back.jsonl`** — zwei Güsse hintereinander. Zeigt die Session-Grenze:
  der verspätete `end`-Report der Vorsession (`actual = 40`) trifft ein, **bevor** die neue
  Session `actual` auf 0 zurücksetzt. Genau dieser lagged Wert vergiftete früher den
  Folge-Guss.

## Schlüsselfelder

- `state`: `ON`/`OFF` (vom Daemon via `state:ON/OFF` gesteuert).
- `irrigation_schedule_status.schedule_status`: `start` → `running` → `end`.
- `irrigation_schedule_status.actual_irrigation_amount`: **Guss-Volumen** der laufenden
  Session (Liter, 0-basiert). Nur bei `running` gültig.
- `real_time_irrigation_volume`: kumulativer geräteweiter Zähler — **nicht** als
  Guss-Volumen verwenden.

Verwendet von `tests/core/test_real_device_fixtures.py`. Siehe auch Feature 0028
(originalgetreue Simulator-Nachbildung).
