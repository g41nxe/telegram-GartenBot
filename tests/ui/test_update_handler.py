import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.ui.telegram_ui import (
    handle_update,
    _read_local_version,
    _fetch_latest_release_info,
    _process_callback_query,
)


class TestReadLocalVersion(unittest.TestCase):

    def test_reads_version_file(self):
        with patch("daemon.config.VERSION_FILE") as mock_path:
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = "v1.2.3\n"
            self.assertEqual(_read_local_version(), "v1.2.3")

    def test_returns_unbekannt_when_file_missing(self):
        with patch("daemon.config.VERSION_FILE") as mock_path:
            mock_path.exists.return_value = False
            self.assertEqual(_read_local_version(), "unbekannt")


class TestFetchLatestReleaseInfo(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.config")
    def test_returns_fragezeichen_when_no_pat(self, mock_config):
        mock_config.GITHUB_PAT = ""
        mock_config.GITHUB_REPO = "test/garden"
        info = _fetch_latest_release_info()
        self.assertEqual(info["tag"], "?")
        self.assertEqual(info["notes"], "")

    @patch("daemon.ui.telegram_ui.config")
    def test_returns_fragezeichen_when_no_repo(self, mock_config):
        mock_config.GITHUB_PAT = "test-pat"
        mock_config.GITHUB_REPO = ""
        info = _fetch_latest_release_info()
        self.assertEqual(info["tag"], "?")

    @patch("daemon.ui.telegram_ui.config")
    @patch("urllib.request.urlopen")
    def test_returns_info_from_api(self, mock_urlopen, mock_config):
        mock_config.GITHUB_PAT = "test-pat"
        mock_config.GITHUB_REPO = "test/garden"
        mock_resp = MagicMock()
        mock_resp.read.return_value = '{"tag_name": "v2.0.0", "name": "2026-06-14 - v2.0.0", "body": "- Feature X"}'.encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        info = _fetch_latest_release_info()
        self.assertEqual(info["tag"], "v2.0.0")
        self.assertIn("2026-06-14", info["name"])
        self.assertIn("Feature X", info["notes"])

    @patch("daemon.ui.telegram_ui.config")
    @patch("urllib.request.urlopen", side_effect=Exception("timeout"))
    def test_returns_fragezeichen_on_error(self, mock_urlopen, mock_config):
        mock_config.GITHUB_PAT = "test-pat"
        mock_config.GITHUB_REPO = "test/garden"
        info = _fetch_latest_release_info()
        self.assertEqual(info["tag"], "?")
        self.assertEqual(info["notes"], "")


class TestHandleUpdate(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui._fetch_latest_release_info",
           return_value={"tag": "v1.2.0", "name": "2026-06-14 — v1.2.0", "notes": "- Feature X\n- Feature Y"})
    @patch("daemon.ui.telegram_ui._read_local_version", return_value="v1.0.0")
    def test_zeigt_versionen_notes_und_keyboard(self, _local, _info, mock_client):
        handle_update(12345)

        mock_client.send_message.assert_called_once()
        text = mock_client.send_message.call_args[0][1]
        keyboard = mock_client.send_message.call_args[0][2]
        self.assertIn("v1.0.0", text)
        self.assertIn("2026-06-14", text)
        self.assertIn("Feature X", text)
        buttons = [b["callback_data"] for row in keyboard["inline_keyboard"] for b in row]
        self.assertIn("update_confirm", buttons)
        self.assertIn("update_cancel", buttons)

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui._fetch_latest_release_info",
           return_value={"tag": "v1.0.0", "name": "2026-06-01 — v1.0.0", "notes": ""})
    @patch("daemon.ui.telegram_ui._read_local_version", return_value="v1.0.0")
    def test_bereits_aktuell_kein_keyboard(self, _local, _info, mock_client):
        handle_update(12345)

        mock_client.send_message.assert_called_once()
        args = mock_client.send_message.call_args[0]
        self.assertIn("aktuell", args[1].lower())
        self.assertEqual(len(args), 2)

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui._fetch_latest_release_info",
           return_value={"tag": "?", "name": "?", "notes": ""})
    @patch("daemon.ui.telegram_ui._read_local_version", return_value="v1.0.0")
    def test_api_nicht_erreichbar(self, _local, _info, mock_client):
        handle_update(12345)

        mock_client.send_message.assert_called_once()
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("?", text)

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui._fetch_latest_release_info",
           return_value={"tag": "v1.2.0", "name": "2026-06-14 — v1.2.0", "notes": "x" * 1000})
    @patch("daemon.ui.telegram_ui._read_local_version", return_value="v1.0.0")
    def test_kuerzt_notes_auf_800_zeichen(self, _local, _info, mock_client):
        handle_update(12345)

        text = mock_client.send_message.call_args[0][1]
        self.assertIn("…", text)
        notes_start = text.find("📋")
        notes_section = text[notes_start:] if notes_start >= 0 else text
        self.assertLessEqual(len(notes_section), 950)


    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui._fetch_latest_release_info",
           return_value={"tag": "v1.2.0", "name": "v1.2.0", "notes": "- _italic_ und *bold* und `code`"})
    @patch("daemon.ui.telegram_ui._read_local_version", return_value="v1.0.0")
    def test_notes_markdown_sonderzeichen_werden_escaped(self, _local, _info, mock_client):
        """Markdown-Sonderzeichen in den Notes dürfen den Telegram-Parser nicht brechen."""
        mock_client.send_message.return_value = True
        handle_update(12345)

        text = mock_client.send_message.call_args[0][1]
        self.assertIn("\\_italic\\_", text)
        self.assertIn("\\*bold\\*", text)
        self.assertIn("\\`code\\`", text)

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui._fetch_latest_release_info",
           return_value={"tag": "v1.2.0", "name": "v1.2.0", "notes": "- Neues Feature"})
    @patch("daemon.ui.telegram_ui._read_local_version", return_value="v1.0.0")
    def test_fallback_wenn_send_message_fehlschlaegt(self, _local, _info, mock_client):
        """Wenn send_message False zurückgibt, wird ein einfacher Fallback-Dialog gesendet."""
        mock_client.send_message.side_effect = [False, True]
        handle_update(12345)

        self.assertEqual(mock_client.send_message.call_count, 2)
        fallback_text = mock_client.send_message.call_args[0][1]
        self.assertIn("v1.0.0", fallback_text)
        self.assertIn("v1.2.0", fallback_text)
        # Fallback enthält den confirm-Button
        kb = mock_client.send_message.call_args[0][2]
        buttons = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
        self.assertIn("update_confirm", buttons)


class TestUpdateCallbacks(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("subprocess.Popen")
    def test_confirm_schreibt_notify_datei_und_startet_subprocess(self, mock_popen, mock_client):
        notify = Path("/tmp/garden-ota-notify")
        if notify.exists():
            notify.unlink()
        cb = {
            "id": "cb1",
            "message": {"chat": {"id": 12345}, "message_id": 1},
            "data": "update_confirm",
        }
        _process_callback_query(cb)

        mock_popen.assert_called_once()
        cmd = " ".join(mock_popen.call_args[0][0])
        self.assertIn("update.sh", cmd)
        self.assertTrue(notify.exists())
        self.assertEqual(notify.read_text().strip(), "12345")
        mock_client.send_message.assert_called_once()
        self.assertIn("gestartet", mock_client.send_message.call_args[0][1].lower())
        notify.unlink(missing_ok=True)

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
