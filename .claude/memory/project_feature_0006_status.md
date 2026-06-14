---
name: project-feature-0006-status
description: "Multi-Ventil-Unterstützung (Feature 0006) — abgeschlossen 2026-06-13, alle 79 Tests grün"
metadata: 
  node_type: memory
  type: project
  originSessionId: 8f4df8a5-7c3c-4d17-8244-8c1aebc8d88c
---

Feature 0006 (Multi-Ventil-Unterstützung) ist **vollständig abgeschlossen**. 9-stufiger Plan in `docs/plans/0007-mehrfach-ventil-unterstuetzung-plan.md`.

**Why:** Mehrere Ventile sollen in einem System betrieben werden können (DB-Verknüpfung, EventBus-Filterung, dynamische MQTT-Topics).

**Status:** 79/79 Tests grün, 3 skipped (kein Regressionsfall).

## Alle Schritte abgeschlossen (1–9)

| Schritt | Datei | Status |
|---------|-------|--------|
| 1 | `database.py` | ✅ Schema `valves` + `schedule_valves`, Migrationen, CRUD |
| 2 | `valve_events.py` | ✅ `ValveStatusReported.mqtt_name` |
| 3 | `mqtt_client.py` | ✅ `mqtt_name` in MQTT-Nachrichten übergeben |
| 4 | `pairing.py` | ✅ `start_pairing(chat_id, notify_fn, wish_name)` + DB |
| 5 | `database_adapter.py` | ✅ `update_valve_status()` in `_on_valve_status_reported` |
| 6 | `watering_controller.py` | ✅ `_active_cycles`, `start_watering(…, mqtt_name, valve_topic)` |
| 7 | `scheduler.py` | ✅ `_trigger_scheduled_watering` liest `get_schedule_valves()`, `_start_sequential` via EventBus-Queue |
| 8 | `daily_report.py` | ✅ `get_all_valves()` iteriert, `_valve_warnings` pro Ventil |
| 9 | `telegram_ui.py` | ✅ "Ventil koppeln" immer sichtbar, wish_name-Wizard, Status pro Ventil |

## Technische Entscheidungen (relevant für zukünftige Sessions)

- **mqtt_name** = technischer Bezeichner (`"garden_valve"`, `"valve_1122"`); `wish_name` = Anzeigename
- **Sequentieller Modus:** Scheduler abonniert `WateringCycleCompleted`/`WateringCycleFailed` one-shot in `_start_sequential`; WateringController bleibt sequenzunbewusst
- **`last_update=NULL`** bedeutet "nie verbunden" — kein "Verbindung verloren"-Warning; nur stale (> 24h) wird gewarnt
- **`add_valve` returns -1** bei IntegrityError (bereits vorhanden); Tests müssen auf `<= 0` prüfen (nicht `== 0`)
- **Valve state (ON/OFF)** ist pro Ventil ephemer (MQTT); Status-Anzeige nutzt `last_update` aus DB statt mqtt_client.get_valve_status()
