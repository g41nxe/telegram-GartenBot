"""Update-Benachrichtigungs-Entscheidung (ADR 0044) — rein, ohne I/O."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.version_announce import decide
from daemon.core.system_events import SoftwareUpdateActivated, SoftwareUpdateRolledBack


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


if __name__ == "__main__":
    unittest.main()
