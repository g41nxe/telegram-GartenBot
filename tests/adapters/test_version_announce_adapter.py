"""Start-Adapter der Update-Benachrichtigung (ADR 0044): I/O + Publikation."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.adapters import version_announce_adapter as vaa
from daemon.core.system_events import SoftwareUpdateActivated, SoftwareUpdateRolledBack

_ANNOUNCED = "announced_version"


class TestVersionAnnounceAdapter(unittest.TestCase):

    def setUp(self):
        self.store = {}
        for target in ("database", "config"):
            p = patch.object(vaa, target)
            m = p.start()
            self.addCleanup(p.stop)
            setattr(self, target, m)
        self.database.get_metadata.side_effect = lambda k, d=None: self.store.get(k, d)
        self.database.set_metadata.side_effect = lambda k, v: self.store.__setitem__(k, v)
        self.config.read_version.return_value = "v1.17.0"
        # Marker standardmäßig nicht vorhanden
        self._rollback = None
        rp = patch.object(vaa, "_read_rollback_marker", side_effect=lambda: self._rollback)
        rp.start(); self.addCleanup(rp.stop)
        cp = patch.object(vaa, "_clear_rollback_marker")
        self.clear_marker = cp.start(); self.addCleanup(cp.stop)

    def _published(self, bus, cls):
        return [c.args[0] for c in bus.publish.call_args_list if isinstance(c.args[0], cls)]

    def test_new_version_publishes_activation_and_persists(self):
        self.store[_ANNOUNCED] = "v1.16.1"
        bus = MagicMock()

        vaa.announce_on_start(bus)

        self.assertEqual(len(self._published(bus, SoftwareUpdateActivated)), 1)
        self.assertEqual(self.store[_ANNOUNCED], "v1.17.0")   # fortgeschrieben

    def test_plain_restart_is_silent(self):
        self.store[_ANNOUNCED] = "v1.17.0"    # gleiche Version, kein Marker
        bus = MagicMock()

        vaa.announce_on_start(bus)

        bus.publish.assert_not_called()

    def test_rollback_marker_publishes_failure_and_clears_marker(self):
        self.store[_ANNOUNCED] = "v1.16.1"
        self.config.read_version.return_value = "v1.16.1"    # zurück auf alt
        self._rollback = "v1.17.0"
        bus = MagicMock()

        vaa.announce_on_start(bus)

        failed = self._published(bus, SoftwareUpdateRolledBack)
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].target_version, "v1.17.0")
        self.clear_marker.assert_called_once()

    def test_state_written_before_publish(self):
        """Höchstens einmal: announced_version steht schon fest, wenn publiziert wird."""
        self.store[_ANNOUNCED] = "v1.16.1"
        bus = MagicMock()
        seen = {}
        bus.publish.side_effect = lambda e: seen.update(at_publish=self.store.get(_ANNOUNCED))

        vaa.announce_on_start(bus)

        self.assertEqual(seen["at_publish"], "v1.17.0")   # vor der Publikation fortgeschrieben


class TestRollbackMarkerIO(unittest.TestCase):
    """Deckt die echten Datei-Helfer ab (in den Haupt-Tests weggepatcht)."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp()) / "garden-ota-rollback"
        p = patch.object(vaa, "_ROLLBACK_MARKER", self.tmp)
        p.start(); self.addCleanup(p.stop)

    def test_read_absent_returns_none(self):
        self.assertIsNone(vaa._read_rollback_marker())

    def test_read_returns_stripped_content(self):
        self.tmp.write_text("  v1.17.0\n")
        self.assertEqual(vaa._read_rollback_marker(), "v1.17.0")

    def test_read_empty_returns_none(self):
        self.tmp.write_text("   \n")
        self.assertIsNone(vaa._read_rollback_marker())

    def test_clear_removes_file(self):
        self.tmp.write_text("v1.17.0")
        vaa._clear_rollback_marker()
        self.assertFalse(self.tmp.exists())

    def test_clear_is_idempotent(self):
        vaa._clear_rollback_marker()   # nicht vorhanden -> kein Fehler
        self.assertFalse(self.tmp.exists())


if __name__ == "__main__":
    unittest.main()
