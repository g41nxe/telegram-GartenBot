"""
Smoke driver for telegram-GartenBot.
Runs the daemon's core in simulation mode (no MQTT broker, no Telegram, no hardware).
All assertions raise SystemExit(1) on failure.

Usage:
    python .claude/skills/run-telegram-gartenbot/smoke.py [--tests]

Options:
    --tests   Also run the full unittest suite after the smoke checks.
"""

import sys, os, time

# UTF-8 output — daily report contains emojis, Windows cp1252 can't encode them.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

def check(label, condition, detail=""):
    if condition:
        print(f"  OK  {label}")
    else:
        print(f"FAIL  {label}" + (f": {detail}" if detail else ""))
        sys.exit(1)


def run_smoke():
    print("=== GartenBot smoke (simulation mode) ===\n")

    # --- 1. Database ---
    from daemon.adapters import database
    database.init_db()
    sid = database.add_schedule("smoke", "06:00", "everyday", 5, 2, 1)
    check("add_schedule", sid > 0)
    rows = database.get_schedules()
    check("get_schedules", any(r["id"] == sid for r in rows))
    database.delete_schedule(sid)
    check("delete_schedule", not any(r["id"] == sid for r in database.get_schedules()))

    database.log_watering(3, "smoke", "completed", "smoke run", watered_volume=1.5)
    hist = database.get_recent_history(1)
    check("log_watering", hist and hist[0]["status"] == "completed")
    succ, fail, vol = database.get_watering_stats_last_24h()
    check("watering_stats", succ >= 1, f"succ={succ}")

    # --- 2. MQTT simulation ---
    from daemon.adapters import mqtt_client
    mqtt_client.HAS_PAHO = False
    mqtt_client.start_client()
    check("sim client type", mqtt_client.client_instance.__class__.__name__ == "SimulatedMqttAdapter")
    check("open_valve", mqtt_client.open_valve())
    check("valve ON", mqtt_client.get_valve_status()["state"] == "ON")
    check("close_valve", mqtt_client.close_valve())
    check("valve OFF", mqtt_client.get_valve_status()["state"] == "OFF")

    # --- 3. Scheduler + WateringController ---
    from daemon import scheduler
    from daemon.core.watering_controller import WateringController
    from daemon.adapters.database_adapter import DatabaseLoggerAdapter

    bus = mqtt_client._global_bus
    ctrl = WateringController(bus, mqtt_client.client_instance)
    scheduler.controller = ctrl
    DatabaseLoggerAdapter(bus)
    scheduler.start_scheduler()
    check("scheduler started", scheduler.scheduler_running)

    ok, msg = scheduler.start_watering(duration_minutes=1, target_volume_liters=10, source="smoke")
    check("start_watering", ok, msg)
    check("active cycle", scheduler.get_active_cycle() is not None)

    ok2, _ = scheduler.stop_watering()
    check("stop_watering", ok2)
    check("cycle cleared", scheduler.get_active_cycle() is None)

    # --- 4. Weather (offline-first fallback) ---
    from daemon.adapters import weather
    rain_l, rain_n, temp, code, tmin, tmax, prob = weather.get_weather_data(52.5, 13.5)
    check("weather offline returns floats", isinstance(rain_l, float))
    skip, reason = weather.should_skip_watering()
    check("skip logic returns bool", isinstance(skip, bool))

    # --- 5. Daily report ---
    report = scheduler.generate_daily_report("2026-06-20")
    check("daily report not empty", len(report) > 50)
    check("report contains date", "20.06.2026" in report)

    scheduler.stop_scheduler()
    check("scheduler stopped", not scheduler.scheduler_running)

    print("\n=== All smoke checks passed ===")


def run_tests():
    import subprocess
    print("\n=== Running unittest suite ===\n")
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode != 0:
        print("FAIL  unittest suite")
        sys.exit(1)
    print("\n=== All tests passed ===")


if __name__ == "__main__":
    run_smoke()
    if "--tests" in sys.argv:
        run_tests()
