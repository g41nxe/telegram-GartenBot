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


if __name__ == "__main__":
    unittest.main()
