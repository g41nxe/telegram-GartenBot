import sys
import sqlite3
import tempfile
import unittest
from datetime import datetime
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


if __name__ == "__main__":
    unittest.main()
