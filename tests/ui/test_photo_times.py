"""Tests für /aufnahmen Wizard und TimedPhotoCaptured-Handler (Feature 0030)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.telegram_ui import _process_message, _process_callback_query


def _msg(text, chat_id=100):
    return {"chat": {"id": chat_id}, "text": text}


def _cb(data, chat_id=100, msg_id=1):
    return {"id": "cb1", "data": data, "message": {"chat": {"id": chat_id}, "message_id": msg_id}}


def _markup(call_args):
    return call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs.get("reply_markup")


def _cb_data(markup):
    if markup is None:
        return []
    return [b["callback_data"] for row in markup["inline_keyboard"] for b in row]


# ===========================================================================
# /aufnahmen — Listenansicht
# ===========================================================================

class TestCameraTimesCommand(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_keine_eintraege_zeigt_hinweis_und_add_button(self, mock_db, mock_tc):
        """Keine gespeicherten Foto-Uhrzeiten → Hinweis + 'Uhrzeit hinzufügen'-Button."""
        mock_db.get_photo_times.return_value = []
        _process_callback_query(_cb("kamera_fotozeiten"))

        mock_tc.send_message.assert_called_once()
        text = mock_tc.send_message.call_args.args[1]
        self.assertIn("keine", text.lower())
        markup = _markup(mock_tc.send_message.call_args)
        self.assertIsNotNone(markup)
        cb_data = _cb_data(markup)
        self.assertTrue(any("phtadd" in d for d in cb_data), f"Kein Add-Button in {cb_data}")

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_mit_eintraegen_zeigt_liste_und_loeschen(self, mock_db, mock_tc):
        """Vorhandene Uhrzeiten werden aufgelistet, je Eintrag ein Löschen-Button."""
        mock_db.get_photo_times.return_value = [
            {"id": 1, "time": "08:00"},
            {"id": 2, "time": "18:00"},
        ]
        _process_callback_query(_cb("kamera_fotozeiten"))

        mock_tc.send_message.assert_called_once()
        text = mock_tc.send_message.call_args.args[1]
        self.assertIn("08:00", text)
        self.assertIn("18:00", text)
        cb_data = _cb_data(_markup(mock_tc.send_message.call_args))
        self.assertTrue(any("phtime_del_ask_1" in d for d in cb_data))
        self.assertTrue(any("phtime_del_ask_2" in d for d in cb_data))


# ===========================================================================
# Wizard: Uhrzeit hinzufügen
# ===========================================================================

class TestPhotoTimeWizard(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_add_button_zeigt_stunden_keyboard(self, mock_db, mock_tc):
        """Klick auf 'Uhrzeit hinzufügen' → Stunden-Auswahl-Keyboard."""
        mock_db.get_photo_times.return_value = []
        _process_callback_query(_cb("phtadd_start"))

        mock_tc.send_message.assert_called_once()
        markup = _markup(mock_tc.send_message.call_args)
        self.assertIsNotNone(markup)
        cb_data = _cb_data(markup)
        self.assertTrue(any("phtadd_h_" in d for d in cb_data))

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_stunde_gewaehlt_zeigt_minuten_keyboard(self, mock_db, mock_tc):
        """Stunden-Auswahl → Minuten-Keyboard wird angezeigt."""
        _process_callback_query(_cb("phtadd_h_8"))

        mock_tc.send_message.assert_called_once()
        markup = _markup(mock_tc.send_message.call_args)
        cb_data = _cb_data(markup)
        self.assertTrue(any("phtadd_m_" in d for d in cb_data))

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_minute_gewaehlt_speichert_und_bestaetigt(self, mock_db, mock_tc):
        """Minuten-Auswahl nach Stunden-Auswahl → Uhrzeit gespeichert + Bestätigung."""
        mock_db.add_photo_time.return_value = True
        # Stunde setzen
        _process_callback_query(_cb("phtadd_h_8", chat_id=200))
        mock_tc.reset_mock()
        # Minute wählen
        _process_callback_query(_cb("phtadd_m_30", chat_id=200))

        mock_db.add_photo_time.assert_called_once_with("08:30")
        mock_tc.send_message.assert_called_once()
        text = mock_tc.send_message.call_args.args[1]
        self.assertIn("08:30", text)


# ===========================================================================
# Löschen
# ===========================================================================

class TestPhotoTimeDelete(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_del_ask_zeigt_rueckfrage(self, mock_db, mock_tc):
        """'Löschen'-Button → Rückfrage-Nachricht mit Bestätigungs-Callback."""
        mock_db.get_photo_times.return_value = [{"id": 5, "time": "08:00"}]
        _process_callback_query(_cb("phtime_del_ask_5"))

        mock_tc.send_message.assert_called_once()
        cb_data = _cb_data(_markup(mock_tc.send_message.call_args))
        self.assertTrue(any("phtime_del_confirm_5" in d for d in cb_data))

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.database")
    def test_del_confirm_loescht_und_bestaetigt(self, mock_db, mock_tc):
        """Löschen-Bestätigung → delete_photo_time aufgerufen + Erfolgsmeldung."""
        mock_db.delete_photo_time.return_value = True
        mock_db.get_photo_times.return_value = []
        _process_callback_query(_cb("phtime_del_confirm_5"))

        mock_db.delete_photo_time.assert_called_once_with(5)
        mock_tc.send_message.assert_called()


# ===========================================================================
# _on_timed_photo_captured
# ===========================================================================

class TestTimedPhotoCapturedHandler(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_sendet_foto_mit_beschriftung(self, mock_tc):
        """TimedPhotoCaptured → broadcast_photo mit korrekter Beschriftung."""
        from daemon.ui import telegram_ui
        from daemon.core.camera_events import TimedPhotoCaptured

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b'\xFF\xD8\xFF' + b'\x00' * 10)
            fpath = f.name

        try:
            event = TimedPhotoCaptured("Garten", fpath, "📷 Foto um 08:00")
            telegram_ui._on_timed_photo_captured(event)

            mock_tc.broadcast_photo.assert_called_once()
            call_args = mock_tc.broadcast_photo.call_args
            caption = call_args.kwargs.get("caption") or (call_args.args[1] if len(call_args.args) > 1 else "")
            self.assertIn("08:00", caption)
        finally:
            os.unlink(fpath)

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_fehlendes_bild_wird_ignoriert(self, mock_tc):
        """TimedPhotoCaptured mit nicht vorhandenem Pfad → kein broadcast_photo."""
        from daemon.ui import telegram_ui
        from daemon.core.camera_events import TimedPhotoCaptured

        event = TimedPhotoCaptured("Garten", "/nonexistent/foto.jpg", "📷 Foto um 08:00")
        telegram_ui._on_timed_photo_captured(event)

        mock_tc.broadcast_photo.assert_not_called()


class TestZustellungFehlgeschlagen(unittest.TestCase):
    """Schlaegt der Versand fehl, darf der Aufnahme-Zeitpunkt nicht als erfuellt gelten."""

    @patch("daemon.ui.telegram_ui._global_bus")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_fehlgeschlagener_versand_meldet_das(self, mock_tc, mock_bus):
        from datetime import datetime
        from daemon.ui import telegram_ui
        from daemon.core.camera_events import TimedPhotoCaptured, TimedPhotoDeliveryFailed

        mock_tc.broadcast_photo.return_value = False  # Telegram nicht erreichbar

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b'\xFF\xD8\xFF' + b'\x00' * 10)
            fpath = f.name

        try:
            target = datetime(2026, 7, 14, 8, 0)
            event = TimedPhotoCaptured("Garten", fpath, "📷 Foto um 08:00",
                                       target_dt=target, captured_at=target,
                                       mac_address="AA:BB:CC")
            telegram_ui._on_timed_photo_captured(event)

            published = [c.args[0] for c in mock_bus.publish.call_args_list]
            assert any(isinstance(e, TimedPhotoDeliveryFailed) for e in published), \
                "Ein fehlgeschlagener Versand muss gemeldet werden, sonst ist das Foto still verloren"
        finally:
            os.unlink(fpath)


class TestAufnahmeVerzugMeldungen(unittest.TestCase):
    """Telegram-Nachrichten der zweiten Alarmklasse (ADR 0041)."""

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_warnung_nennt_kamera_und_verzug(self, mock_tc):
        from daemon.ui import telegram_ui
        from daemon.core.camera_events import CameraDelayAlertTriggered

        telegram_ui._on_camera_delay_alert(
            CameraDelayAlertTriggered("AA:BB", "Garten01", 28.0, 15)
        )

        msg = mock_tc.broadcast_notification.call_args.args[0]
        assert "Garten01" in msg
        assert "28" in msg, "Die Warnung muss den Verzug nennen"

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_entwarnung_nennt_die_kamera(self, mock_tc):
        from daemon.ui import telegram_ui
        from daemon.core.camera_events import CameraDelayAlertResolved

        telegram_ui._on_camera_delay_resolved(CameraDelayAlertResolved("AA:BB", "Garten01"))

        msg = mock_tc.broadcast_notification.call_args.args[0]
        assert "Garten01" in msg
