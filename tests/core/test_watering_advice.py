import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import daemon.core.watering_advice as advice


class TestEvaluateRainWindow(unittest.TestCase):

    def test_below_threshold_does_not_skip(self):
        result = advice.evaluate_rain_window(0.5, 0.3, threshold_mm=2.0)
        self.assertFalse(result.skip)
        self.assertAlmostEqual(result.total_mm, 0.8)

    def test_exactly_at_threshold_skips(self):
        result = advice.evaluate_rain_window(1.0, 1.0, threshold_mm=2.0)
        self.assertTrue(result.skip)
        self.assertAlmostEqual(result.total_mm, 2.0)

    def test_above_threshold_skips(self):
        result = advice.evaluate_rain_window(6.1, 0.0, threshold_mm=2.0)
        self.assertTrue(result.skip)
        self.assertAlmostEqual(result.total_mm, 6.1)

    def test_total_is_sum_of_both_windows(self):
        result = advice.evaluate_rain_window(2.4, 1.1, threshold_mm=2.0)
        self.assertAlmostEqual(result.total_mm, 3.5)
