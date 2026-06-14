import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.telegram_ui import (
    handle_update,
    _read_local_version,
    _fetch_latest_release_tag,
    _process_callback_query,
)


class TestReadLocalVersion(unittest.TestCase):

    def test_reads_version_file(self):
        with patch("daemon.ui.telegram_ui._VERSION_FILE") as mock_path:
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = "v1.2.3\n"
            self.assertEqual(_read_local_version(), "v1.2.3")

    def test_returns_unbekannt_when_file_missing(self):
        with patch("daemon.ui.telegram_ui._VERSION_FILE") as mock_path:
            mock_path.exists.return_value = False
            self.assertEqual(_read_local_version(), "unbekannt")


class TestFetchLatestReleaseTag(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.config")
    def test_returns_fragezeichen_when_no_pat(self, mock_config):
        mock_config.GITHUB_PAT = ""
        mock_config.GITHUB_REPO = "test/garden"
        self.assertEqual(_fetch_latest_release_tag(), "?")

    @patch("daemon.ui.telegram_ui.config")
    def test_returns_fragezeichen_when_no_repo(self, mock_config):
        mock_config.GITHUB_PAT = "test-pat"
        mock_config.GITHUB_REPO = ""
        self.assertEqual(_fetch_latest_release_tag(), "?")

    @patch("daemon.ui.telegram_ui.config")
    @patch("urllib.request.urlopen")
    def test_returns_tag_from_api(self, mock_urlopen, mock_config):
        mock_config.GITHUB_PAT = "test-pat"
        mock_config.GITHUB_REPO = "test/garden"
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"tag_name": "v2.0.0"}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        self.assertEqual(_fetch_latest_release_tag(), "v2.0.0")

    @patch("daemon.ui.telegram_ui.config")
    @patch("urllib.request.urlopen", side_effect=Exception("timeout"))
    def test_returns_fragezeichen_on_error(self, mock_urlopen, mock_config):
        mock_config.GITHUB_PAT = "test-pat"
        mock_config.GITHUB_REPO = "test/garden"
        self.assertEqual(_fetch_latest_release_tag(), "?")


class TestHandleUpdate(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui._fetch_latest_release_tag", return_value="v1.2.0")
    @patch("daemon.ui.telegram_ui._read_local_version", return_value="v1.0.0")
    def test_zeigt_versionen_und_keyboard(self, _local, _remote, mock_client):
        handle_update(12345)

        mock_client.send_message.assert_called_once()
        text = mock_client.send_message.call_args[0][1]
        keyboard = mock_client.send_message.call_args[0][2]
        self.assertIn("v1.0.0", text)
        self.assertIn("v1.2.0", text)
        buttons = [b["callback_data"] for row in keyboard["inline_keyboard"] for b in row]
        self.assertIn("update_confirm", buttons)
        self.assertIn("update_cancel", buttons)

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui._fetch_latest_release_tag", return_value="v1.0.0")
    @patch("daemon.ui.telegram_ui._read_local_version", return_value="v1.0.0")
    def test_bereits_aktuell_kein_keyboard(self, _local, _remote, mock_client):
        handle_update(12345)

        mock_client.send_message.assert_called_once()
        args = mock_client.send_message.call_args[0]
        self.assertIn("aktuell", args[1].lower())
        self.assertEqual(len(args), 2)  # kein drittes Argument (kein Keyboard)

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui._fetch_latest_release_tag", return_value="?")
    @patch("daemon.ui.telegram_ui._read_local_version", return_value="v1.0.0")
    def test_api_nicht_erreichbar(self, _local, _remote, mock_client):
        handle_update(12345)

        mock_client.send_message.assert_called_once()
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("?", text)


class TestUpdateCallbacks(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("subprocess.Popen")
    def test_confirm_startet_subprocess(self, mock_popen, mock_client):
        cb = {
            "id": "cb1",
            "message": {"chat": {"id": 12345}, "message_id": 1},
            "data": "update_confirm",
        }
        _process_callback_query(cb)

        mock_popen.assert_called_once()
        cmd = " ".join(mock_popen.call_args[0][0])
        self.assertIn("update.sh", cmd)
        mock_client.send_message.assert_called_once()
        self.assertIn("gestartet", mock_client.send_message.call_args[0][1].lower())

    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_cancel_bricht_ab(self, mock_client):
        cb = {
            "id": "cb2",
            "message": {"chat": {"id": 12345}, "message_id": 1},
            "data": "update_cancel",
        }
        _process_callback_query(cb)

        mock_client.send_message.assert_called_once()
        self.assertIn("abgebrochen", mock_client.send_message.call_args[0][1].lower())


if __name__ == "__main__":
    unittest.main()
