import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.event_bus import EventBus
from daemon.adapters.mqtt_client import SimulatedMqttAdapter
from daemon.core.mist_controller import MistController
from daemon.core.mist_events import MistIntervalStarted, MistIntervalEnded


class TestNebelController(unittest.TestCase):
    """Tests für die Nebel-Steuerung (Burst-Loop). Timing wird über die Transitions-
    Methoden direkt getrieben — keine sleep-basierten Tests."""

    def setUp(self):
        self.bus = EventBus()
        self.client = SimulatedMqttAdapter(self.bus)
        self.claim = Mock()
        self.release = Mock()
        self.nebel = MistController(self.bus, self.client.publish,
                                     claim_fn=self.claim, release_fn=self.release)
        self.assertTrue(self.client.connect())

    def tearDown(self):
        self.client.disconnect()

    def _future(self, minutes=30):
        return datetime.now() + timedelta(minutes=minutes)

    def test_start_opens_valve_and_emits_started(self):
        started = []
        self.bus.subscribe(MistIntervalStarted, lambda e: started.append(e))

        self.nebel.start("terrace_mist", on_seconds=20, pause_minutes=5,
                         end_time=self._future(), source="nebel")

        self.assertTrue(self.nebel.is_active("terrace_mist"))
        self.assertEqual(self.client.get_valve_status()["state"], "ON")
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0].mqtt_name, "terrace_mist")
        self.claim.assert_called_once_with("terrace_mist")

    def test_end_burst_closes_then_next_burst_reopens(self):
        self.nebel.start("terrace_mist", 20, 5, self._future(), "nebel")
        self.assertEqual(self.client.get_valve_status()["state"], "ON")

        self.nebel._end_burst("terrace_mist")          # Stoß-Ende → Pause
        self.assertEqual(self.client.get_valve_status()["state"], "OFF")
        self.assertTrue(self.nebel.is_active("terrace_mist"))

        self.nebel._begin_burst("terrace_mist")        # nächster Nebelstoß
        self.assertEqual(self.client.get_valve_status()["state"], "ON")

    def test_stop_closes_valve_and_emits_ended_once(self):
        ended = []
        self.bus.subscribe(MistIntervalEnded, lambda e: ended.append(e))

        self.nebel.start("terrace_mist", 20, 5, self._future(), "nebel")
        self.nebel.stop("terrace_mist")

        self.assertFalse(self.nebel.is_active("terrace_mist"))
        self.assertEqual(self.client.get_valve_status()["state"], "OFF")
        self.assertEqual(len(ended), 1)
        self.assertEqual(ended[0].mqtt_name, "terrace_mist")
        self.release.assert_called_once_with("terrace_mist")

    def test_reaching_end_time_finishes_window(self):
        ended = []
        self.bus.subscribe(MistIntervalEnded, lambda e: ended.append(e))

        self.nebel.start("terrace_mist", 20, 5, self._future(), "nebel")
        # Fensterende erreichen, während ein Stoß läuft:
        self.nebel._cycles["terrace_mist"]["end_time"] = datetime.now() - timedelta(seconds=1)
        self.nebel._end_burst("terrace_mist")

        self.assertFalse(self.nebel.is_active("terrace_mist"))
        self.assertEqual(self.client.get_valve_status()["state"], "OFF")
        self.assertEqual(len(ended), 1)

    def test_begin_burst_warns_on_publish_failure(self):
        """Schlägt der ON-Publish fehl (z.B. MQTT down), wird gewarnt — das Fenster läuft weiter."""
        bus = EventBus()
        nebel = MistController(bus, lambda t, p: False)   # Publish schlägt immer fehl
        try:
            with self.assertLogs("garden_nebel_controller", level="WARNING") as cm:
                nebel.start("terrace_mist", 20, 5, self._future(), "nebel")
            self.assertTrue(any("ON" in m for m in cm.output))
            self.assertTrue(nebel.is_active("terrace_mist"))
        finally:
            nebel.stop()

    def test_start_is_idempotent(self):
        """Zustandsloses Anstoßen durch den Scheduler darf keinen zweiten Lauf erzeugen."""
        started = []
        self.bus.subscribe(MistIntervalStarted, lambda e: started.append(e))

        self.nebel.start("terrace_mist", 20, 5, self._future(), "nebel")
        ok, _ = self.nebel.start("terrace_mist", 20, 5, self._future(), "nebel")

        self.assertFalse(ok)
        self.assertEqual(len(started), 1)
        self.claim.assert_called_once_with("terrace_mist")

    # --- get_active_window (Lese-Schnittstelle fürs Stopp-Menü) ---

    def test_get_active_window_none_when_idle(self):
        self.assertIsNone(self.nebel.get_active_window())

    def test_get_active_window_returns_running_valve(self):
        self.nebel.start("terrace_mist", 20, 5, self._future(), "nebel")
        self.assertEqual(self.nebel.get_active_window(), "terrace_mist")
        self.nebel.stop("terrace_mist")
        self.assertIsNone(self.nebel.get_active_window())

    # --- Restart-Unterdrückung (C1, in-memory) ---

    def test_stop_suppresses_until_end_time(self):
        """Manueller Stopp merkt sich die Fenster-Endzeit und unterdrückt bis dahin."""
        end = self._future(30)
        self.nebel.start("terrace_mist", 20, 5, end, "nebel")
        self.assertFalse(self.nebel.is_suppressed("terrace_mist"))

        self.nebel.stop("terrace_mist")
        self.assertTrue(self.nebel.is_suppressed("terrace_mist"))

    def test_is_suppressed_lazy_expires_after_end_time(self):
        """Nach Ablauf der Endzeit läuft die Sperre lazy ab."""
        self.nebel._suppressed_until["terrace_mist"] = datetime.now() - timedelta(minutes=1)
        self.assertFalse(self.nebel.is_suppressed("terrace_mist"))
        # nach dem Lazy-Ablauf ist der Eintrag entfernt
        self.assertNotIn("terrace_mist", self.nebel._suppressed_until)

    def test_start_clears_suppression(self):
        """Expliziter Neustart hebt die Sperre auf (Neustart gewinnt)."""
        self.nebel.start("terrace_mist", 20, 5, self._future(), "nebel")
        self.nebel.stop("terrace_mist")
        self.assertTrue(self.nebel.is_suppressed("terrace_mist"))

        self.nebel.start("terrace_mist", 20, 5, self._future(), "nebel")
        self.assertFalse(self.nebel.is_suppressed("terrace_mist"))
        self.nebel.stop("terrace_mist")

    def test_is_suppressed_unknown_valve_is_false(self):
        self.assertFalse(self.nebel.is_suppressed("never_seen"))


if __name__ == "__main__":
    unittest.main()
