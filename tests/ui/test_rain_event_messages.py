"""Meldungen zum Regenereignis (ADR 0043): Start ohne Menge, Ende mit Gesamtmenge."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import daemon.ui.telegram_ui as ui
from daemon.core.sensor_events import RainEventEnded, RainEventStarted


class TestRainEventMessages(unittest.TestCase):

    def _sent(self, render, event):
        # Reiner Render (Registry-Refactor 3sr): kein Telegram-Mock mehr nötig.
        return render(event)

    def test_start_message_has_no_amount(self):
        msg = self._sent(ui._render_rain_event_started, RainEventStarted())

        self.assertIn("Regen erkannt", msg)
        self.assertNotIn("mm", msg)          # die 0,5 mm des ersten Kipps sagen nichts aus

    def test_end_message_reports_total_and_duration(self):
        msg = self._sent(ui._render_rain_event_ended, RainEventEnded(4.5, 130))

        self.assertIn("Regen vorbei", msg)
        self.assertIn("4.5 mm", msg)
        self.assertIn("2 h 10 Min", msg)

    def test_end_message_short_duration_in_minutes(self):
        msg = self._sent(ui._render_rain_event_ended, RainEventEnded(1.0, 20))

        self.assertIn("1.0 mm", msg)
        self.assertIn("20 Min", msg)
        self.assertNotIn(" h ", msg)

    def test_end_message_single_tick_omits_duration(self):
        msg = self._sent(ui._render_rain_event_ended, RainEventEnded(0.5, 0))

        self.assertIn("0.5 mm", msg)
        self.assertNotIn("Min", msg)         # ohne Dauer bei nur einem Kipp


if __name__ == "__main__":
    unittest.main()
