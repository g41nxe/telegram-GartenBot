"""Ticket cy1: reine Zustandsmaschine des Assistenten (Zeitplan-Pilot).

Der Assistent besitzt Zustand (step/data/prompt_msg_id) und die Übergänge; advance(value)
liefert eine reine Absicht (Prompt / Reject / Done) — kein I/O, keine Telegram-Aufrufe.
Die lebende-Prompt-Invariante (ADR 0039) und das Rendering leben im späteren Live-Adapter.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.assistent import ScheduleAssistent, Prompt, Reject, Done


def _valves(n):
    return [{"id": i, "wish_name": f"V{i}"} for i in range(1, n + 1)]


class TestScheduleAssistentHappyPath(unittest.TestCase):
    """Wässern-Pfad: name → hour → minute → duration → volume → (valve) → days → confirm."""

    def _run_to_days(self, valves):
        a = ScheduleAssistent(mode="watering", valves=valves)
        self.assertIsInstance(a.start(), Prompt)
        self.assertEqual(a.step, "name")
        self.assertIsInstance(a.advance("Rasen"), Prompt)
        self.assertEqual(a.data["name"], "Rasen")
        self.assertEqual(a.step, "hour")
        a.advance(14)
        self.assertEqual(a.data["hour"], 14)
        self.assertEqual(a.step, "minute")
        a.advance(30)
        self.assertEqual(a.data["minute"], 30)
        self.assertEqual(a.step, "duration")
        a.advance(10)
        self.assertEqual(a.data["duration"], 10)
        self.assertEqual(a.step, "volume")
        return a

    def test_single_valve_skips_valve_step(self):
        a = self._run_to_days(_valves(1))
        a.advance(25)  # volume preset
        self.assertEqual(a.data["volume"], 25)
        self.assertEqual(a.data["valve_id"], 1)      # auto-zugewiesen
        self.assertEqual(a.step, "days")             # Ventil-Schritt übersprungen

    def test_multi_valve_asks_valve(self):
        a = self._run_to_days(_valves(3))
        a.advance(25)
        self.assertEqual(a.step, "valve")
        a.advance(2)                                 # Ventil-Auswahl
        self.assertEqual(a.data["valve_id"], 2)
        self.assertEqual(a.step, "days")

    def test_full_flow_terminates_with_done(self):
        a = self._run_to_days(_valves(1))
        a.advance(25)
        # days: einen Tag wählen, dann bestätigen
        a.advance("Mon")
        self.assertIn("Mon", a.data["days"])
        p = a.advance("save")                        # Wochentag-Auswahl fertig
        self.assertIsInstance(p, Prompt)
        self.assertEqual(a.step, "confirm")
        result = a.advance("confirm")
        self.assertIsInstance(result, Done)
        self.assertEqual(result.data["name"], "Rasen")
        self.assertEqual(result.data["hour"], 14)
        self.assertEqual(result.data["minute"], 30)
        self.assertEqual(result.data["duration"], 10)
        self.assertEqual(result.data["volume"], 25)
        self.assertEqual(result.data["days"], ["Mon"])
        self.assertEqual(result.data["valve_id"], 1)
        self.assertEqual(result.data["mode"], "watering")


class TestScheduleAssistentValidation(unittest.TestCase):

    def test_empty_name_rejected_no_step_change(self):
        a = ScheduleAssistent(mode="watering", valves=_valves(1))
        a.start()
        r = a.advance("   ")
        self.assertIsInstance(r, Reject)
        self.assertEqual(a.step, "name")             # ADR 0039: kein Schritt-Wechsel

    def test_days_empty_rejected(self):
        a = ScheduleAssistent(mode="watering", valves=_valves(1))
        a.start(); a.advance("Rasen"); a.advance(14); a.advance(30); a.advance(10); a.advance(25)
        self.assertEqual(a.step, "days")
        r = a.advance("save")                        # ohne Tag
        self.assertIsInstance(r, Reject)
        self.assertEqual(a.step, "days")

    def test_custom_duration_out_of_range_rejected(self):
        a = ScheduleAssistent(mode="watering", valves=_valves(1))
        a.start(); a.advance("Rasen"); a.advance(14); a.advance(30)
        a.advance("custom")
        self.assertEqual(a.step, "duration_custom")
        self.assertIsInstance(a.advance(99), Reject)  # > 25
        self.assertEqual(a.step, "duration_custom")
        a.advance(12)
        self.assertEqual(a.data["duration"], 12)
        self.assertEqual(a.step, "volume")

    def test_custom_volume_non_positive_rejected(self):
        a = ScheduleAssistent(mode="watering", valves=_valves(1))
        a.start(); a.advance("Rasen"); a.advance(14); a.advance(30); a.advance(10)
        a.advance("custom")
        self.assertEqual(a.step, "volume_custom")
        self.assertIsInstance(a.advance(0), Reject)
        a.advance(40)
        self.assertEqual(a.data["volume"], 40)

    def test_custom_duration_non_numeric_rejected(self):
        """Review-Befund: getippter Unsinn darf nicht crashen (alter Wizard fing ValueError)."""
        a = ScheduleAssistent(mode="watering", valves=_valves(1))
        a.start(); a.advance("Rasen"); a.advance(14); a.advance(30)
        a.advance("custom")
        r = a.advance("abc")
        self.assertIsInstance(r, Reject)
        self.assertEqual(a.step, "duration_custom")

    def test_custom_volume_non_numeric_rejected(self):
        a = ScheduleAssistent(mode="watering", valves=_valves(1))
        a.start(); a.advance("Rasen"); a.advance(14); a.advance(30); a.advance(10)
        a.advance("custom")
        r = a.advance("13,5")   # Komma ist keine ganze Zahl
        self.assertIsInstance(r, Reject)
        self.assertEqual(a.step, "volume_custom")


class TestScheduleAssistentModeGuard(unittest.TestCase):

    def test_nebel_mode_not_yet_supported_fails_loudly(self):
        """Review-Befund: Nebel-Zweig ist noch nicht migriert — soll laut scheitern, nicht
        still in den Wässern-Pfad fallen."""
        a = ScheduleAssistent(mode="nebel", valves=_valves(1))
        a.start(); a.advance("Kühlung"); a.advance(14)
        with self.assertRaises(NotImplementedError):
            a.advance(30)


class TestScheduleAssistentDays(unittest.TestCase):

    def _at_days(self):
        a = ScheduleAssistent(mode="watering", valves=_valves(1))
        a.start(); a.advance("Rasen"); a.advance(14); a.advance(30); a.advance(10); a.advance(25)
        return a

    def test_toggle_day_on_and_off(self):
        a = self._at_days()
        a.advance("Mon"); self.assertIn("Mon", a.data["days"])
        a.advance("Mon"); self.assertNotIn("Mon", a.data["days"])

    def test_everyday_clears_individual_days(self):
        a = self._at_days()
        a.advance("Mon"); a.advance("Wed")
        a.advance("everyday")
        self.assertEqual(a.data["days"], ["everyday"])

    def test_individual_day_clears_everyday(self):
        a = self._at_days()
        a.advance("everyday")
        a.advance("Fri")
        self.assertEqual(a.data["days"], ["Fri"])


if __name__ == "__main__":
    unittest.main()
