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


class TestAufnahmeVerzug(unittest.TestCase):
    """Zweite Alarmklasse der Kamera-Ueberwachung: Aufnahme-Verzug (ADR 0041)."""

    MAC = "AA:BB:CC:DD:EE:01"

    def setUp(self):
        self.db_path = _make_temp_db()
        self._db_patcher = patch.object(db, "DB_PATH", self.db_path)
        self._db_patcher.start()
        db.init_db()
        db.add_camera(self.MAC, "Garten01")
        self.events = []
        from daemon.core.camera_events import (
            CameraDelayAlertTriggered, CameraDelayAlertResolved,
        )
        _global_bus.subscribe(CameraDelayAlertTriggered, self.events.append)
        _global_bus.subscribe(CameraDelayAlertResolved, self.events.append)

    def tearDown(self):
        self._db_patcher.stop()
        self.db_path.unlink(missing_ok=True)

    def _erfuellt(self, verzug_minuten: int):
        """Simuliert einen erfuellten Aufnahme-Zeitpunkt mit dem gegebenen Verzug."""
        from daemon.core.camera_events import TimedPhotoCaptured
        target = datetime(2026, 7, 14, 8, 0)
        _global_bus.publish(TimedPhotoCaptured(
            "Garten01", "/tmp/x.jpg", "📷 Foto um 08:00",
            target_dt=target,
            captured_at=target + timedelta(minutes=verzug_minuten),
            mac_address=self.MAC,
        ))

    def test_ein_einzelner_verzug_meldet_noch_nicht(self):
        """Ein WLAN-Wackler soll nicht nachts melden — erst der zweite Verzug in Folge."""
        watchdog.initialize()
        self._erfuellt(28)

        assert self.events == [], "Ein einzelner Verzug darf keine Warnung ausloesen"

    def test_zweiter_verzug_in_folge_meldet(self):
        from daemon.core.camera_events import CameraDelayAlertTriggered
        watchdog.initialize()
        self._erfuellt(28)
        self._erfuellt(16)

        alarme = [e for e in self.events if isinstance(e, CameraDelayAlertTriggered)]
        assert len(alarme) == 1, f"Erwartet genau eine Warnung, war {len(alarme)}"
        assert alarme[0].mac_address == self.MAC

    def test_puenktlicher_treffer_entwarnt(self):
        from daemon.core.camera_events import CameraDelayAlertResolved
        watchdog.initialize()
        self._erfuellt(28)
        self._erfuellt(16)
        self.events.clear()

        self._erfuellt(0)

        entwarnungen = [e for e in self.events if isinstance(e, CameraDelayAlertResolved)]
        assert len(entwarnungen) == 1, "Ein puenktlicher Aufnahme-Zeitpunkt muss entwarnen"


class TestVerpassteAufnahmeZeitpunkte(unittest.TestCase):
    """Ein abgeloester Aufnahme-Zeitpunkt ohne Bild gilt als maximal verzoegert (ADR 0041)."""

    MAC = "AA:BB:CC:DD:EE:02"

    def setUp(self):
        self.db_path = _make_temp_db()
        self._db_patcher = patch.object(db, "DB_PATH", self.db_path)
        self._db_patcher.start()
        db.init_db()
        db.add_camera(self.MAC, "Garten01")
        # Kamera meldet sich regelmaessig — der Inaktivitaets-Watchdog schweigt also
        db.update_camera_on_upload(self.MAC)
        # Die Tests rechnen mit `datetime.now()`; ein aktiver Tageslicht-Filter machte sie
        # tagsueber gruen und nachts rot. Die Wechselwirkung Filter↔Verzugsmeldung prueft
        # `test_unterdrueckter_zeitpunkt_gilt_nicht_als_verpasst` mit festem Praedikat.
        self._daylight_patcher = patch(
            "daemon.camera_daylight.build_photo_filter", return_value=None
        )
        self._daylight_patcher.start()
        self.events = []
        from daemon.core.camera_events import CameraDelayAlertTriggered
        _global_bus.subscribe(CameraDelayAlertTriggered, self.events.append)

    def tearDown(self):
        self._daylight_patcher.stop()
        self._db_patcher.stop()
        self.db_path.unlink(missing_ok=True)

    def test_unterdrueckter_zeitpunkt_gilt_nicht_als_verpasst(self):
        """Bei Dunkelheit entfaellt der Aufnahme-Zeitpunkt — das ist Absicht, kein Verzug.

        Ohne diese Kopplung haette der Filter das schwarze Foto nur durch einen Fehlalarm
        ersetzt (ADR 0041/0047).
        """
        from datetime import datetime, timedelta
        self._daylight_patcher.stop()
        dunkel = patch(
            "daemon.camera_daylight.build_photo_filter",
            return_value=(lambda target_dt, label: False),
        )
        dunkel.start()
        self.addCleanup(dunkel.stop)

        now = datetime.now()
        for stunden in (4, 3, 2):
            t = (now - timedelta(hours=stunden)).replace(second=0, microsecond=0)
            db.add_photo_time(t.strftime("%H:%M"))
        zuletzt = (now - timedelta(hours=5)).replace(second=0, microsecond=0)
        db.set_metadata(f"last_delivered_target:{self.MAC}", zuletzt.isoformat())

        watchdog.run_watchdog_check()

        assert self.events == [], \
            "Ein bei Dunkelheit unterdrueckter Zeitpunkt darf keinen Verzug melden"

    def test_zwei_abgeloeste_zeitpunkte_ohne_bild_melden(self):
        """Drei faellige Zeitpunkte ohne Bild: zwei sind abgeloest (= verpasst), einer noch offen."""
        from datetime import datetime, timedelta
        now = datetime.now()
        for stunden in (4, 3, 2):
            t = (now - timedelta(hours=stunden)).replace(second=0, microsecond=0)
            db.add_photo_time(t.strftime("%H:%M"))
        # Zuletzt zugestellt: ein Zeitpunkt von vor 5 Stunden
        zuletzt = (now - timedelta(hours=5)).replace(second=0, microsecond=0)
        db.set_metadata(f"last_delivered_target:{self.MAC}", zuletzt.isoformat())

        watchdog.run_watchdog_check()

        assert len(self.events) == 1, \
            f"Zwei abgeloeste Zeitpunkte ohne Bild muessen melden, war {len(self.events)}"

    def test_kein_doppelzaehlen_ueber_mehrere_pruefläufe(self):
        """Derselbe verpasste Zeitpunkt darf nicht bei jedem stuendlichen Lauf erneut zaehlen."""
        from datetime import datetime, timedelta
        now = datetime.now()
        t1 = (now - timedelta(hours=2)).replace(second=0, microsecond=0)
        db.add_photo_time(t1.strftime("%H:%M"))
        db.add_photo_time((now + timedelta(hours=1)).strftime("%H:%M"))  # noch offen
        zuletzt = (now - timedelta(hours=3)).replace(second=0, microsecond=0)
        db.set_metadata(f"last_delivered_target:{self.MAC}", zuletzt.isoformat())

        watchdog.run_watchdog_check()
        watchdog.run_watchdog_check()
        watchdog.run_watchdog_check()

        assert self.events == [], \
            "Ein einzelner verpasster Zeitpunkt darf auch nach mehreren Pruefläufen nicht melden"


class TestVerpasstEntwarntNie(unittest.TestCase):
    """Ein verpasster Aufnahme-Zeitpunkt ist keine Puenktlichkeit — er darf nie entwarnen."""

    MAC = "AA:BB:CC:DD:EE:03"

    def setUp(self):
        self.db_path = _make_temp_db()
        self._db_patcher = patch.object(db, "DB_PATH", self.db_path)
        self._db_patcher.start()
        db.init_db()
        db.add_camera(self.MAC, "Garten01")
        db.update_camera_on_upload(self.MAC)
        self.events = []
        from daemon.core.camera_events import CameraDelayAlertTriggered, CameraDelayAlertResolved
        _global_bus.subscribe(CameraDelayAlertTriggered, self.events.append)
        _global_bus.subscribe(CameraDelayAlertResolved, self.events.append)

    def tearDown(self):
        self._db_patcher.stop()
        self.db_path.unlink(missing_ok=True)

    def test_kurz_zurueckliegender_verpasster_zeitpunkt_entwarnt_nicht(self):
        """Zwei dicht beieinander liegende Fotozeiten: der aeltere ist verpasst, aber erst
        wenige Minuten her. Er darf NICHT als 'puenktlich' durchgehen und den Alarm loeschen.
        """
        from datetime import datetime, timedelta
        from daemon.core.camera_events import CameraDelayAlertResolved
        now = datetime.now()

        # Ein Verzugs-Alarm laeuft bereits
        db.set_metadata(f"watchdog_delay_alert_active_camera_{self.MAC}", "1")
        db.set_metadata(f"watchdog_delay_streak_camera_{self.MAC}", "2")

        # Fotozeiten vor 12 und vor 4 Minuten -> die erste ist abgeloest (verpasst),
        # ihr Abstand zu jetzt (12 min) liegt UNTER der Schwelle von 15 min.
        for minuten in (12, 4):
            t = (now - timedelta(minutes=minuten)).replace(second=0, microsecond=0)
            db.add_photo_time(t.strftime("%H:%M"))
        zuletzt = (now - timedelta(minutes=30)).replace(second=0, microsecond=0)
        db.set_metadata(f"last_delivered_target:{self.MAC}", zuletzt.isoformat())

        watchdog.run_watchdog_check()

        entwarnungen = [e for e in self.events if isinstance(e, CameraDelayAlertResolved)]
        assert entwarnungen == [], "Ein verpasster Zeitpunkt darf niemals entwarnen"
        assert db.get_metadata(f"watchdog_delay_alert_active_camera_{self.MAC}") == "1", \
            "Der Alarm muss bestehen bleiben"

    def test_verpasst_bei_flag_ohne_streak_entwarnt_nicht(self):
        """Desync-Absicherung: Flag aktiv, aber Streak-Zaehler fehlt (z.B. nach OTA-Migration
        oder einem Thread-Race). Ein gestoerter (verpasster) Aufnahme-Zeitpunkt zaehlt die
        Streak neu ab 1 hoch — er darf den bestehenden Alarm dabei NICHT loeschen. Ein
        gestoerter Zustand ist niemals eine Entwarnung, egal wie die Streak steht.
        """
        from daemon.core.camera_events import CameraDelayAlertResolved

        db.set_metadata(f"watchdog_delay_alert_active_camera_{self.MAC}", "1")
        # kein Streak gesetzt -> get_metadata liefert None -> Streak wird auf 1 gezaehlt (< 2)

        watchdog._bewerte_stoerung(
            self.MAC, "Garten01", gestoert=True, grund="verpasst", zeitpunkte=["08:00"],
        )

        entwarnungen = [e for e in self.events if isinstance(e, CameraDelayAlertResolved)]
        assert entwarnungen == [], "Ein gestoerter Zeitpunkt darf nie entwarnen"
        assert db.get_metadata(f"watchdog_delay_alert_active_camera_{self.MAC}") == "1", \
            "Der Alarm muss bestehen bleiben"
