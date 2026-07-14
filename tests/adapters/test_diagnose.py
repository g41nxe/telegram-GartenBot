import io
import os
import sys
import sqlite3
import zipfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.adapters import diagnose, database


def _fake_journal_ok(cmd, **kwargs):
    """Simuliert erfolgreiche subprocess-Aufrufe (journalctl, systemctl)."""
    m = MagicMock()
    m.returncode = 0
    m.stdout = "Jun 30 08:00:01 pi daemon[123]: Beispielzeile 1\nJun 30 08:00:02 pi daemon[123]: Beispielzeile 2\n"
    return m


ALL_FILES = {"journal_daemon.txt", "journal_zigbee2mqtt.txt", "garden.db", "garden.conf", "system_info.txt"}


class TestDiagnosePaket(unittest.TestCase):
    """Feature 0041: Sammel-Logik des Diagnose-Pakets (Degradations-Politik, .env-Garantie)."""

    def setUp(self):
        # Temporäre Datenbank mit erkennbarem Inhalt
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        con = sqlite3.connect(self.db_path)
        con.execute("CREATE TABLE schedules (id INTEGER PRIMARY KEY, name TEXT)")
        con.execute("INSERT INTO schedules (name) VALUES ('Rasen')")
        con.commit()
        con.close()
        self._db_patch = patch.object(database, "DB_PATH", self.db_path)
        self._db_patch.start()

        # Temporäre fachliche Konfiguration
        fd, self.conf_path = tempfile.mkstemp(suffix=".conf")
        os.close(fd)
        Path(self.conf_path).write_text("RAIN_THRESHOLD_MM=3.0\n", encoding="utf-8")
        self._conf_patch = patch.object(diagnose, "GARDEN_CONF_PATH", Path(self.conf_path))
        self._conf_patch.start()

    def tearDown(self):
        self._db_patch.stop()
        self._conf_patch.stop()
        for p in (self.db_path, self.conf_path):
            try:
                os.unlink(p)
            except OSError:
                pass

    @staticmethod
    def _namelist(blob: bytes) -> list:
        return zipfile.ZipFile(io.BytesIO(blob)).namelist()

    # --- Happy Path -------------------------------------------------------

    @patch("daemon.adapters.diagnose.subprocess.run", side_effect=_fake_journal_ok)
    def test_happy_path_contains_all_bausteine(self, _run):
        blob, missing = diagnose.collect_diagnose_paket()
        self.assertIsNotNone(blob)
        self.assertEqual(missing, [])
        self.assertEqual(set(self._namelist(blob)), ALL_FILES)

    @patch("daemon.adapters.diagnose.subprocess.run", side_effect=_fake_journal_ok)
    def test_journal_content_lands_in_archive(self, _run):
        blob, _ = diagnose.collect_diagnose_paket()
        zf = zipfile.ZipFile(io.BytesIO(blob))
        text = zf.read("journal_daemon.txt").decode("utf-8")
        self.assertIn("Beispielzeile 1", text)

    # --- .env-Garantie ----------------------------------------------------

    @patch("daemon.adapters.diagnose.subprocess.run", side_effect=_fake_journal_ok)
    def test_env_datei_erscheint_niemals_im_archiv(self, _run):
        blob, _ = diagnose.collect_diagnose_paket()
        for name in self._namelist(blob):
            self.assertNotIn(".env", name, f"Geheimnis-Datei im Archiv gefunden: {name}")

    # --- Degradations-Politik ---------------------------------------------

    @patch("daemon.adapters.diagnose.subprocess.run", side_effect=FileNotFoundError("journalctl fehlt"))
    def test_journal_fehler_degradiert_statt_abbruch(self, _run):
        blob, missing = diagnose.collect_diagnose_paket()
        self.assertIsNotNone(blob)
        names = set(self._namelist(blob))
        self.assertNotIn("journal_daemon.txt", names)
        self.assertNotIn("journal_zigbee2mqtt.txt", names)
        # Übrige Bausteine vorhanden
        self.assertIn("garden.db", names)
        self.assertIn("garden.conf", names)
        self.assertIn("system_info.txt", names)
        self.assertTrue(any("journal_daemon" in m for m in missing))
        self.assertTrue(any("journal_zigbee2mqtt" in m for m in missing))

    @patch("daemon.adapters.diagnose.subprocess.run", side_effect=_fake_journal_ok)
    def test_db_fehler_degradiert_statt_abbruch(self, _run):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Ein Verzeichnis als DB-Pfad → sqlite3.connect schlägt fehl
            with patch.object(database, "DB_PATH", tmpdir):
                blob, missing = diagnose.collect_diagnose_paket()
        self.assertIsNotNone(blob)
        names = set(self._namelist(blob))
        self.assertNotIn("garden.db", names)
        self.assertIn("journal_daemon.txt", names)
        self.assertTrue(any("garden.db" in m for m in missing))

    @patch("daemon.adapters.diagnose.subprocess.run", side_effect=FileNotFoundError("kein subprocess"))
    def test_fast_totalausfall_liefert_steckbrief_mit_lueckenliste(self, _run):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(database, "DB_PATH", tmpdir), \
                 patch.object(diagnose, "GARDEN_CONF_PATH", Path(tmpdir) / "gibts-nicht.conf"):
                blob, missing = diagnose.collect_diagnose_paket()
        self.assertIsNotNone(blob, "Solange ein Baustein einsammelbar ist, entsteht ein Paket")
        names = set(self._namelist(blob))
        self.assertIn("system_info.txt", names)
        self.assertGreaterEqual(len(missing), 4)

    # --- Konsistenter Datenbank-Schnappschuss ------------------------------

    @patch("daemon.adapters.diagnose.subprocess.run", side_effect=_fake_journal_ok)
    def test_db_schnappschuss_ist_oeffnbar_und_vollstaendig(self, _run):
        blob, _ = diagnose.collect_diagnose_paket()
        zf = zipfile.ZipFile(io.BytesIO(blob))
        fd, snap_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            Path(snap_path).write_bytes(zf.read("garden.db"))
            con = sqlite3.connect(snap_path)
            rows = con.execute("SELECT name FROM schedules").fetchall()
            con.close()
            self.assertEqual(rows, [("Rasen",)])
        finally:
            os.unlink(snap_path)

    # --- Größen-Wächter -----------------------------------------------------

    @patch("daemon.adapters.diagnose.subprocess.run", side_effect=_fake_journal_ok)
    def test_uebergroesse_wirft_datenbank_ab(self, _run):
        # Datenbank mit inkompressiblem Inhalt aufpumpen (>100 KB)
        con = sqlite3.connect(self.db_path)
        con.execute("CREATE TABLE blobs (data BLOB)")
        for _ in range(20):
            con.execute("INSERT INTO blobs (data) VALUES (?)", (os.urandom(8192),))
        con.commit()
        con.close()

        blob, missing = diagnose.collect_diagnose_paket(max_bytes=20_000)
        self.assertIsNotNone(blob)
        self.assertLessEqual(len(blob), 20_000)
        names = set(self._namelist(blob))
        self.assertNotIn("garden.db", names, "Bei Übergröße muss die Datenbank weichen")
        self.assertIn("journal_daemon.txt", names)
        self.assertTrue(any("garden.db" in m for m in missing))


if __name__ == "__main__":
    unittest.main()
