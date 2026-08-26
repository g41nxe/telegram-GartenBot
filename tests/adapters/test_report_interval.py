import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import daemon.adapters.database as db


class TestDeviceReportInterval(unittest.TestCase):
    """Misst den typischen Melde-Takt eines Geräts aus device_status_log (Ticket 8zj)."""

    def setUp(self):
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        f.close()
        self.db_path = Path(f.name)
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

    def _log(self, device: str, times: list):
        conn = sqlite3.connect(self.db_path)
        conn.executemany(
            "INSERT INTO device_status_log (timestamp, device_name, battery, linkquality) "
            "VALUES (?, ?, 100, 150)",
            [(t.isoformat(), device) for t in times],
        )
        conn.commit()
        conn.close()

    def _every(self, seconds: int, count: int, device="valve_a", start=None):
        base = start or datetime(2026, 8, 20, 12, 0, 0)
        self._log(device, [base + timedelta(seconds=i * seconds) for i in range(count)])

    def test_measures_regular_interval(self):
        """Gleichmäßiger 5-Minuten-Takt → 300 Sekunden."""
        self._every(300, 20)
        self.assertAlmostEqual(db.get_device_report_interval_seconds("valve_a"), 300.0, places=1)

    def test_measures_fast_interval(self):
        """Der zweite Ventiltyp funkt alle 6 Sekunden."""
        self._every(6, 30)
        self.assertAlmostEqual(db.get_device_report_interval_seconds("valve_a"), 6.0, places=1)

    def test_median_ignores_single_outage(self):
        """Eine einzelne lange Lücke darf den Takt nicht verfälschen — deshalb Median.

        Ein Mittelwert würde durch den Ausfall selbst nach oben gezogen und die Schwelle
        genau dann anheben, wenn sie greifen soll.
        """
        base = datetime(2026, 8, 20, 12, 0, 0)
        times = [base + timedelta(seconds=i * 300) for i in range(10)]
        times.append(times[-1] + timedelta(hours=9))     # Ausfall
        times.append(times[-1] + timedelta(seconds=300))
        self._log("valve_a", times)
        self.assertAlmostEqual(db.get_device_report_interval_seconds("valve_a"), 300.0, places=1)

    def test_unknown_device_returns_none(self):
        """Kein Gerät, keine Messung — der Aufrufer fällt auf den Fixwert zurück."""
        self.assertIsNone(db.get_device_report_interval_seconds("gibt_es_nicht"))

    def test_single_entry_returns_none(self):
        """Ein einziger Eintrag ergibt keinen Abstand."""
        self._every(300, 1)
        self.assertIsNone(db.get_device_report_interval_seconds("valve_a"))

    def test_isolates_devices(self):
        """Der Takt des einen Geräts darf den des anderen nicht beeinflussen."""
        self._every(300, 20, device="valve_a")
        self._every(6, 40, device="valve_b")
        self.assertAlmostEqual(db.get_device_report_interval_seconds("valve_a"), 300.0, places=1)
        self.assertAlmostEqual(db.get_device_report_interval_seconds("valve_b"), 6.0, places=1)

    def test_uses_only_recent_sample(self):
        """Ein alter, langsamerer Takt darf den heutigen nicht überstimmen."""
        alt = datetime(2026, 1, 1, 12, 0, 0)
        self._log("valve_a", [alt + timedelta(hours=i) for i in range(30)])
        self._every(300, 30, start=datetime(2026, 8, 20, 12, 0, 0))
        self.assertAlmostEqual(
            db.get_device_report_interval_seconds("valve_a", sample=20), 300.0, places=1
        )


if __name__ == "__main__":
    unittest.main()
