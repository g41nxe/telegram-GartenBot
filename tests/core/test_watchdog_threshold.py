import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.watchdog_threshold import valve_timeout_seconds


class TestValveTimeoutSeconds(unittest.TestCase):
    """Die Inaktivitäts-Schwelle leitet sich aus dem Melde-Verhalten des Geräts ab.

    Ein fester 24-Stunden-Wert lässt bei einem Ventil, das alle fünf Minuten funkt,
    288 ausgebliebene Meldungen verstreichen, bevor jemand etwas merkt
    (telegram_GartenBot-8zj).
    """

    MIN = 3600.0      # Mindestschwelle: 1 h
    MAX = 86400.0     # Obergrenze: der bisherige Fixwert von 24 h
    FACTOR = 3.0

    def _timeout(self, interval):
        return valve_timeout_seconds(interval, self.MIN, self.MAX, self.FACTOR)

    def test_derives_from_interval(self):
        """Faktor × Intervall, sobald das Ergebnis über der Mindestschwelle liegt."""
        # 30-Min-Takt → 90 Min
        self.assertEqual(self._timeout(1800), 5400.0)

    def test_floor_protects_chatty_devices(self):
        """Ein 5-Minuten-Takt ergäbe 15 Min — die Mindestschwelle verhindert Fehlalarme."""
        self.assertEqual(self._timeout(300), self.MIN)

    def test_floor_protects_very_chatty_devices(self):
        """Ein 6-Sekunden-Takt ergäbe 18 s; ein WLAN-Wackler darf nicht sofort melden."""
        self.assertEqual(self._timeout(6), self.MIN)

    def test_ceiling_keeps_configured_maximum(self):
        """Ein sehr träges Gerät reißt die Obergrenze nicht: 24 h bleiben das Maximum."""
        self.assertEqual(self._timeout(12 * 3600), self.MAX)

    def test_unknown_interval_falls_back_to_maximum(self):
        """Ohne Messdaten bleibt es beim bisherigen Verhalten — kein Blindflug nach unten."""
        self.assertEqual(self._timeout(None), self.MAX)

    def test_nonsensical_interval_falls_back_to_maximum(self):
        """Ein nicht-positives Intervall ist keine Messung, sondern ein Datenfehler."""
        self.assertEqual(self._timeout(0), self.MAX)
        self.assertEqual(self._timeout(-5), self.MAX)

    def test_result_never_below_floor_even_if_max_is_smaller(self):
        """Widersprüchliche Konfiguration (max < min) darf keine Schwelle unter max liefern."""
        # Deckel gewinnt: er ist die ausdrücklich konfigurierte Obergrenze.
        self.assertEqual(valve_timeout_seconds(300, 3600.0, 1800.0, 3.0), 1800.0)


if __name__ == "__main__":
    unittest.main()
