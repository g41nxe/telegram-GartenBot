"""Update-Meldungen (ADR 0044): live / fehlgeschlagen."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import daemon.ui.telegram_ui as ui
from daemon.core.system_events import SoftwareUpdateActivated, SoftwareUpdateRolledBack


class TestUpdateMessages(unittest.TestCase):

    def _sent(self, fn, event):
        with patch.object(ui, "telegram_client") as tc:
            fn(event)
            return tc.broadcast_notification.call_args[0][0]

    def test_activated_message(self):
        msg = self._sent(ui._on_software_update_activated, SoftwareUpdateActivated("v1.17.0"))

        self.assertIn("Update aktiv", msg)
        self.assertIn("v1.17.0", msg)

    def test_rolled_back_message(self):
        msg = self._sent(
            ui._on_software_update_rolled_back, SoftwareUpdateRolledBack("v1.17.0", "v1.16.1")
        )

        self.assertIn("fehlgeschlagen", msg)
        self.assertIn("v1.17.0", msg)   # das gescheiterte Ziel
        self.assertIn("v1.16.1", msg)   # laeuft weiter auf

    def test_subscribe_wires_both_update_events(self):
        """Rule 6: subscribe_event_handlers() verdrahtet beide Update-Ereignisse."""
        import daemon.adapters.mqtt_client as mc

        ui.subscribe_event_handlers()
        with patch.object(ui, "telegram_client") as tc:
            mc._global_bus.publish(SoftwareUpdateActivated("v9.9.9"))
            mc._global_bus.publish(SoftwareUpdateRolledBack("v9.9.9", "v1.0.0"))

        sent = " ".join(c.args[0] for c in tc.broadcast_notification.call_args_list)
        self.assertIn("Update aktiv", sent)
        self.assertIn("fehlgeschlagen", sent)


if __name__ == "__main__":
    unittest.main()
