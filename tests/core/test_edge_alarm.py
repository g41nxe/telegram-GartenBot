"""Reine Flanken-Auswertung für zustandsbehaftete Alarme (Ticket 6r2).

`evaluate` bekommt den aktuellen Störungszustand (`faulted`) und den zuletzt gemeldeten
Zustand (`reported`) herein und liefert den neuen gemeldeten Zustand plus das auszulösende
Ereignis — aber NUR bei einem Übergang (steigende/fallende Flanke). Kein I/O; die
Ereignis-Fabriken werden als Callables injiziert (ADR 0017), damit der Kern die konkreten
Ereignistypen nicht kennt.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.edge_alarm import evaluate

_RAISE = object()
_CLEAR = object()


class TestEdgeAlarm(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def _on_raise(self):
        self.calls.append("raise")
        return _RAISE

    def _on_clear(self):
        self.calls.append("clear")
        return _CLEAR

    def _run(self, faulted, reported):
        return evaluate(faulted, reported, self._on_raise, self._on_clear)

    def test_rising_edge_raises(self):
        # gestört, aber noch nicht gemeldet -> melden
        new_reported, event = self._run(faulted=True, reported=False)
        self.assertTrue(new_reported)
        self.assertIs(event, _RAISE)
        self.assertEqual(self.calls, ["raise"])

    def test_falling_edge_clears(self):
        # nicht mehr gestört, war aber gemeldet -> entwarnen
        new_reported, event = self._run(faulted=False, reported=True)
        self.assertFalse(new_reported)
        self.assertIs(event, _CLEAR)
        self.assertEqual(self.calls, ["clear"])

    def test_stable_faulted_is_silent(self):
        # weiterhin gestört und schon gemeldet -> kein Ereignis, kein Fabrik-Aufruf
        new_reported, event = self._run(faulted=True, reported=True)
        self.assertTrue(new_reported)
        self.assertIsNone(event)
        self.assertEqual(self.calls, [])

    def test_stable_ok_is_silent(self):
        # alles in Ordnung und war nicht gemeldet -> still
        new_reported, event = self._run(faulted=False, reported=False)
        self.assertFalse(new_reported)
        self.assertIsNone(event)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
