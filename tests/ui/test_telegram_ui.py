import sys
import time
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.weather_codes import get_wmo_description
from daemon.ui.telegram_ui import (
    wizard_states,
    manual_states,
    _state_get,
    _state_set,
    _state_del,
    _state_touch,
    _cleanup_expired_states,
    WIZARD_TTL_SECONDS,
)


class TestWeatherCodes(unittest.TestCase):

    def test_known_code_returns_description(self):
        self.assertIn("Sonnig", get_wmo_description(0))

    def test_rain_code_returns_description(self):
        self.assertIn("Regen", get_wmo_description(61))

    def test_unknown_code_returns_fallback(self):
        result = get_wmo_description(9999)
        self.assertIn("Unbekannt", result)

    def test_boundary_code_45(self):
        self.assertIn("Nebel", get_wmo_description(45))


class TestWizardStateMachine(unittest.TestCase):

    def setUp(self):
        wizard_states.clear()
        manual_states.clear()

    def tearDown(self):
        wizard_states.clear()
        manual_states.clear()

    def test_state_set_stores_value_with_last_active(self):
        _state_set(wizard_states, 42, {"step": 1})
        state = _state_get(wizard_states, 42)
        self.assertIsNotNone(state)
        self.assertEqual(state["step"], 1)
        self.assertIn("last_active", state)
        self.assertIsInstance(state["last_active"], datetime)

    def test_state_get_returns_none_for_missing_key(self):
        self.assertIsNone(_state_get(wizard_states, 999))

    def test_state_del_removes_entry(self):
        _state_set(wizard_states, 42, {"step": 1})
        _state_del(wizard_states, 42)
        self.assertIsNone(_state_get(wizard_states, 42))

    def test_state_del_noop_on_missing_key(self):
        # Must not raise
        _state_del(wizard_states, 9999)

    def test_state_touch_updates_last_active(self):
        _state_set(wizard_states, 42, {"step": 1})
        original_time = _state_get(wizard_states, 42)["last_active"]
        time.sleep(0.01)
        _state_touch(wizard_states, 42)
        updated_time = _state_get(wizard_states, 42)["last_active"]
        self.assertGreater(updated_time, original_time)


class TestWizardTTLCleanup(unittest.TestCase):

    def setUp(self):
        wizard_states.clear()
        manual_states.clear()

    def tearDown(self):
        wizard_states.clear()
        manual_states.clear()

    def test_cleanup_removes_expired_entries(self):
        past = datetime.now() - timedelta(seconds=WIZARD_TTL_SECONDS + 10)
        wizard_states[100] = {"step": 1, "last_active": past}
        _cleanup_expired_states()
        self.assertNotIn(100, wizard_states)

    def test_cleanup_preserves_fresh_entries(self):
        _state_set(wizard_states, 200, {"step": 2})
        _cleanup_expired_states()
        self.assertIn(200, wizard_states)

    def test_cleanup_removes_expired_manual_states(self):
        past = datetime.now() - timedelta(seconds=WIZARD_TTL_SECONDS + 1)
        manual_states[300] = {"step": "man_custom_duration", "last_active": past}
        _cleanup_expired_states()
        self.assertNotIn(300, manual_states)

    def test_cleanup_is_thread_safe(self):
        """Concurrent cleanup and state mutations must not raise."""
        errors = []

        def writer():
            for i in range(50):
                try:
                    _state_set(wizard_states, i % 5, {"step": i})
                    _state_del(wizard_states, i % 5)
                except Exception as e:
                    errors.append(e)

        def cleaner():
            for _ in range(50):
                try:
                    _cleanup_expired_states()
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=cleaner)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread-safety errors: {errors}")


if __name__ == "__main__":
    unittest.main()
