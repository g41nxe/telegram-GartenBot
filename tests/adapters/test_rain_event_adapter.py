"""Regenereignis-Adapter: Persistenz des Zustands + Publikation der Übergänge (ADR 0043)."""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.adapters.rain_event_adapter import RainEventAdapter
from daemon.core.sensor_events import RainEventEnded, RainEventStarted, RainSensorMeasured

T0 = datetime(2026, 7, 6, 11, 40, 0)


def _measurement(mm):
    return RainSensorMeasured(mm, 100.0, 18.0, 90, mm >= 0.1)


class TestRainEventAdapter(unittest.TestCase):

    def setUp(self):
        self.store = {}
        p = patch("daemon.adapters.rain_event_adapter.database")
        db = p.start()
        self.addCleanup(p.stop)
        db.get_metadata.side_effect = lambda k, d=None: self.store.get(k, d)
        db.set_metadata.side_effect = lambda k, v: self.store.__setitem__(k, v)
        # Ticket l97: die Flag-Primitive an denselben Store koppeln (spiegelt database.get/set_flag).
        db.get_flag.side_effect = lambda k: self.store.get(k) == "1"
        db.set_flag.side_effect = lambda k, v: self.store.__setitem__(k, "1" if v else "0")

    def _feed(self, adapter, mm, when):
        with patch("daemon.adapters.rain_event_adapter.datetime") as dt:
            dt.now.return_value = when
            dt.fromisoformat = datetime.fromisoformat
            adapter._on_rain_sensor_measured(_measurement(mm))

    def _published(self, bus, cls):
        return [c.args[0] for c in bus.publish.call_args_list if isinstance(c.args[0], cls)]

    def test_first_tick_publishes_started_and_persists_state(self):
        bus = MagicMock()
        adapter = RainEventAdapter(bus)

        self._feed(adapter, 0.5, T0)

        self.assertEqual(len(self._published(bus, RainEventStarted)), 1)
        self.assertEqual(self.store.get("rain_event_active"), "1")

    def test_restart_mid_event_does_not_publish_started_again(self):
        bus1 = MagicMock()
        self._feed(RainEventAdapter(bus1), 0.5, T0)          # Regen beginnt

        bus2 = MagicMock()                                    # Daemon-Neustart: neue Instanz,
        adapter2 = RainEventAdapter(bus2)                     # derselbe persistierte Zustand
        self._feed(adapter2, 0.5, T0 + timedelta(minutes=20))

        self.assertEqual(self._published(bus2, RainEventStarted), [])   # kein doppeltes "erkannt"

    def test_honours_configured_threshold(self):
        """RAIN_SENSOR_THRESHOLD_MM muss auch für die Ereignis-Erkennung gelten."""
        bus = MagicMock()
        adapter = RainEventAdapter(bus)

        with patch("daemon.adapters.rain_event_adapter.datetime") as dt, \
             patch("daemon.adapters.rain_event_adapter.config") as cfg:
            dt.now.return_value = T0
            dt.fromisoformat = datetime.fromisoformat
            cfg.RAIN_EVENT_GRACE_MINUTES = 45
            cfg.RAIN_SENSOR_THRESHOLD_MM = 1.0      # strenger als ein 0,5-mm-Kipp
            adapter._on_rain_sensor_measured(_measurement(0.5))

        self.assertEqual(self._published(bus, RainEventStarted), [])

    def test_event_ends_after_grace_with_accumulated_total(self):
        bus = MagicMock()
        adapter = RainEventAdapter(bus)
        self._feed(adapter, 0.5, T0)
        self._feed(adapter, 0.5, T0 + timedelta(minutes=20))

        self._feed(adapter, 0.0, T0 + timedelta(minutes=90))   # weit nach der Karenzzeit

        ended = self._published(bus, RainEventEnded)
        self.assertEqual(len(ended), 1)
        self.assertEqual(ended[0].total_mm, 1.0)
        self.assertEqual(ended[0].duration_minutes, 20)
        self.assertEqual(self.store.get("rain_event_active"), "0")


if __name__ == "__main__":
    unittest.main()
