"""Ende-zu-Ende-Regression der Ventil-Kopplung (Ticket cy1).

Treibt „🔧 Ventil koppeln" (Name → start_pairing) durch die echten Dispatcher.
Paritäts-Anker für die PairingNameAssistent-Migration: grün VOR und NACH.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.telegram_ui import _process_message, _process_callback_query, wizard_states
import daemon.adapters.valve_pairing  # noqa: F401


class TestPairingFlow(unittest.TestCase):
    CHAT = 600

    def setUp(self):
        wizard_states.clear()
        self.tc = patch("daemon.ui.telegram_ui.telegram_client").start()
        self.db = patch("daemon.ui.telegram_ui.database").start()
        self.start_pairing = patch("daemon.adapters.valve_pairing.start_pairing").start()
        self.addCleanup(patch.stopall)
        self.tc.send_message_id.return_value = 500

    def tearDown(self):
        wizard_states.clear()

    def _cb(self, data, msg_id=500):
        return {"id": "cb1", "data": data, "message": {"chat": {"id": self.CHAT}, "message_id": msg_id}}

    def _msg(self, text):
        return {"chat": {"id": self.CHAT}, "text": text, "message_id": 1}

    def test_name_starts_pairing(self):
        _process_callback_query(self._cb("setup_confirm", msg_id=10))
        _process_message(self._msg("Beet-Ventil"))
        self.start_pairing.assert_called_once()
        self.assertIn("Beet-Ventil", self.start_pairing.call_args.args)
        self.assertNotIn(self.CHAT, wizard_states)

    def test_empty_name_stays(self):
        _process_callback_query(self._cb("setup_confirm", msg_id=10))
        _process_message(self._msg("   "))
        self.assertIn(self.CHAT, wizard_states)
        self.start_pairing.assert_not_called()


if __name__ == "__main__":
    unittest.main()
