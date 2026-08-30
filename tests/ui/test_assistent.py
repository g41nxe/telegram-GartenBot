"""Ticket cy1: reine Zustandsmaschine des Assistenten (Zeitplan-Pilot).

Der Assistent besitzt Zustand (step/data/prompt_msg_id) und die Übergänge; advance(value)
liefert eine reine Absicht (Prompt / Reject / Done) — kein I/O, keine Telegram-Aufrufe.
Die lebende-Prompt-Invariante (ADR 0039) und das Rendering leben im späteren Live-Adapter.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.assistent import (
    ScheduleAssistent, GussAssistent, InstantMistAssistent,
    CameraPairAssistent, CameraSettingsAssistent, PairingNameAssistent,
    DeleteConfirmAssistent, EditAssistent, Prompt, Reject, Done,
)


_SCHEDULE = {"id": 5, "name": "Morgen", "time": "08:30", "days": "Mon,Wed",
             "duration_minutes": 10, "target_volume_liters": 20, "valve_id": 3, "is_active": 1}


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


class TestScheduleAssistentNebel(unittest.TestCase):
    """Nebel-Pfad: name → hour → minute → end_hour → end_minute → nebel_on → nebel_pause
    → (valve) → days → confirm. Teilt Präfix und Suffix mit dem Wässern-Pfad."""

    def _run_to_days(self, valves):
        a = ScheduleAssistent(mode="nebel", valves=valves)
        a.start()
        a.advance("Kühlung"); a.advance(8); a.advance(0)
        self.assertEqual(a.step, "end_hour")
        a.advance(20)
        self.assertEqual(a.data["end_hour"], 20)
        self.assertEqual(a.step, "end_minute")
        a.advance(30)
        self.assertEqual(a.data["end_minute"], 30)
        self.assertEqual(a.step, "nebel_on")
        a.advance(10)
        self.assertEqual(a.data["on_seconds"], 10)
        self.assertEqual(a.step, "nebel_pause")
        return a

    def test_single_valve_skips_valve_step(self):
        a = self._run_to_days(_valves(1))
        a.advance(5)                                 # pause_minutes
        self.assertEqual(a.data["pause_minutes"], 5)
        self.assertEqual(a.data["valve_id"], 1)      # auto-zugewiesen
        self.assertEqual(a.step, "days")

    def test_multi_valve_asks_valve(self):
        a = self._run_to_days(_valves(3))
        p = a.advance(5)
        self.assertEqual(p.view, "valve")
        self.assertEqual(a.step, "valve")
        a.advance(2)
        self.assertEqual(a.data["valve_id"], 2)
        self.assertEqual(a.step, "days")

    def test_full_flow_terminates_with_done(self):
        a = self._run_to_days(_valves(1))
        a.advance(5)
        a.advance("Mon")
        a.advance("save")
        self.assertEqual(a.step, "confirm")
        result = a.advance("confirm")
        self.assertIsInstance(result, Done)
        self.assertEqual(result.data["mode"], "nebel")
        self.assertEqual(result.data["name"], "Kühlung")
        self.assertEqual(result.data["hour"], 8)
        self.assertEqual(result.data["minute"], 0)
        self.assertEqual(result.data["end_hour"], 20)
        self.assertEqual(result.data["end_minute"], 30)
        self.assertEqual(result.data["on_seconds"], 10)
        self.assertEqual(result.data["pause_minutes"], 5)
        self.assertEqual(result.data["days"], ["Mon"])
        self.assertEqual(result.data["valve_id"], 1)

    def test_end_before_start_returns_to_end_hour(self):
        a = ScheduleAssistent(mode="nebel", valves=_valves(1))
        a.start(); a.advance("Kühlung"); a.advance(12); a.advance(0)
        a.advance(11)                                # end_hour 11 < start 12
        p = a.advance(30)                            # 11:30 <= 12:00 ⇒ zurück
        self.assertIsInstance(p, Prompt)
        self.assertEqual(a.step, "end_hour")
        self.assertNotIn("end_minute", a.data)       # nicht übernommen

    def test_end_equal_start_returns_to_end_hour(self):
        a = ScheduleAssistent(mode="nebel", valves=_valves(1))
        a.start(); a.advance("Kühlung"); a.advance(12); a.advance(0)
        a.advance(12)
        p = a.advance(0)                             # 12:00 == 12:00 ⇒ zurück
        self.assertEqual(a.step, "end_hour")
        self.assertNotIn("end_minute", a.data)


class TestGussAssistent(unittest.TestCase):
    """Sofort-Guss (manueller Start): duration → volume → Done. Das Ventil ist vorgewählt
    und wird als mqtt_name durchgereicht; Done liefert dur/vol/mqtt_name (Aktion im Adapter)."""

    def test_preset_path_terminates_with_done(self):
        a = GussAssistent(mqtt_name="beet_1")
        p = a.start()
        self.assertEqual(p.view, "duration")
        self.assertEqual(a.step, "duration")
        a.advance(10)
        self.assertEqual(a.data["duration"], 10)
        self.assertEqual(a.step, "volume")
        result = a.advance(25)
        self.assertIsInstance(result, Done)
        self.assertEqual(result.data["duration"], 10)
        self.assertEqual(result.data["volume"], 25)
        self.assertEqual(result.data["mqtt_name"], "beet_1")

    def test_custom_duration_path(self):
        a = GussAssistent()
        a.start()
        p = a.advance("custom")
        self.assertEqual(a.step, "duration_custom")
        self.assertEqual(p.view, "duration_custom")
        a.advance(7)
        self.assertEqual(a.data["duration"], 7)
        self.assertEqual(a.step, "volume")

    def test_custom_volume_path(self):
        a = GussAssistent()
        a.start(); a.advance(10)
        a.advance("custom")
        self.assertEqual(a.step, "volume_custom")
        result = a.advance(40)
        self.assertIsInstance(result, Done)
        self.assertEqual(result.data["volume"], 40)

    def test_custom_duration_out_of_range_rejected(self):
        a = GussAssistent()
        a.start(); a.advance("custom")
        self.assertIsInstance(a.advance(99), Reject)   # > 25
        self.assertEqual(a.step, "duration_custom")
        self.assertIsInstance(a.advance(0), Reject)    # < 1
        self.assertEqual(a.step, "duration_custom")

    def test_custom_duration_non_numeric_rejected(self):
        a = GussAssistent()
        a.start(); a.advance("custom")
        self.assertIsInstance(a.advance("abc"), Reject)
        self.assertEqual(a.step, "duration_custom")

    def test_custom_volume_non_positive_rejected(self):
        a = GussAssistent()
        a.start(); a.advance(10); a.advance("custom")
        self.assertIsInstance(a.advance(0), Reject)
        self.assertEqual(a.step, "volume_custom")

    def test_default_mqtt_name(self):
        a = GussAssistent()
        self.assertEqual(a.data["mqtt_name"], "garden_valve")


class TestSofortNebelAssistent(unittest.TestCase):
    """Sofort-Nebel: on → pause → runtime → Done. Ventil vorgewählt (außerhalb data)."""

    def test_full_flow_terminates_with_done(self):
        valve = {"id": 3, "wish_name": "Terrasse", "mqtt_name": "terrace_mist"}
        a = InstantMistAssistent(valve)
        p = a.start()
        self.assertEqual(p.view, "on")
        self.assertEqual(a.step, "on")
        a.advance(30)
        self.assertEqual(a.data["on_seconds"], 30)
        self.assertEqual(a.step, "pause")
        a.advance(5)
        self.assertEqual(a.data["pause_minutes"], 5)
        self.assertEqual(a.step, "runtime")
        result = a.advance(60)
        self.assertIsInstance(result, Done)
        self.assertEqual(result.data["minutes"], 60)
        self.assertEqual(result.data["on_seconds"], 30)
        self.assertEqual(result.data["pause_minutes"], 5)
        self.assertIs(a.valve, valve)


class TestCameraPairAssistent(unittest.TestCase):
    """Kopplung: wish_name → interval → resolution → quality → Done."""

    def test_full_flow_terminates_with_done(self):
        a = CameraPairAssistent()
        p = a.start()
        self.assertEqual(p.view, "wish_name")
        a.advance("Terrasse-Cam")
        self.assertEqual(a.data["wish_name"], "Terrasse-Cam")
        self.assertEqual(a.step, "interval")
        a.advance("15")
        self.assertEqual(a.data["sleep_seconds"], 900)
        self.assertEqual(a.step, "resolution")
        a.advance("XGA")
        self.assertEqual(a.data["resolution"], "XGA")
        self.assertEqual(a.step, "quality")
        result = a.advance("high")
        self.assertIsInstance(result, Done)
        self.assertEqual(result.data["quality"], "high")
        self.assertEqual(result.data["sleep_seconds"], 900)

    def test_invalid_name_rejected(self):
        a = CameraPairAssistent()
        a.start()
        self.assertIsInstance(a.advance("ungültig name!"), Reject)   # Leerzeichen/Sonderzeichen
        self.assertEqual(a.step, "wish_name")
        self.assertIsInstance(a.advance(""), Reject)
        self.assertEqual(a.step, "wish_name")

    def test_interval_out_of_range_rejected(self):
        a = CameraPairAssistent()
        a.start(); a.advance("Cam")
        self.assertIsInstance(a.advance("0"), Reject)
        self.assertIsInstance(a.advance("1441"), Reject)
        self.assertIsInstance(a.advance("abc"), Reject)
        self.assertEqual(a.step, "interval")


class TestCameraSettingsAssistent(unittest.TestCase):

    def test_interval_update_done(self):
        a = CameraSettingsAssistent(mac="AA:BB", wish_name="Cam")
        p = a.start()
        self.assertEqual(p.view, "interval")
        result = a.advance("30")
        self.assertIsInstance(result, Done)
        self.assertEqual(result.data["mac"], "AA:BB")
        self.assertEqual(result.data["sleep_seconds"], 1800)

    def test_invalid_interval_rejected(self):
        a = CameraSettingsAssistent(mac="AA:BB", wish_name="Cam")
        a.start()
        self.assertIsInstance(a.advance("nope"), Reject)


class TestPairingNameAssistent(unittest.TestCase):

    def test_name_terminates_with_done(self):
        a = PairingNameAssistent()
        p = a.start()
        self.assertEqual(p.view, "wish_name")
        result = a.advance("Beet-Ventil")
        self.assertIsInstance(result, Done)
        self.assertEqual(result.data["wish_name"], "Beet-Ventil")

    def test_empty_name_rejected(self):
        a = PairingNameAssistent()
        a.start()
        self.assertIsInstance(a.advance("   "), Reject)
        self.assertEqual(a.step, "wish_name")


class TestDeleteConfirmAssistent(unittest.TestCase):

    def test_confirm_yields_done_confirmed(self):
        a = DeleteConfirmAssistent(schedule_id=5, name="Morgen")
        self.assertEqual(a.start().view, "confirm")
        result = a.advance("confirm")
        self.assertIsInstance(result, Done)
        self.assertTrue(result.data["confirmed"])
        self.assertEqual(result.data["schedule_id"], 5)

    def test_cancel_yields_done_not_confirmed(self):
        a = DeleteConfirmAssistent(schedule_id=5, name="Morgen")
        a.start()
        result = a.advance("cancel")
        self.assertIsInstance(result, Done)
        self.assertFalse(result.data["confirmed"])


class TestEditAssistent(unittest.TestCase):
    """Nabe-Speiche-Editor: menu → Feld → zurück ins menu; Batch-Speichern bei „done"."""

    def _fresh(self):
        a = EditAssistent(dict(_SCHEDULE), valves=[{"id": 3, "wish_name": "Beet"}])
        a.start()
        return a

    def test_prefilled_from_schedule(self):
        a = self._fresh()
        self.assertEqual(a.step, "menu")
        self.assertEqual(a.data["name"], "Morgen")
        self.assertEqual(a.data["hour"], 8)
        self.assertEqual(a.data["minute"], 30)
        self.assertEqual(a.data["days"], ["Mon", "Wed"])
        self.assertEqual(a.data["duration"], 10)
        self.assertEqual(a.data["volume"], 20)
        self.assertEqual(a.data["valve_id"], 3)

    def test_done_without_change_returns_original(self):
        a = self._fresh()
        result = a.advance("done")
        self.assertIsInstance(result, Done)
        self.assertEqual(result.data["name"], "Morgen")
        self.assertEqual(result.data["hour"], 8)

    def test_edit_time_returns_to_menu_and_batches(self):
        a = self._fresh()
        a.advance("time")
        self.assertEqual(a.step, "time_hour")
        a.advance(14)
        self.assertEqual(a.step, "time_min")
        p = a.advance(45)
        self.assertEqual(p.view, "menu")            # zurück in der Nabe
        self.assertEqual(a.data["hour"], 14)
        self.assertEqual(a.data["minute"], 45)
        # noch NICHT gespeichert — erst done liefert Done
        result = a.advance("done")
        self.assertEqual(result.data["hour"], 14)
        self.assertEqual(result.data["minute"], 45)

    def test_edit_name_validation(self):
        a = self._fresh()
        a.advance("name")
        self.assertEqual(a.step, "name")
        self.assertIsInstance(a.advance("   "), Reject)
        self.assertIsInstance(a.advance("/slash"), Reject)
        self.assertIsInstance(a.advance("x" * 51), Reject)
        self.assertEqual(a.step, "name")            # kein Wechsel bei Fehler
        a.advance("Abend")
        self.assertEqual(a.step, "menu")
        self.assertEqual(a.data["name"], "Abend")

    def test_edit_days_toggle_and_save(self):
        a = self._fresh()
        a.advance("days")
        self.assertEqual(a.data["edit_days"], ["Mon", "Wed"])
        a.advance("Mon")                            # abwählen
        self.assertNotIn("Mon", a.data["edit_days"])
        a.advance("Fri")                            # hinzufügen
        p = a.advance("save")
        self.assertEqual(p.view, "menu")
        self.assertEqual(a.data["days"], ["Wed", "Fri"])

    def test_edit_days_empty_rejected(self):
        a = self._fresh()
        a.advance("days")
        a.advance("Mon"); a.advance("Wed")          # beide abwählen
        self.assertIsInstance(a.advance("save"), Reject)
        self.assertEqual(a.step, "days")

    def test_edit_multiple_fields_then_done(self):
        a = self._fresh()
        a.advance("duration"); a.advance(20)
        a.advance("volume"); a.advance(0)
        a.advance("valve"); a.advance(3)
        result = a.advance("done")
        self.assertEqual(result.data["duration"], 20)
        self.assertEqual(result.data["volume"], 0)
        self.assertEqual(result.data["valve_id"], 3)

    def test_menu_ignores_typed_text(self):
        a = self._fresh()
        self.assertFalse(a.wants_text())            # Menü erwartet keine Tastatur-Eingabe
        a.advance("name")
        self.assertTrue(a.wants_text())             # Namensschritt schon


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
