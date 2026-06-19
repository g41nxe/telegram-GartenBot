import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class TestConfigLoading(unittest.TestCase):

    def tearDown(self):
        import importlib
        import daemon.config as cfg
        importlib.reload(cfg)

    def _reload_config(self, env_vars: dict):
        import importlib
        import daemon.config as cfg
        with patch.dict(os.environ, env_vars, clear=False):
            importlib.reload(cfg)
        return cfg

    def test_garden_conf_value_is_loaded(self):
        """Wert aus garden.conf wird geladen wenn nicht in .env oder Shell-Env."""
        import daemon.config as cfg
        self.assertIsInstance(cfg.RAIN_THRESHOLD_MM, float)

    def test_env_overrides_garden_conf(self):
        """.env-Wert überschreibt garden.conf."""
        cfg = self._reload_config({"RAIN_THRESHOLD_MM": "9.9"})
        self.assertAlmostEqual(cfg.RAIN_THRESHOLD_MM, 9.9)

    def test_shell_env_overrides_dot_env(self):
        """Shell-Env-Variable hat höchste Priorität."""
        with patch.dict(os.environ, {"RAIN_THRESHOLD_MM": "7.7"}, clear=False):
            cfg = self._reload_config({})
            self.assertAlmostEqual(cfg.RAIN_THRESHOLD_MM, 7.7)

    def test_missing_garden_conf_uses_fallback(self):
        """Fehlende garden.conf → Daemon startet mit Fallback-Werten, kein Absturz."""
        import importlib
        import daemon.config as cfg
        with patch("daemon.config._GARDEN_CONF_PATH", Path("/nonexistent/garden.conf")):
            importlib.reload(cfg)
            self.assertIsInstance(cfg.RAIN_THRESHOLD_MM, float)


class TestGetSetting(unittest.TestCase):

    def test_get_setting_gibt_db_override_zurueck(self):
        """get_setting liefert den DB-Wert wenn ein Override gesetzt ist."""
        with patch("daemon.adapters.database.get_metadata", return_value="4.5"):
            import daemon.config as cfg
            result = cfg.get_setting("RAIN_THRESHOLD_MM", 2.0)
            self.assertAlmostEqual(result, 4.5)

    def test_get_setting_faellt_auf_modulkonstante_zurueck(self):
        """get_setting liefert den Modulwert wenn kein DB-Override vorhanden."""
        with patch("daemon.adapters.database.get_metadata", return_value=None):
            import daemon.config as cfg
            result = cfg.get_setting("RAIN_THRESHOLD_MM", 2.0)
            self.assertAlmostEqual(result, cfg.RAIN_THRESHOLD_MM)

    def test_get_setting_liefert_default_wenn_attribut_fehlt(self):
        """get_setting liefert den angegebenen Default wenn weder DB noch Modul-Attr vorhanden."""
        with patch("daemon.adapters.database.get_metadata", return_value=None):
            import daemon.config as cfg
            result = cfg.get_setting("NONEXISTENT_SETTING_XYZ", 99.0)
            self.assertAlmostEqual(result, 99.0)

    def test_get_setting_konvertiert_float(self):
        """get_setting konvertiert DB-String-Wert zu float wenn default float."""
        with patch("daemon.adapters.database.get_metadata", return_value="3.5"):
            import daemon.config as cfg
            result = cfg.get_setting("RAIN_THRESHOLD_MM", 2.0)
            self.assertIsInstance(result, float)

    def test_get_setting_konvertiert_int(self):
        """get_setting konvertiert DB-String-Wert zu int wenn default int."""
        with patch("daemon.adapters.database.get_metadata", return_value="25"):
            import daemon.config as cfg
            result = cfg.get_setting("BATTERY_WARNING_THRESHOLD", 20)
            self.assertIsInstance(result, int)
            self.assertEqual(result, 25)

    def test_set_setting_speichert_in_db(self):
        """set_setting schreibt den Wert in system_metadata."""
        with patch("daemon.adapters.database.set_metadata") as mock_set:
            import daemon.config as cfg
            cfg.set_setting("RAIN_THRESHOLD_MM", 4.0)
            mock_set.assert_called_once_with("setting_RAIN_THRESHOLD_MM", "4.0")

    def test_reset_setting_loescht_db_override(self):
        """reset_setting entfernt den DB-Override."""
        with patch("daemon.adapters.database.delete_metadata") as mock_del:
            import daemon.config as cfg
            cfg.reset_setting("RAIN_THRESHOLD_MM")
            mock_del.assert_called_once_with("setting_RAIN_THRESHOLD_MM")


if __name__ == "__main__":
    unittest.main()
