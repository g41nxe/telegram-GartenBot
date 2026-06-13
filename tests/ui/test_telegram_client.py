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


if __name__ == "__main__":
    unittest.main()
