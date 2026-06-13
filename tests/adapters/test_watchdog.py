import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import daemon.adapters.database as db
from daemon.adapters import watchdog
from daemon.adapters.mqtt_client import _global_bus
from daemon.core.watchdog_events import InactivityAlertResolved, InactivityAlertTriggered
from daemon.core.valve_events import ValveStatusReported


def _make_temp_db() -> Path:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return Path(f.name)


def _set_last_update(db_path: Path, mqtt_name: str, last_update: str | None):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE valves SET last_update = ? WHERE mqtt_name = ?",
        (last_update, mqtt_name),
    )
    conn.commit()
    conn.close()


class TestWatchdogCheck(unittest.TestCase):
    """Tests für run_watchdog_check() mit echter Testdatenbank."""

    def setUp(self):
        self.db_path = _make_temp_db()
        self._db_patcher = patch.object(db, "DB_PATH", self.db_path)
        self._db_patcher.start()
        db.init_db()
        # Füge Testventil hinzu (init_db legt bereits "garden_valve" mit last_update=NULL an)
        self.valve_id = db.add_valve("Testventil", "test_valve")

    def tearDown(self):
        self._db_patcher.stop()
        import gc
        gc.collect()
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_alert_triggered_when_valve_silent(self):
        """Ventil > 24h still und kein Flag → InactivityAlertTriggered, Flag auf '1'."""
        old = (datetime.now() - timedelta(hours=25)).isoformat()
        _set_last_update(self.db_path, "test_valve", old)

        captured = []
        _global_bus.subscribe(InactivityAlertTriggered, captured.append)
        try:
            with patch("daemon.adapters.watchdog.config.WATCHDOG_ENABLED", True), \
                 patch("daemon.adapters.watchdog.config.WATCHDOG_VALVE_TIMEOUT_HOURS", 24.0):
                watchdog.run_watchdog_check()
        finally:
            _global_bus.unsubscribe(InactivityAlertTriggered, captured.append)

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].valve_id, self.valve_id)
        self.assertGreater(captured[0].hours_silent, 24.0)
        self.assertEqual(db.get_metadata(f"watchdog_alert_active_valve_{self.valve_id}"), "1")

    def test_no_duplicate_alert_when_flag_set(self):
        """Flag bereits '1' → kein zweites InactivityAlertTriggered."""
        old = (datetime.now() - timedelta(hours=25)).isoformat()
        _set_last_update(self.db_path, "test_valve", old)
        db.set_metadata(f"watchdog_alert_active_valve_{self.valve_id}", "1")

        captured = []
        _global_bus.subscribe(InactivityAlertTriggered, captured.append)
        try:
            with patch("daemon.adapters.watchdog.config.WATCHDOG_ENABLED", True), \
                 patch("daemon.adapters.watchdog.config.WATCHDOG_VALVE_TIMEOUT_HOURS", 24.0):
                watchdog.run_watchdog_check()
        finally:
            _global_bus.unsubscribe(InactivityAlertTriggered, captured.append)

        self.assertEqual(len(captured), 0)

    def test_null_last_update_skipped(self):
        """Ventil ohne last_update → kein Event."""
        _set_last_update(self.db_path, "test_valve", None)

        captured = []
        _global_bus.subscribe(InactivityAlertTriggered, captured.append)
        try:
            with patch("daemon.adapters.watchdog.config.WATCHDOG_ENABLED", True), \
                 patch("daemon.adapters.watchdog.config.WATCHDOG_VALVE_TIMEOUT_HOURS", 24.0):
                watchdog.run_watchdog_check()
        finally:
            _global_bus.unsubscribe(InactivityAlertTriggered, captured.append)

        self.assertEqual(len(captured), 0)

    def test_watchdog_disabled_returns_early(self):
        """WATCHDOG_ENABLED=False → kein Event."""
        old = (datetime.now() - timedelta(hours=25)).isoformat()
        _set_last_update(self.db_path, "test_valve", old)

        captured = []
        _global_bus.subscribe(InactivityAlertTriggered, captured.append)
        try:
            with patch("daemon.adapters.watchdog.config.WATCHDOG_ENABLED", False):
                watchdog.run_watchdog_check()
        finally:
            _global_bus.unsubscribe(InactivityAlertTriggered, captured.append)

        self.assertEqual(len(captured), 0)

    def test_multiple_valves_only_inactive_triggers(self):
        """Inaktives und aktives Ventil — nur das inaktive löst Alert aus."""
        old = (datetime.now() - timedelta(hours=25)).isoformat()
        recent = (datetime.now() - timedelta(minutes=30)).isoformat()
        _set_last_update(self.db_path, "test_valve", old)
        db.add_valve("Aktives Ventil", "active_valve")
        _set_last_update(self.db_path, "active_valve", recent)

        captured = []
        _global_bus.subscribe(InactivityAlertTriggered, captured.append)
        try:
            with patch("daemon.adapters.watchdog.config.WATCHDOG_ENABLED", True), \
                 patch("daemon.adapters.watchdog.config.WATCHDOG_VALVE_TIMEOUT_HOURS", 24.0):
                watchdog.run_watchdog_check()
        finally:
            _global_bus.unsubscribe(InactivityAlertTriggered, captured.append)

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].valve_id, self.valve_id)

    def test_recovery_via_watchdog_check(self):
        """Flag gesetzt, Ventil wieder aktiv → InactivityAlertResolved beim nächsten Check."""
        recent = (datetime.now() - timedelta(minutes=30)).isoformat()
        _set_last_update(self.db_path, "test_valve", recent)
        db.set_metadata(f"watchdog_alert_active_valve_{self.valve_id}", "1")

        captured = []
        _global_bus.subscribe(InactivityAlertResolved, captured.append)
        try:
            with patch("daemon.adapters.watchdog.config.WATCHDOG_ENABLED", True), \
                 patch("daemon.adapters.watchdog.config.WATCHDOG_VALVE_TIMEOUT_HOURS", 24.0):
                watchdog.run_watchdog_check()
        finally:
            _global_bus.unsubscribe(InactivityAlertResolved, captured.append)

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].valve_id, self.valve_id)
        self.assertNotEqual(db.get_metadata(f"watchdog_alert_active_valve_{self.valve_id}"), "1")

    def test_resolution_via_status_handler(self):
        """Flag gesetzt → ValveStatusReported-Handler → InactivityAlertResolved + Flag gelöscht."""
        old = (datetime.now() - timedelta(hours=25)).isoformat()
        _set_last_update(self.db_path, "test_valve", old)
        db.set_metadata(f"watchdog_alert_active_valve_{self.valve_id}", "1")

        captured = []
        _global_bus.subscribe(InactivityAlertResolved, captured.append)
        try:
            watchdog._on_valve_status(
                ValveStatusReported(
                    mqtt_name="test_valve", state="ON", flow_rate=0.0,
                    battery=100, linkquality=200,
                )
            )
        finally:
            _global_bus.unsubscribe(InactivityAlertResolved, captured.append)

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].valve_id, self.valve_id)
        self.assertNotEqual(db.get_metadata(f"watchdog_alert_active_valve_{self.valve_id}"), "1")

    def test_status_handler_noop_when_no_flag(self):
        """ValveStatusReported ohne aktives Flag → kein Event."""
        recent = (datetime.now() - timedelta(minutes=30)).isoformat()
        _set_last_update(self.db_path, "test_valve", recent)

        captured = []
        _global_bus.subscribe(InactivityAlertResolved, captured.append)
        try:
            watchdog._on_valve_status(
                ValveStatusReported(
                    mqtt_name="test_valve", state="ON", flow_rate=0.0,
                    battery=100, linkquality=200,
                )
            )
        finally:
            _global_bus.unsubscribe(InactivityAlertResolved, captured.append)

        self.assertEqual(len(captured), 0)


if __name__ == "__main__":
    unittest.main()
