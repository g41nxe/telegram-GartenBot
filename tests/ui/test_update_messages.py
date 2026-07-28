"""Update-Meldungen (ADR 0044): live / fehlgeschlagen."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import daemon.ui.telegram_ui as ui
from daemon.core.system_events import (
    SoftwareUpdateActivated, SoftwareUpdateRolledBack, SoftwareUpdateFailed,
)


class TestUpdateMessages(unittest.TestCase):

    def _sent(self, render, event):
        # Reiner Render (Registry-Refactor 3sr): kein Telegram-Mock mehr nötig.
        return render(event)

    def test_activated_message(self):
        msg = self._sent(ui._render_software_update_activated, SoftwareUpdateActivated("v1.17.0"))

        self.assertIn("Update aktiv", msg)
        self.assertIn("v1.17.0", msg)

    def test_rolled_back_message(self):
        msg = self._sent(
            ui._render_software_update_rolled_back, SoftwareUpdateRolledBack("v1.17.0", "v1.16.1")
        )

        self.assertIn("fehlgeschlagen", msg)
        self.assertIn("v1.17.0", msg)   # das gescheiterte Ziel
        self.assertIn("v1.16.1", msg)   # laeuft weiter auf

    def test_failed_message(self):
        # Ticket eor: Abbruch vor dem Rollback — Warnung mit Ziel + laufender Version + Prüf-Bitte.
        msg = self._sent(
            ui._render_software_update_failed, SoftwareUpdateFailed("v1.18.0", "v1.17.0")
        )

        self.assertIn("unterbrochen", msg)
        self.assertIn("v1.18.0", msg)   # das gescheiterte Ziel
        self.assertIn("v1.17.0", msg)   # laeuft weiter auf
        self.assertIn("/status", msg)   # Prüf-Bitte

    def test_subscribe_wires_all_update_events(self):
        """Rule 6: subscribe_event_handlers() verdrahtet alle drei Update-Ereignisse."""
        import daemon.adapters.mqtt_client as mc

        ui.subscribe_event_handlers()
        with patch.object(ui, "telegram_client") as tc:
            mc._global_bus.publish(SoftwareUpdateActivated("v9.9.9"))
            mc._global_bus.publish(SoftwareUpdateRolledBack("v9.9.9", "v1.0.0"))
            mc._global_bus.publish(SoftwareUpdateFailed("v9.9.9", "v1.0.0"))

        sent = " ".join(c.args[0] for c in tc.broadcast_notification.call_args_list)
        self.assertIn("Update aktiv", sent)
        self.assertIn("fehlgeschlagen", sent)
        self.assertIn("unterbrochen", sent)


if __name__ == "__main__":
    unittest.main()
