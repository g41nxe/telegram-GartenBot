"""Update-Benachrichtigungs-Entscheidung (ADR 0044) — rein, ohne I/O."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.version_announce import decide
from daemon.core.system_events import (
    SoftwareUpdateActivated, SoftwareUpdateRolledBack, SoftwareUpdateFailed,
)


class TestVersionAnnounce(unittest.TestCase):

    def test_new_version_announces_activation(self):
        event, new_announced = decide(current="v1.17.0", announced="v1.16.1", rollback_target=None)

        self.assertIsInstance(event, SoftwareUpdateActivated)
        self.assertEqual(event.version, "v1.17.0")
        self.assertEqual(new_announced, "v1.17.0")

    def test_same_version_no_announcement(self):
        event, new_announced = decide(current="v1.17.0", announced="v1.17.0", rollback_target=None)

        self.assertIsNone(event)
        self.assertEqual(new_announced, "v1.17.0")   # unverändert

    def test_rollback_marker_announces_failure(self):
        # Rollback: laeuft wieder auf der alten Version (== announced), aber Marker liegt vor
        event, new_announced = decide(current="v1.16.1", announced="v1.16.1", rollback_target="v1.17.0")

        self.assertIsInstance(event, SoftwareUpdateRolledBack)
        self.assertEqual(event.target_version, "v1.17.0")
        self.assertEqual(event.current_version, "v1.16.1")
        self.assertEqual(new_announced, "v1.16.1")

    def test_unknown_version_is_skipped(self):
        event, new_announced = decide(current="unbekannt", announced="v1.16.1", rollback_target=None)

        self.assertIsNone(event)
        self.assertEqual(new_announced, "v1.16.1")   # nicht fortschreiben

    def test_first_start_announces_once(self):
        event, new_announced = decide(current="v1.17.0", announced="", rollback_target=None)

        self.assertIsInstance(event, SoftwareUpdateActivated)
        self.assertEqual(new_announced, "v1.17.0")

    # --- Ticket eor: Abbruch vor dem Rollback (Versuchs-Marker) ------------------------------

    def test_attempt_marker_but_old_version_running_announces_failure(self):
        # update.sh starb still: Versuchs-Marker (v1.18.0) liegt vor, aber es läuft weiter die
        # alte Version -> Abbruch melden, ohne die gemeldete Version fortzuschreiben.
        event, new_announced = decide(current="v1.17.0", announced="v1.17.0",
                                      rollback_target=None, attempt_target="v1.18.0")

        self.assertIsInstance(event, SoftwareUpdateFailed)
        self.assertEqual(event.target_version, "v1.18.0")
        self.assertEqual(event.current_version, "v1.17.0")
        self.assertEqual(new_announced, "v1.17.0")

    def test_attempt_marker_with_target_running_is_success(self):
        # Race: Daemon startet während der Health-Check-Wartephase, Marker noch da, ABER die
        # Zielversion läuft bereits -> Erfolg (kein Fehlalarm).
        event, new_announced = decide(current="v1.18.0", announced="v1.17.0",
                                      rollback_target=None, attempt_target="v1.18.0")

        self.assertIsInstance(event, SoftwareUpdateActivated)
        self.assertEqual(event.version, "v1.18.0")
        self.assertEqual(new_announced, "v1.18.0")

    def test_rollback_marker_wins_over_attempt_marker(self):
        # Sauberer Rollback hat Vorrang: „fehlgeschlagen + zurückgerollt", nicht „Abbruch".
        event, _ = decide(current="v1.17.0", announced="v1.17.0",
                          rollback_target="v1.18.0", attempt_target="v1.18.0")

        self.assertIsInstance(event, SoftwareUpdateRolledBack)

    def test_attempt_marker_unknown_version_is_skipped(self):
        # Simulation ohne VERSION-Datei: current == Marker-Ziel wäre falsch; current != Ziel,
        # aber „unbekannt" darf keinen Fehlalarm auslösen.
        event, new_announced = decide(current="unbekannt", announced="v1.17.0",
                                      rollback_target=None, attempt_target="v1.18.0")

        self.assertIsNone(event)
        self.assertEqual(new_announced, "v1.17.0")


if __name__ == "__main__":
    unittest.main()
