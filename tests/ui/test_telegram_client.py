import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui import telegram_client
from daemon import config

_FAKE_PNG = b"\x89PNG\r\nfake-image-data"
_FAKE_TOKEN = "123:ABC-test-token"


def _mock_urlopen_200():
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock = MagicMock(return_value=mock_resp)
    return mock


class TestSendPhoto(unittest.TestCase):

    @patch.object(config, "TELEGRAM_BOT_TOKEN", "")
    def test_returns_false_without_token(self):
        result = telegram_client.send_photo(chat_id=100, image_bytes=_FAKE_PNG)
        self.assertFalse(result)

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_returns_true_on_200(self, mock_urlopen):
        mock_urlopen.side_effect = _mock_urlopen_200()
        result = telegram_client.send_photo(chat_id=100, image_bytes=_FAKE_PNG)
        self.assertTrue(result)

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen",
           side_effect=urllib.error.URLError("timeout"))
    def test_returns_false_on_network_error(self, _):
        result = telegram_client.send_photo(chat_id=100, image_bytes=_FAKE_PNG)
        self.assertFalse(result)

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_content_type_is_multipart(self, mock_urlopen):
        captured = {}

        def capture(req, timeout=None):
            captured["headers"] = req.headers
            return _mock_urlopen_200()()

        mock_urlopen.side_effect = capture
        telegram_client.send_photo(chat_id=100, image_bytes=_FAKE_PNG)

        content_type = captured["headers"].get("Content-type", "")
        self.assertIn("multipart/form-data", content_type)

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_image_bytes_in_request_body(self, mock_urlopen):
        captured = {}

        def capture(req, timeout=None):
            captured["data"] = req.data
            return _mock_urlopen_200()()

        mock_urlopen.side_effect = capture
        telegram_client.send_photo(chat_id=100, image_bytes=_FAKE_PNG)

        self.assertIn(_FAKE_PNG, captured["data"])

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_caption_included_when_provided(self, mock_urlopen):
        captured = {}

        def capture(req, timeout=None):
            captured["data"] = req.data
            return _mock_urlopen_200()()

        mock_urlopen.side_effect = capture
        telegram_client.send_photo(chat_id=100, image_bytes=_FAKE_PNG, caption="Wetterverlauf")

        self.assertIn(b"Wetterverlauf", captured["data"])

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_no_caption_field_when_omitted(self, mock_urlopen):
        captured = {}

        def capture(req, timeout=None):
            captured["data"] = req.data
            return _mock_urlopen_200()()

        mock_urlopen.side_effect = capture
        telegram_client.send_photo(chat_id=100, image_bytes=_FAKE_PNG, caption=None)

        self.assertNotIn(b"caption", captured["data"])


class TestSendChatAction(unittest.TestCase):

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_send_chat_action_posts_correct_payload(self, mock_urlopen):
        mock_urlopen.side_effect = _mock_urlopen_200()
        telegram_client.send_chat_action(12345, "typing")
        call_args = mock_urlopen.call_args[0][0]
        payload = json.loads(call_args.data.decode())
        self.assertEqual(payload["chat_id"], 12345)
        self.assertEqual(payload["action"], "typing")
        self.assertIn("sendChatAction", call_args.full_url)

    @patch.object(config, "TELEGRAM_BOT_TOKEN", "")
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_send_chat_action_skips_without_token(self, mock_urlopen):
        telegram_client.send_chat_action(12345, "typing")
        mock_urlopen.assert_not_called()


class TestSetMyCommands(unittest.TestCase):

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_set_my_commands_posts_commands_list(self, mock_urlopen):
        mock_urlopen.side_effect = _mock_urlopen_200()
        commands = [{"command": "status", "description": "Systemstatus anzeigen"}]
        telegram_client.set_my_commands(commands)
        call_args = mock_urlopen.call_args[0][0]
        payload = json.loads(call_args.data.decode())
        self.assertEqual(payload["commands"], commands)
        self.assertIn("setMyCommands", call_args.full_url)

    @patch.object(config, "TELEGRAM_BOT_TOKEN", "")
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_set_my_commands_skips_without_token(self, mock_urlopen):
        telegram_client.set_my_commands([{"command": "status", "description": "Test"}])
        mock_urlopen.assert_not_called()


class TestSendMessageMarkdownFallback(unittest.TestCase):
    """Ein Markdown-Parse-Fehler (HTTP 400) darf die Nachricht nicht verschlucken."""

    def _ok_resp(self):
        resp = MagicMock()
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_markdown_400_falls_back_to_plaintext(self, mock_urlopen):
        sent = []

        def side_effect(req, *a, **k):
            sent.append(json.loads(req.data.decode("utf-8")))
            if len(sent) == 1:
                raise urllib.error.HTTPError("url", 400, "Bad Request", {}, None)
            return self._ok_resp()

        mock_urlopen.side_effect = side_effect
        result = telegram_client.send_message(123, "Zeitplan valve_report_test *")

        self.assertTrue(result)                              # Nachricht ist durchgekommen
        self.assertEqual(len(sent), 2)                       # genau ein Fallback-Versuch
        self.assertEqual(sent[0].get("parse_mode"), "Markdown")
        self.assertNotIn("parse_mode", sent[1])              # Fallback ohne Formatierung
        self.assertEqual(sent[1]["text"], "Zeitplan valve_report_test *")

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_non_400_error_does_not_retry(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError("url", 403, "Forbidden", {}, None)
        result = telegram_client.send_message(123, "x")
        self.assertFalse(result)
        self.assertEqual(mock_urlopen.call_count, 1)         # kein Fallback bei 403

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_400_logs_telegram_description_and_preview(self, mock_urlopen):
        """Der 400-Log enthält die Telegram-'description' und eine Text-Vorschau (Anhaltspunkt)."""
        import io
        body = json.dumps({
            "ok": False, "error_code": 400,
            "description": "Bad Request: can't parse entities: Character '_' is reserved",
        }).encode("utf-8")
        state = {"n": 0}

        def side_effect(req, *a, **k):
            state["n"] += 1
            if state["n"] == 1:
                raise urllib.error.HTTPError("url", 400, "Bad Request", {}, io.BytesIO(body))
            return self._ok_resp()

        mock_urlopen.side_effect = side_effect
        with self.assertLogs("garden_telegram_client", level="WARNING") as cm:
            telegram_client.send_message(123, "Zeitplan valve_report_test geöffnet")

        joined = " ".join(cm.output)
        self.assertIn("can't parse entities", joined)            # echte Telegram-Begründung
        self.assertIn("valve_report_test", joined)               # Text-Vorschau der Nachricht


class TestSendMessageSplitting(unittest.TestCase):
    """Nachrichten über dem Telegram-Limit werden aufgeteilt statt verworfen (HTTP 400 'too long')."""

    def _ok_resp(self):
        resp = MagicMock()
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_long_message_is_split_into_multiple_sends(self, mock_urlopen):
        sent = []

        def side_effect(req, *a, **k):
            sent.append(json.loads(req.data.decode("utf-8")))
            return self._ok_resp()

        mock_urlopen.side_effect = side_effect
        long_text = "\n".join(f"🆔 Zeile Nummer {i} mit etwas Text" for i in range(400))
        markup = {"inline_keyboard": [[{"text": "x", "callback_data": "y"}]]}

        result = telegram_client.send_message(123, long_text, markup)

        self.assertTrue(result)
        self.assertGreater(len(sent), 1)                                  # mehrfach gesendet
        for part in sent:
            self.assertLessEqual(telegram_client._utf16_len(part["text"]), 4096)
        # Tastatur nur an der letzten Teilnachricht
        self.assertNotIn("reply_markup", sent[0])
        self.assertIn("reply_markup", sent[-1])

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_short_message_is_single_send(self, mock_urlopen):
        sent = []
        mock_urlopen.side_effect = lambda req, *a, **k: (sent.append(1), self._ok_resp())[1]
        telegram_client.send_message(123, "kurz")
        self.assertEqual(len(sent), 1)


def _mock_resp_200_body(body_bytes):
    resp = MagicMock()
    resp.status = 200
    resp.read.return_value = body_bytes
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestSendMessageId(unittest.TestCase):
    """Feature 0037: send_message_id liefert die message_id für Assistenten-Prompts."""

    @patch.object(config, "TELEGRAM_BOT_TOKEN", "")
    def test_returns_none_without_token(self):
        self.assertIsNone(telegram_client.send_message_id(123, "hi"))

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_returns_message_id_on_200(self, mock_urlopen):
        body = json.dumps({"ok": True, "result": {"message_id": 4242}}).encode("utf-8")
        mock_urlopen.return_value = _mock_resp_200_body(body)
        self.assertEqual(telegram_client.send_message_id(123, "hi"), 4242)

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_returns_none_on_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError("url", 403, "Forbidden", {}, None)
        self.assertIsNone(telegram_client.send_message_id(123, "hi"))

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_markdown_400_falls_back_to_plaintext(self, mock_urlopen):
        body = json.dumps({"ok": True, "result": {"message_id": 7}}).encode("utf-8")
        calls = []

        def side(req, *a, **k):
            calls.append(req)
            if len(calls) == 1:
                raise urllib.error.HTTPError("url", 400, "Bad Request", {}, None)
            return _mock_resp_200_body(body)

        mock_urlopen.side_effect = side
        self.assertEqual(telegram_client.send_message_id(123, "Zeitplan *"), 7)
        self.assertEqual(len(calls), 2)  # genau ein Fallback


class TestEditMessageReplyMarkup(unittest.TestCase):
    """Feature 0033: Inline-Keyboard einer bestehenden Nachricht entfernen/ersetzen."""

    @patch.object(config, "TELEGRAM_BOT_TOKEN", "")
    def test_returns_false_without_token(self):
        self.assertFalse(telegram_client.edit_message_reply_markup(123, 45, None))

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_returns_true_on_200(self, mock_urlopen):
        mock_urlopen.side_effect = _mock_urlopen_200()
        self.assertTrue(telegram_client.edit_message_reply_markup(123, 45, None))

    @patch.object(config, "TELEGRAM_BOT_TOKEN", _FAKE_TOKEN)
    @patch("daemon.ui.telegram_client.urllib.request.urlopen")
    def test_endpoint_and_payload_without_markup(self, mock_urlopen):
        captured = {}

        def capture(req, *a, **k):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _mock_urlopen_200()()

        mock_urlopen.side_effect = capture
        telegram_client.edit_message_reply_markup(123, 45, None)
        self.assertIn("editMessageReplyMarkup", captured["url"])
        self.assertEqual(captured["body"]["chat_id"], 123)
        self.assertEqual(captured["body"]["message_id"], 45)
        self.assertNotIn("reply_markup", captured["body"])  # None → Keyboard entfällt


if __name__ == "__main__":
    unittest.main()
