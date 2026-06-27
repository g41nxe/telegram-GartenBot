import sys
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import daemon.adapters.database as db


def _make_temp_db() -> Path:
    """Erzeugt eine temporäre SQLite-Datei und gibt den Pfad zurück."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return Path(f.name)


class TestDatabaseMultiValveSchema(unittest.TestCase):
    """Testet Schema-Migration und CRUD-Funktionen für Multi-Ventil-Unterstützung."""

    def setUp(self):
        self.db_path = _make_temp_db()
        self._db_path_patcher = patch.object(db, "DB_PATH", self.db_path)
        self._db_path_patcher.start()
        db.init_db()

    def tearDown(self):
        self._db_path_patcher.stop()
        import gc
        gc.collect()
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass  # Windows-Dateisperren lösen sich beim nächsten GC-Lauf auf

    # --- Schema-Tests ---

    def test_valves_table_exists(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='valves'")
        self.assertIsNotNone(cursor.fetchone(), "Tabelle 'valves' wurde nicht erstellt")
        conn.close()

    def test_valves_table_columns(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(valves)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        expected = {"id", "wish_name", "mqtt_name", "is_paired", "battery", "linkquality", "last_update", "valve_abnormal_state"}
        self.assertTrue(expected.issubset(columns), f"Fehlende Spalten: {expected - columns}")

    def test_schedule_valves_table_exists(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schedule_valves'")
        self.assertIsNotNone(cursor.fetchone(), "Tabelle 'schedule_valves' wurde nicht erstellt")
        conn.close()

    def test_schedules_has_execution_mode_column(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(schedules)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        self.assertIn("execution_mode", columns)

    def test_schedules_has_nebel_columns(self):
        """Nebel-Intervall (Feature 0032): mode, end_time, on_seconds, pause_minutes."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(schedules)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        expected = {"mode", "end_time", "on_seconds", "pause_minutes"}
        self.assertTrue(expected.issubset(columns), f"Fehlende Spalten: {expected - columns}")

    def test_add_and_get_nebel_schedule(self):
        """Ein Nebel-Zeitplan persistiert mode + Fenster-/Takt-Felder korrekt."""
        sid = db.add_schedule(
            "Terrassen-Nebel", "12:00", "everyday", duration_minutes=0,
            mode="nebel", end_time="18:00", on_seconds=20, pause_minutes=5,
        )
        self.assertGreater(sid, 0)
        sched = db.get_schedule_by_id(sid)
        self.assertEqual(sched["mode"], "nebel")
        self.assertEqual(sched["end_time"], "18:00")
        self.assertEqual(sched["on_seconds"], 20)
        self.assertEqual(sched["pause_minutes"], 5)

    def test_existing_schedule_defaults_mode_watering(self):
        """Ein normaler Zeitplan ohne Nebel-Felder ist implizit mode='watering'."""
        sid = db.add_schedule("Rasen", "07:00", "Mon,Wed", duration_minutes=10)
        sched = db.get_schedule_by_id(sid)
        self.assertEqual(sched["mode"], "watering")

    def test_watering_history_has_valve_id_column(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(watering_history)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        self.assertIn("valve_id", columns)

    def test_device_status_log_has_device_name_column(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(device_status_log)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        self.assertIn("device_name", columns)

    # --- Migrations-Tests ---

    def test_default_valve_created_on_fresh_db(self):
        valves = db.get_all_valves()
        self.assertEqual(len(valves), 1)
        self.assertEqual(valves[0]["mqtt_name"], "garden_valve")
        self.assertEqual(valves[0]["is_paired"], 1)

    def test_migration_links_existing_schedules_to_default_valve(self):
        # Zeitplan anlegen, DB neu initialisieren (simuliert Migration auf bestehender DB)
        sched_id = db.add_schedule("Test", "08:00", "everyday", 10)
        db.init_db()  # zweiter Aufruf simuliert Re-Migration
        linked_valve_ids = db.get_schedule_valves(sched_id)
        self.assertIn(1, linked_valve_ids, "Bestehender Zeitplan muss mit valve_id=1 verknüpft sein")

    def test_migration_sets_device_name_on_existing_status_logs(self):
        # Log ohne device_name einfügen (simuliert Altdaten)
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO device_status_log (timestamp, battery, linkquality) VALUES (?, ?, ?)",
                     (datetime.now().isoformat(), 80, 120))
        conn.commit()
        conn.close()
        db.init_db()  # Migration auslösen
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT device_name FROM device_status_log ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        self.assertEqual(row["device_name"], "garden_valve")

    # --- CRUD-Tests: Ventile ---

    def test_add_valve_returns_id(self):
        valve_id = db.add_valve("Rasen", "valve_1122")
        self.assertGreater(valve_id, 0)

    def test_get_valve_by_id(self):
        db.add_valve("Hochbeet", "valve_aabb")
        valves = db.get_all_valves()
        target = next(v for v in valves if v["mqtt_name"] == "valve_aabb")
        result = db.get_valve_by_id(target["id"])
        self.assertIsNotNone(result)
        self.assertEqual(result["wish_name"], "Hochbeet")

    def test_get_valve_by_mqtt_name(self):
        db.add_valve("Gewächshaus", "valve_ccdd")
        result = db.get_valve_by_mqtt_name("valve_ccdd")
        self.assertIsNotNone(result)
        self.assertEqual(result["wish_name"], "Gewächshaus")

    def test_get_valve_by_mqtt_name_not_found(self):
        result = db.get_valve_by_mqtt_name("valve_nonexistent")
        self.assertIsNone(result)

    def test_update_valve_status(self):
        now = datetime.now().isoformat()
        db.update_valve_status("garden_valve", battery=42, linkquality=150,
                               last_update=now, valve_abnormal_state="leak")
        valve = db.get_valve_by_mqtt_name("garden_valve")
        self.assertEqual(valve["battery"], 42)
        self.assertEqual(valve["linkquality"], 150)
        self.assertEqual(valve["last_update"], now)
        self.assertEqual(valve["valve_abnormal_state"], "leak")

    def test_add_valve_prevents_duplicate_mqtt_name(self):
        db.add_valve("Rasen", "valve_dup")
        result = db.add_valve("Rasen 2", "valve_dup")
        self.assertEqual(result, -1, "Doppelter mqtt_name muss -1 zurückgeben")

    # --- CRUD-Tests: schedule_valves ---

    def test_set_and_get_schedule_valves(self):
        sched_id = db.add_schedule("Multi-Test", "09:00", "everyday", 15)
        v1 = db.add_valve("Rasen", "valve_r1")
        v2 = db.add_valve("Hochbeet", "valve_h1")
        db.set_schedule_valves(sched_id, [v1, v2])
        linked = db.get_schedule_valves(sched_id)
        self.assertIn(v1, linked)
        self.assertIn(v2, linked)

    def test_set_schedule_valves_replaces_existing(self):
        sched_id = db.add_schedule("Ersatz-Test", "10:00", "everyday", 10)
        v1 = db.add_valve("Ventil-A", "valve_a1")
        v2 = db.add_valve("Ventil-B", "valve_b1")
        db.set_schedule_valves(sched_id, [v1])
        db.set_schedule_valves(sched_id, [v2])
        linked = db.get_schedule_valves(sched_id)
        self.assertNotIn(v1, linked)
        self.assertIn(v2, linked)

    # --- CRUD-Tests: device_status_log mit device_name ---

    def test_log_device_status_with_device_name(self):
        db.log_device_status("garden_valve", 75, 200)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM device_status_log ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        self.assertEqual(row["device_name"], "garden_valve")
        self.assertEqual(row["battery"], 75)
        self.assertEqual(row["linkquality"], 200)

    def test_get_device_status_stats_filters_by_device_name(self):
        db.log_device_status("garden_valve", 80, 180)
        db.log_device_status("valve_1122", 90, 100)
        stats_gv = db.get_device_status_stats_last_24h("garden_valve")
        stats_v2 = db.get_device_status_stats_last_24h("valve_1122")
        self.assertEqual(stats_gv["avg_lqi"], 180.0)
        self.assertEqual(stats_v2["avg_lqi"], 100.0)

    # --- Abwärtskompatibilität: schedules mit execution_mode ---

    def test_add_schedule_default_execution_mode(self):
        sched_id = db.add_schedule("Compat-Test", "07:00", "everyday", 5)
        schedules = db.get_schedules()
        target = next(s for s in schedules if s["id"] == sched_id)
        self.assertEqual(target.get("execution_mode", "sequential"), "sequential")


class TestWeatherHistoryFeature0007(unittest.TestCase):
    """Testet die neuen Spalten und Funktionen aus Feature 0007 (verbesserte Wetterdaten)."""

    def setUp(self):
        self.db_path = _make_temp_db()
        self._db_path_patcher = patch.object(db, "DB_PATH", self.db_path)
        self._db_path_patcher.start()
        db.init_db()

    def tearDown(self):
        self._db_path_patcher.stop()
        import gc
        gc.collect()
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_weather_history_has_current_precipitation_mm_column(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(weather_history)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        self.assertIn("current_precipitation_mm", columns)

    def test_weather_history_has_hourly_forecast_json_column(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(weather_history)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        self.assertIn("hourly_forecast_json", columns)

    def test_log_weather_stores_current_precipitation(self):
        db.log_weather(0.0, 1.2, current_temp=20.0, weather_code=61,
                       current_precipitation_mm=0.5)
        row = db.get_last_weather()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["current_precipitation_mm"], 0.5)

    def test_log_weather_stores_hourly_forecast_json(self):
        import json
        fc = {"times": ["2026-06-13T14:00"], "temp": [22.0],
              "precip_mm": [0.0], "precip_prob": [5], "wmo": [0]}
        db.log_weather(0.0, 0.0, hourly_forecast_json=json.dumps(fc))
        row = db.get_last_weather()
        self.assertIsNotNone(row)
        parsed = json.loads(row["hourly_forecast_json"])
        self.assertEqual(parsed["times"], ["2026-06-13T14:00"])
        self.assertEqual(parsed["temp"], [22.0])

    def test_log_weather_empty_hourly_json_stored_as_null(self):
        db.log_weather(0.0, 0.0, hourly_forecast_json="")
        row = db.get_last_weather()
        self.assertIsNone(row["hourly_forecast_json"])

    def test_get_last_weather_returns_new_fields_as_defaults_when_null(self):
        db.log_weather(0.5, 1.0, current_temp=18.0, weather_code=3)
        row = db.get_last_weather()
        # current_precipitation_mm has DEFAULT 0.0 — must be present
        self.assertIn("current_precipitation_mm", row)
        self.assertIn("hourly_forecast_json", row)


class TestRainLastSource(unittest.TestCase):

    def setUp(self):
        self.db_path = _make_temp_db()
        self._patcher = patch.object(db, "DB_PATH", self.db_path)
        self._patcher.start()
        db.init_db()

    def tearDown(self):
        self._patcher.stop()
        import gc
        gc.collect()
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_log_weather_persists_source(self):
        db.log_weather(6.1, 0.0, rain_last_source="measured")
        row = db.get_last_weather()
        self.assertEqual(row["rain_last_source"], "measured")

    def test_log_weather_defaults_source_to_measured(self):
        db.log_weather(1.0, 0.0)
        row = db.get_last_weather()
        self.assertEqual(row["rain_last_source"], "measured")

    def test_log_weather_accepts_forecast_source(self):
        db.log_weather(1.0, 0.0, rain_last_source="forecast")
        row = db.get_last_weather()
        self.assertEqual(row["rain_last_source"], "forecast")


class TestDailyForecastSnapshot(unittest.TestCase):

    def setUp(self):
        self.db_path = _make_temp_db()
        self._patcher = patch.object(db, "DB_PATH", self.db_path)
        self._patcher.start()
        db.init_db()

    def tearDown(self):
        self._patcher.stop()
        import gc
        gc.collect()
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_set_and_get_daily_forecast_snapshot(self):
        db.set_daily_forecast_snapshot("2026-06-14", 5.5, "14:00")
        snapshot = db.get_daily_forecast_snapshot()
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["date"], "2026-06-14")
        self.assertEqual(snapshot["rain_next_mm"], 5.5)
        self.assertEqual(snapshot["window_start"], "14:00")

    def test_get_daily_forecast_snapshot_returns_none_initially(self):
        self.assertIsNone(db.get_daily_forecast_snapshot())

class TestGetWateringSkipCountLast24h(unittest.TestCase):

    def setUp(self):
        self.db_path = _make_temp_db()
        self._patcher = patch.object(db, "DB_PATH", self.db_path)
        self._patcher.start()
        db.init_db()

    def tearDown(self):
        self._patcher.stop()
        import gc
        gc.collect()
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def _insert_history(self, status: str, minutes_ago: int = 60):
        from datetime import timedelta
        ts = (datetime.now() - timedelta(minutes=minutes_ago)).isoformat()
        conn = db.get_connection()
        conn.execute(
            "INSERT INTO watering_history (timestamp, duration_minutes, source, status) VALUES (?, ?, ?, ?)",
            (ts, 0, "schedule", status)
        )
        conn.commit()
        conn.close()

    def test_no_entries_returns_zero(self):
        self.assertEqual(db.get_watering_skip_count_last_24h(), 0)

    def test_one_skip_returns_one(self):
        self._insert_history("skipped")
        self.assertEqual(db.get_watering_skip_count_last_24h(), 1)

    def test_completed_not_counted(self):
        self._insert_history("completed")
        self.assertEqual(db.get_watering_skip_count_last_24h(), 0)

    def test_old_skip_beyond_24h_not_counted(self):
        self._insert_history("skipped", minutes_ago=25 * 60)
        self.assertEqual(db.get_watering_skip_count_last_24h(), 0)


class TestGetDailyMaxTemps(unittest.TestCase):

    def setUp(self):
        self.db_path = _make_temp_db()
        self._patcher = patch.object(db, "DB_PATH", self.db_path)
        self._patcher.start()
        db.init_db()

    def tearDown(self):
        self._patcher.stop()
        import gc
        gc.collect()
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def _days_ago(self, n: int) -> str:
        return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")

    def _insert_weather(self, date_str: str, temp_max: float):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO weather_history (timestamp, rain_last_24h_mm, rain_next_24h_mm, "
            "current_temp, weather_code, temp_min, temp_max, rain_probability) "
            "VALUES (?, 0, 0, 20, 0, 15, ?, 0)",
            (f"{date_str}T12:00:00", temp_max),
        )
        conn.commit()
        conn.close()

    def test_returns_past_days_newest_first(self):
        self._insert_weather(self._days_ago(3), 28.0)
        self._insert_weather(self._days_ago(2), 30.0)
        self._insert_weather(self._days_ago(1), 26.0)
        result = db.get_daily_max_temps(5)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0][0], self._days_ago(1))
        self.assertAlmostEqual(result[0][1], 26.0)
        self.assertEqual(result[1][0], self._days_ago(2))
        self.assertAlmostEqual(result[1][1], 30.0)

    def test_excludes_today(self):
        today = datetime.now().strftime("%Y-%m-%d")
        self._insert_weather(today, 35.0)
        result = db.get_daily_max_temps(5)
        self.assertEqual(result, [])

    def test_returns_max_per_day_when_multiple_entries(self):
        self._insert_weather(self._days_ago(1), 25.0)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO weather_history (timestamp, rain_last_24h_mm, rain_next_24h_mm, "
            "current_temp, weather_code, temp_min, temp_max, rain_probability) "
            "VALUES (?, 0, 0, 20, 0, 15, ?, 0)",
            (f"{self._days_ago(1)}T18:00:00", 31.0),
        )
        conn.commit()
        conn.close()
        result = db.get_daily_max_temps(5)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0][1], 31.0)

    def test_empty_when_no_data(self):
        result = db.get_daily_max_temps(5)
        self.assertEqual(result, [])

    def test_respects_days_limit(self):
        for i in range(1, 8):
            self._insert_weather(self._days_ago(i), float(20 + i))
        result = db.get_daily_max_temps(3)
        self.assertEqual(len(result), 3)

    def test_result_is_list_of_tuples(self):
        self._insert_weather(self._days_ago(1), 22.5)
        result = db.get_daily_max_temps(5)
        self.assertEqual(len(result), 1)
        date_str, temp_max = result[0]
        self.assertIsInstance(date_str, str)
        self.assertIsInstance(temp_max, float)
        self.assertAlmostEqual(temp_max, 22.5)


    def test_excludes_today_by_local_clock_not_utc(self):
        """Tagesgrenze muss lokal berechnet werden, nicht als date('now') (UTC).

        Simulation: Eintrag für lokales Heute (2026-06-15) einfügen,
        datetime.now() auf 02:00 Uhr patchen (entspricht UTC-gestern in MESZ).
        Die Funktion muss den Eintrag trotzdem ausschließen.
        """
        fake_today = datetime(2026, 6, 15, 2, 0, 0)
        today_str = "2026-06-15"

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO weather_history (timestamp, rain_last_24h_mm, rain_next_24h_mm, "
            "current_temp, weather_code, temp_min, temp_max, rain_probability) "
            "VALUES (?, 0, 0, 20, 0, 15, ?, 0)",
            (f"{today_str}T02:00:00", 35.0),
        )
        conn.commit()
        conn.close()

        with patch("daemon.adapters.database.datetime") as mock_dt:
            mock_dt.now.return_value = fake_today
            result = db.get_daily_max_temps(5)

        self.assertEqual(result, [])


class TestCameraPhotoTimesCRUD(unittest.TestCase):
    """Testet CRUD für die Tabelle camera_photo_times (Feature 0030)."""

    def setUp(self):
        self.db_path = _make_temp_db()
        self._patcher = patch.object(db, "DB_PATH", self.db_path)
        self._patcher.start()
        db.init_db()

    def tearDown(self):
        self._patcher.stop()
        import gc; gc.collect()
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_get_photo_times_leer(self):
        self.assertEqual(db.get_photo_times(), [])

    def test_add_und_get(self):
        self.assertTrue(db.add_photo_time("08:00"))
        self.assertTrue(db.add_photo_time("18:00"))
        times = db.get_photo_times()
        self.assertEqual(len(times), 2)
        self.assertIn("08:00", [t["time"] for t in times])

    def test_get_photo_times_sortiert(self):
        db.add_photo_time("18:00")
        db.add_photo_time("06:00")
        db.add_photo_time("12:00")
        times = db.get_photo_times()
        times_list = [t["time"] for t in times]
        self.assertEqual(times_list, sorted(times_list))

    def test_duplikat_wird_ignoriert(self):
        db.add_photo_time("08:00")
        db.add_photo_time("08:00")
        self.assertEqual(len(db.get_photo_times()), 1)

    def test_delete_photo_time(self):
        db.add_photo_time("08:00")
        times = db.get_photo_times()
        self.assertTrue(db.delete_photo_time(times[0]["id"]))
        self.assertEqual(db.get_photo_times(), [])

    def test_delete_nicht_vorhandene_id(self):
        result = db.delete_photo_time(9999)
        self.assertFalse(result)

    def test_migration_auf_bestehender_db(self):
        """Zweiter init_db()-Aufruf auf existierender DB ist idempotent."""
        db.add_photo_time("10:00")
        db.init_db()
        self.assertEqual(len(db.get_photo_times()), 1)


if __name__ == "__main__":
    unittest.main()
