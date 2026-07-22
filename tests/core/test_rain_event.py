"""Regenereignis-Zustandslogik (ADR 0043) — rein, ohne I/O."""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.rain_event import RainEventState, advance
from daemon.core.sensor_events import RainEventEnded, RainEventStarted

T0 = datetime(2026, 7, 6, 11, 40, 0)
GRACE = 45


class TestRainEvent(unittest.TestCase):

    def test_first_tick_starts_event(self):
        state, events = advance(RainEventState(), 0.5, T0, grace_minutes=GRACE)

        self.assertTrue(state.active)
        self.assertEqual(state.start, T0)
        self.assertEqual(state.total_mm, 0.5)
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], RainEventStarted)

    def test_tick_during_event_only_accumulates(self):
        state, _ = advance(RainEventState(), 0.5, T0, GRACE)

        state, events = advance(state, 0.5, T0 + timedelta(minutes=20), GRACE)

        self.assertEqual(events, [])                       # kein zweites "gestartet"
        self.assertEqual(state.total_mm, 1.0)
        self.assertEqual(state.last_tick, T0 + timedelta(minutes=20))
        self.assertEqual(state.start, T0)                  # Startzeit bleibt

    def test_gap_shorter_than_grace_does_not_end_event(self):
        state, _ = advance(RainEventState(), 0.5, T0, GRACE)

        state, events = advance(state, 0.0, T0 + timedelta(minutes=44), GRACE)

        self.assertEqual(events, [])
        self.assertTrue(state.active)

    def test_gap_reaching_grace_ends_event_with_total_and_duration(self):
        state, _ = advance(RainEventState(), 0.5, T0, GRACE)
        state, _ = advance(state, 0.5, T0 + timedelta(minutes=20), GRACE)   # letzter Kipp

        state, events = advance(state, 0.0, T0 + timedelta(minutes=65), GRACE)  # 45 Min danach

        self.assertFalse(state.active)
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], RainEventEnded)
        self.assertEqual(events[0].total_mm, 1.0)
        self.assertEqual(events[0].duration_minutes, 20)   # letzter Kipp - erster Kipp

    def test_real_drizzle_afternoon_collapses_to_two_events(self):
        """Echte Kipp-Zeiten vom 06.07.2026 — heute neun Paare, künftig zwei."""
        day = datetime(2026, 7, 6)
        ticks = ["11:40", "12:09", "12:51", "13:13", "13:37", "14:08", "14:23", "15:44", "15:59"]
        series = [(day.replace(hour=int(t[:2]), minute=int(t[3:])), 0.5) for t in ticks]
        # dazwischen die regulären Meldungen ohne Kipp (~13 Min Takt bis zum Abend)
        t = day.replace(hour=11, minute=30)
        while t <= day.replace(hour=18, minute=0):
            series.append((t, 0.0))
            t += timedelta(minutes=13)
        series.sort(key=lambda x: x[0])

        state, started, ended = RainEventState(), 0, 0
        for ts, mm in series:
            state, events = advance(state, mm, ts, GRACE)
            started += sum(isinstance(e, RainEventStarted) for e in events)
            ended += sum(isinstance(e, RainEventEnded) for e in events)

        self.assertEqual((started, ended), (2, 2))   # statt 9 Paaren


if __name__ == "__main__":
    unittest.main()
