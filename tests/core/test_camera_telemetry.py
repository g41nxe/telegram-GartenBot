import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.camera_telemetry import summarize


def _row(fail_count=0, wifi_connect_ms=1000, request_ms=300):
    return {"fail_count": fail_count, "wifi_connect_ms": wifi_connect_ms,
            "request_ms": request_ms}


class TestSummarize(unittest.TestCase):
    """Verdichtet die Telemetrie-Zeilen einer Kamera für den Diagnose-Bericht (Ticket top).

    Reine Rechnung, kein I/O: Die Zeilen holt der Adapter, die Aussage entsteht hier.
    """

    def test_empty_returns_none(self):
        """Ohne Zeilen gibt es nichts zu berichten."""
        self.assertIsNone(summarize([]))

    def test_counts_uploads(self):
        s = summarize([_row(), _row(), _row()])
        self.assertEqual(s["uploads"], 3)

    def test_averages_and_maximum_of_request_duration(self):
        """Der Mittelwert zeigt den Normalfall, das Maximum den schlimmsten Upload.

        Für die Verdachtsfrage zählt vor allem das Maximum: Ein einzelner langer Request
        reicht, damit die Kamera in ihr Timeout läuft.
        """
        s = summarize([_row(request_ms=100), _row(request_ms=200), _row(request_ms=1800)])
        self.assertEqual(s["request_ms_avg"], 700)
        self.assertEqual(s["request_ms_max"], 1800)

    def test_reports_latest_fail_count(self):
        """Die Zeilen kommen neueste zuerst — der jüngste failCount ist der aktuelle."""
        s = summarize([_row(fail_count=4), _row(fail_count=1), _row(fail_count=0)])
        self.assertEqual(s["fail_count_last"], 4)
        self.assertEqual(s["fail_count_max"], 4)

    def test_counts_uploads_with_reported_failures(self):
        """Wie oft meldete die Kamera einen vorangegangenen Fehlschlag?

        Das ist die eigentliche Frage: Uploads, die der Daemon als erfolgreich
        protokolliert hat, während die Kamera von gescheiterten Versuchen berichtet.
        """
        s = summarize([_row(fail_count=0), _row(fail_count=2), _row(fail_count=0),
                       _row(fail_count=1)])
        self.assertEqual(s["uploads_with_failures"], 2)

    def test_missing_camera_metrics_are_reported_as_such(self):
        """Nur NULL-Werte heißt: Die Firmware sendet die Kennzahlen nicht."""
        rows = [_row(fail_count=None, wifi_connect_ms=None),
                _row(fail_count=None, wifi_connect_ms=None)]
        s = summarize(rows)
        self.assertFalse(s["has_camera_metrics"])
        self.assertIsNone(s["fail_count_last"])
        # Die selbst gemessene Dauer bleibt davon unberührt.
        self.assertEqual(s["request_ms_avg"], 300)

    def test_partial_metrics_still_count(self):
        """Eine Kamera, die erst seit einem Firmware-Wechsel meldet, zählt trotzdem."""
        rows = [_row(fail_count=3), _row(fail_count=None, wifi_connect_ms=None)]
        s = summarize(rows)
        self.assertTrue(s["has_camera_metrics"])
        self.assertEqual(s["fail_count_last"], 3)
        self.assertEqual(s["uploads"], 2)

    def test_missing_request_ms_does_not_break(self):
        """Zeilen aus einer älteren Fassung ohne request_ms dürfen nicht stören."""
        s = summarize([_row(request_ms=None), _row(request_ms=400)])
        self.assertEqual(s["request_ms_avg"], 400)
        self.assertEqual(s["request_ms_max"], 400)

    def test_all_request_ms_missing(self):
        s = summarize([_row(request_ms=None)])
        self.assertIsNone(s["request_ms_avg"])
        self.assertIsNone(s["request_ms_max"])


if __name__ == "__main__":
    unittest.main()
