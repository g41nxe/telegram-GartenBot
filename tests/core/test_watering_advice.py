import sys
import unittest
from datetime import date, timedelta
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


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _hot_days(n: int, temp: float = 28.0) -> list:
    return [(_days_ago(i), temp) for i in range(1, n + 1)]


def _cold_days(n: int, temp: float = 15.0) -> list:
    return [(_days_ago(i), temp) for i in range(1, n + 1)]


class TestEvaluateWatering(unittest.TestCase):

    def _eval(
        self,
        rain_last: float = 0.2,
        rain_next_eff: float = 0.1,
        temp_today: float = 15.0,
        past: list | None = None,
        threshold: float = 3.0,
    ) -> advice.WateringDecision:
        return advice.evaluate_watering(
            rain_last_mm=rain_last,
            rain_next_eff_mm=rain_next_eff,
            temp_max_today=temp_today,
            past_daily_temps=past or [],
            threshold_mm=threshold,
        )

    # --- Factor/Verdict matrix ---

    def test_no_rain_cold_no_streak_full_watering(self):
        d = self._eval(rain_last=0.0, rain_next_eff=0.0, temp_today=15.0)
        self.assertAlmostEqual(d.factor, 1.0)
        self.assertIn("🚿", d.verdict)
        self.assertFalse(d.skip)

    def test_enough_rain_cold_skips(self):
        d = self._eval(rain_last=2.0, rain_next_eff=2.0, temp_today=15.0)
        self.assertAlmostEqual(d.factor, 0.0)
        self.assertIn("🌧", d.verdict)
        self.assertTrue(d.skip)

    def test_partial_rain_cold_gives_reduced(self):
        # rain=1.5, threshold=3.0, factor_roh = 1 - 1.5/3.0 = 0.5 → 50%
        d = self._eval(rain_last=1.5, rain_next_eff=0.0, temp_today=15.0)
        self.assertAlmostEqual(d.factor, 0.5)
        self.assertIn("💧", d.verdict)
        self.assertIn("50", d.verdict)
        self.assertFalse(d.skip)

    def test_hot_day_raises_threshold(self):
        # With heat_sensitivity=0.5, hot_today → hitze_faktor=1.5, T_eff=4.5
        # rain=2.0, R_eff=2.0, factor_roh = 1 - 2.0/4.5 ≈ 0.556 → 55%
        d = self._eval(rain_last=2.0, rain_next_eff=0.0, temp_today=28.0)
        self.assertGreater(d.factor, 0.0)
        self.assertLess(d.factor, 1.0)
        self.assertIn("💧", d.verdict)

    def test_heat_streak_raises_threshold_further(self):
        # 3 hot days streak: hitze_faktor = 1 + 0.5 (hot) + 3*0.25 (streak) = 2.25
        # rain=2.0, T_eff=6.75, factor_roh = 1 - 2/6.75 ≈ 0.704 → 70%
        d = self._eval(rain_last=2.0, rain_next_eff=0.0, temp_today=28.0, past=_hot_days(3))
        self.assertGreater(d.factor, 0.5)
        self.assertLess(d.factor, 1.0)

    def test_enough_rain_even_with_heat_skips(self):
        # rain=6.0, T_eff=4.5 (hot today), factor_roh < 0 → 0
        d = self._eval(rain_last=6.0, rain_next_eff=0.0, temp_today=28.0)
        self.assertAlmostEqual(d.factor, 0.0)
        self.assertTrue(d.skip)

    # --- Dead zones ---

    def test_dead_zone_high_rounds_to_100(self):
        # factor_roh=0.92 → should snap to 1.0
        d = self._eval(rain_last=0.24, rain_next_eff=0.0, temp_today=15.0, threshold=3.0)
        # factor_roh = 1 - 0.24/3.0 = 0.92 → dead zone → 1.0
        self.assertAlmostEqual(d.factor, 1.0)

    def test_dead_zone_low_rounds_to_0(self):
        # factor_roh=0.08 → should snap to 0.0
        d = self._eval(rain_last=2.76, rain_next_eff=0.0, temp_today=15.0, threshold=3.0)
        # factor_roh = 1 - 2.76/3.0 = 0.08 → dead zone → 0.0
        self.assertAlmostEqual(d.factor, 0.0)

    def test_factor_rounds_to_5_percent_steps(self):
        # factor_roh=0.50 → exact 5% step: factor=0.5
        d = self._eval(rain_last=1.5, rain_next_eff=0.0, temp_today=15.0, threshold=3.0)
        self.assertAlmostEqual(d.factor, 0.5)
        # factor_roh=0.667 → nearest 5%: round(0.667*20)/20 = 13/20 = 0.65
        d2 = self._eval(rain_last=1.0, rain_next_eff=0.0, temp_today=15.0, threshold=3.0)
        # factor_roh = 1 - 1/3 ≈ 0.667 → round to 0.65
        self.assertAlmostEqual(d2.factor, 0.65)

    # --- Streak edge cases ---

    def test_streak_breaks_on_cool_day(self):
        past = [(_days_ago(1), 28.0), (_days_ago(2), 15.0), (_days_ago(3), 28.0)]
        d = self._eval(temp_today=28.0, past=past)
        # Streak=1 (only yesterday), cap=3: hitze_faktor = 1 + 0.5 + 1*0.25 = 1.75
        # factor_roh for 0.2+0.1=0.3 rain, T_eff=5.25 → > 0.9 → 1.0
        self.assertAlmostEqual(d.factor, 1.0)

    def test_streak_breaks_on_date_gap(self):
        # day 2 missing (offline) → streak=1
        past = [(_days_ago(1), 28.0), (_days_ago(3), 28.0), (_days_ago(4), 28.0)]
        d = self._eval(temp_today=28.0, past=past)
        # Only day-1 counted, streak=1
        self.assertAlmostEqual(d.factor, 1.0)

    def test_empty_past_no_crash(self):
        d = self._eval(temp_today=28.0, past=[])
        self.assertIsInstance(d.factor, float)
        self.assertIsInstance(d.reasons, list)
        self.assertGreater(len(d.reasons), 0)

    def test_invalid_date_string_breaks_streak(self):
        past = [("not-a-date", 28.0), (_days_ago(1), 28.0)]
        d = self._eval(temp_today=28.0, past=past)
        self.assertIsInstance(d.factor, float)

    # --- Reasons content ---

    def test_reasons_contain_total_mm(self):
        d = self._eval(rain_last=1.5, rain_next_eff=0.5)
        self.assertTrue(any("2.0 mm" in r for r in d.reasons))

    def test_reasons_mention_source(self):
        d = advice.evaluate_watering(
            rain_last_mm=0.5, rain_next_eff_mm=0.1, temp_max_today=15.0,
            past_daily_temps=[], rain_last_source="sensor",
        )
        self.assertTrue(any("lokal gemessen" in r for r in d.reasons))

    def test_reasons_mention_streak_when_present(self):
        d = self._eval(temp_today=28.0, past=_hot_days(3))
        self.assertTrue(any("heiß" in r.lower() and "3" in r for r in d.reasons))

    def test_hot_day_reason_appears(self):
        d = self._eval(temp_today=28.0, past=[])
        self.assertTrue(any("28" in r or "heiß" in r.lower() for r in d.reasons))

    # --- skip / factor / verdict consistency ---

    def test_skip_iff_factor_zero(self):
        for rain in [0.0, 1.5, 3.0, 5.0]:
            d = self._eval(rain_last=rain, rain_next_eff=0.0, temp_today=15.0)
            self.assertEqual(d.skip, d.factor == 0.0, f"rain={rain}: skip≠(factor==0)")

    def test_verdict_matches_factor(self):
        d0 = self._eval(rain_last=5.0, rain_next_eff=0.0, temp_today=15.0)
        self.assertIn("🌧", d0.verdict)
        d_full = self._eval(rain_last=0.0, rain_next_eff=0.0, temp_today=15.0)
        self.assertIn("🚿", d_full.verdict)
        d_partial = self._eval(rain_last=1.5, rain_next_eff=0.0, temp_today=15.0)
        self.assertIn("💧", d_partial.verdict)
        self.assertIn("%", d_partial.verdict)
