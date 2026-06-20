"""
Smoke driver for telegram-GartenBot.
Runs the daemon's core in simulation mode (no MQTT broker, no Telegram, no hardware).

Usage:
    python .claude/skills/run-telegram-gartenbot/smoke.py [--tests]

Options:
    --tests   Also run the full pytest suite after the smoke checks.
"""

import sys, os
from datetime import datetime

# UTF-8 output — daily report contains emojis, Windows cp1252 can't encode them.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(_repo_root, "src"))  # enables: from daemon import ...
sys.path.insert(0, _repo_root)                        # enables: from src.daemon import ... (camera_events workaround)


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

    # --- 3. WateringController ---
    from daemon.core.watering_controller import WateringController
    from daemon.adapters.database_adapter import DatabaseLoggerAdapter

    bus = mqtt_client._global_bus
    ctrl = WateringController(bus, mqtt_client.client_instance.publish)
    DatabaseLoggerAdapter(bus)

    ok, msg = ctrl.start_watering(duration_minutes=1, target_volume_liters=10, source="smoke")
    check("start_watering", ok, msg)
    check("active cycle", ctrl.get_active_cycle() is not None)

    ok2, _ = ctrl.stop_watering()
    check("stop_watering", ok2)
    check("cycle cleared", ctrl.get_active_cycle() is None)

    # --- 4. Scheduler (lifecycle only) ---
    from daemon import scheduler
    scheduler.set_controller(ctrl)
    scheduler.start_scheduler()
    check("scheduler started", scheduler.scheduler_running)
    scheduler.stop_scheduler()
    check("scheduler stopped", not scheduler.scheduler_running)

    # --- 5. Weather (offline-first fallback) ---
    from daemon.adapters import weather
    result = weather.get_weather_data(52.5, 13.5)
    if result is not None:
        rain_l, rain_n, temp, code, tmin, tmax, prob, source = result
        check("weather returns 8-tuple", isinstance(rain_l, float))
    else:
        check("weather offline fallback (None)", True)

    skip, reason = weather.should_skip_watering()
    check("skip logic returns bool", isinstance(skip, bool))

    # --- 6. Daily report ---
    from daemon.adapters.daily_report import generate_daily_report
    today_str = datetime.today().strftime("%Y-%m-%d")
    report = generate_daily_report(today_str)
    check("daily report not empty", len(report) > 50)
    today_display = datetime.today().strftime("%d.%m.")
    check("report contains date", today_display in report, f"looking for {today_display!r}")

    print("\n=== All smoke checks passed ===")


def run_tests():
    import subprocess
    print("\n=== Running pytest suite ===\n")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests"],
        cwd=_repo_root,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode != 0:
        print("FAIL  pytest suite")
        sys.exit(1)
    print("\n=== All tests passed ===")


if __name__ == "__main__":
    run_smoke()
    if "--tests" in sys.argv:
        run_tests()
