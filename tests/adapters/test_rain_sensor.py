"""Tests für die Regensensor-Integration (Feature 0016)."""
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import daemon.adapters.database as db
from daemon.adapters.mqtt_client import _global_bus
from daemon.core.event_bus import EventBus
from daemon.core.sensor_events import (
    RainSensorMeasured,
    RainSensorInactivityAlertTriggered,
    RainSensorInactivityAlertResolved,
)
from daemon.core.watering_events import WateringCycleInterrupted
from daemon.core.watering_controller import WateringController


def _make_temp_db() -> Path:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return Path(f.name)


# ---------------------------------------------------------------------------
# 1. MQTT Payload-Parsing
# ---------------------------------------------------------------------------

class TestRainSensorPayloadParsing(unittest.TestCase):
    """Prüft das Parsen des echten RANWIE01-Payloads (AQS/<id>/stat).

    Format laut Doku: {"uptime","temperature"(1/10 °C),"rainlevel","battery"(mAs verbraucht),"raintotal"}
    rainlevel/raintotal in 0,5-mm-Einheiten (Wert × 0,5 = mm).
    """

    def _adapter(self):
        from daemon.adapters.mqtt_client import PahoMqttAdapter
        bus = EventBus()
        adapter = PahoMqttAdapter.__new__(PahoMqttAdapter)
        adapter.event_bus = bus
        captured = []
        bus.subscribe(RainSensorMeasured, captured.append)
        return adapter, captured

    def test_real_payload_maps_fields_and_units(self):
        adapter, captured = self._adapter()
        with patch("daemon.adapters.mqtt_client.config.RAIN_SENSOR_MM_PER_TICK", 0.5), \
             patch("daemon.adapters.mqtt_client.config.RAIN_SENSOR_BATTERY_CAPACITY_MAH", 1200.0):
            adapter._handle_rain_sensor({
                "uptime": "1", "temperature": "200",   # 20,0 °C
                "rainlevel": "2", "raintotal": "10",   # × 0,5 → 1,0 mm / 5,0 mm
                "battery": "0",                         # nichts verbraucht → voll
            })
        self.assertEqual(len(captured), 1)
        ev = captured[0]
        self.assertAlmostEqual(ev.rainlevel_mm, 1.0)
        self.assertAlmostEqual(ev.raintotal_mm, 5.0)
        self.assertAlmostEqual(ev.temperature_c, 20.0)
        self.assertEqual(ev.battery_pct, 100)

    def test_is_raining_on_single_tick(self):
        adapter, captured = self._adapter()
        with patch("daemon.adapters.mqtt_client.config.RAIN_SENSOR_THRESHOLD_MM", 0.1), \
             patch("daemon.adapters.mqtt_client.config.RAIN_SENSOR_MM_PER_TICK", 0.5):
            adapter._handle_rain_sensor({"rainlevel": "1", "raintotal": "5", "temperature": "180", "battery": "0"})
        self.assertTrue(captured[0].is_raining)          # 1 × 0,5 = 0,5 mm ≥ 0,1

    def test_zero_message_not_raining(self):
        adapter, captured = self._adapter()
        with patch("daemon.adapters.mqtt_client.config.RAIN_SENSOR_THRESHOLD_MM", 0.1), \
             patch("daemon.adapters.mqtt_client.config.RAIN_SENSOR_MM_PER_TICK", 0.5):
            adapter._handle_rain_sensor({"rainlevel": "0", "raintotal": "5", "temperature": "200", "battery": "0"})
        self.assertFalse(captured[0].is_raining)         # Null-Heartbeat → kein Regen

    def test_battery_consumed_mas_to_percent(self):
        adapter, captured = self._adapter()
        # 1200 mAh = 4.320.000 mAs; halb verbraucht = 2.160.000 → 50 %
        with patch("daemon.adapters.mqtt_client.config.RAIN_SENSOR_BATTERY_CAPACITY_MAH", 1200.0):
            adapter._handle_rain_sensor({"rainlevel": "0", "raintotal": "0", "temperature": "200", "battery": "2160000"})
        self.assertEqual(captured[0].battery_pct, 50)


class TestRainTopicMatching(unittest.TestCase):
    """Wildcard-Topic-Matching, damit AQS/<id>/stat geräteunabhängig erkannt wird."""

    def test_wildcard_and_exact(self):
        from daemon.adapters.mqtt_client import _topic_matches
        self.assertTrue(_topic_matches("AQS/+/stat", "AQS/1d00010f/stat"))
        self.assertTrue(_topic_matches("sensor/rain", "sensor/rain"))
        self.assertFalse(_topic_matches("AQS/+/stat", "AQS/1d00010f/cmd"))
        self.assertFalse(_topic_matches("AQS/+/stat", "zigbee2mqtt/garden_valve"))


# ---------------------------------------------------------------------------
# 2. Watering Controller — Guss-Unterbrechung
# ---------------------------------------------------------------------------

class TestWateringControllerInterrupt(unittest.TestCase):
    """Prüft, dass RainSensorMeasured mit is_raining=True alle Zyklen unterbricht."""

    def _make_ctrl(self, bus: EventBus):
        publish_mock = MagicMock(return_value=True)
        ctrl = WateringController(bus, publish_mock)
        return ctrl, publish_mock

    def test_interrupt_stops_active_cycle_and_publishes_event(self):
        bus = EventBus()
        ctrl, publish_mock = self._make_ctrl(bus)

        ok, _ = ctrl.start_watering(5, 20, "manual", mqtt_name="garten")
        self.assertTrue(ok)

        interrupted = []
        bus.subscribe(WateringCycleInterrupted, interrupted.append)

        bus.publish(RainSensorMeasured(1.4, 18.2, 21.8, 95, is_raining=True))

        self.assertEqual(len(interrupted), 1)
        ev = interrupted[0]
        self.assertEqual(ev.mqtt_name, "garten")
        self.assertAlmostEqual(ev.rain_mm, 1.4)
        self.assertEqual(ev.source, "manual")

    def test_interrupt_not_fires_when_not_raining(self):
        bus = EventBus()
        ctrl, _ = self._make_ctrl(bus)

        ok, _ = ctrl.start_watering(5, 20, "manual", mqtt_name="garten")
        self.assertTrue(ok)

        interrupted = []
        bus.subscribe(WateringCycleInterrupted, interrupted.append)

        bus.publish(RainSensorMeasured(0.0, 5.0, 20.0, 90, is_raining=False))

        self.assertEqual(len(interrupted), 0)

    def test_interrupt_stops_multiple_parallel_cycles(self):
        bus = EventBus()
        ctrl, _ = self._make_ctrl(bus)

        ctrl.start_watering(5, 20, "schedule", mqtt_name="valve_1")
        ctrl.start_watering(5, 20, "schedule", mqtt_name="valve_2")

        interrupted = []
        bus.subscribe(WateringCycleInterrupted, interrupted.append)

        bus.publish(RainSensorMeasured(0.8, 10.0, 19.0, 85, is_raining=True))

        self.assertEqual(len(interrupted), 2)
        names = {ev.mqtt_name for ev in interrupted}
        self.assertIn("valve_1", names)
        self.assertIn("valve_2", names)

    def test_interrupt_publishes_interrupted_not_stopped(self):
        """Guss-Unterbrechung muss WateringCycleInterrupted (nicht WateringCycleStopped) senden."""
        from daemon.core.watering_events import WateringCycleStopped
        bus = EventBus()
        ctrl, _ = self._make_ctrl(bus)
        ctrl.start_watering(5, 20, "manual", mqtt_name="garten")

        stopped = []
        interrupted = []
        bus.subscribe(WateringCycleStopped, stopped.append)
        bus.subscribe(WateringCycleInterrupted, interrupted.append)

        bus.publish(RainSensorMeasured(1.0, 5.0, 20.0, 80, is_raining=True))

        self.assertEqual(len(stopped), 0)
        self.assertEqual(len(interrupted), 1)

    def test_no_active_cycle_interrupt_is_noop(self):
        bus = EventBus()
        ctrl, publish_mock = self._make_ctrl(bus)

        interrupted = []
        bus.subscribe(WateringCycleInterrupted, interrupted.append)

        bus.publish(RainSensorMeasured(2.0, 20.0, 18.0, 70, is_raining=True))

        self.assertEqual(len(interrupted), 0)
        publish_mock.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Datenbank — rain_measurements
# ---------------------------------------------------------------------------

class TestRainMeasurementsDatabase(unittest.TestCase):

    def setUp(self):
        self.db_path = _make_temp_db()
        self._patcher = patch.object(db, "DB_PATH", self.db_path)
        self._patcher.start()
        db.init_db()

    def tearDown(self):
        self._patcher.stop()
        import gc
        gc.collect()
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_log_and_retrieve_measurement(self):
        db.log_rain_measurement(1.4, 18.2, 21.8, 95)
        last = db.get_last_rain_measurement()
        self.assertIsNotNone(last)
        self.assertAlmostEqual(last["rainlevel_mm"], 1.4)
        self.assertAlmostEqual(last["raintotal_mm"], 18.2)
        self.assertAlmostEqual(last["temperature_c"], 21.8)
        self.assertEqual(last["battery_pct"], 95)

    def test_get_last_returns_none_when_empty(self):
        self.assertIsNone(db.get_last_rain_measurement())

    def test_get_rain_sum_last_24h(self):
        db.log_rain_measurement(1.0, 10.0, 20.0, 90)
        db.log_rain_measurement(2.5, 12.5, 21.0, 88)
        total = db.get_rain_sum_last_24h()
        self.assertAlmostEqual(total, 3.5)

    def test_get_rain_sum_excludes_old_entries(self):
        old_ts = (datetime.now() - timedelta(hours=25)).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO rain_measurements (timestamp, rainlevel_mm, raintotal_mm, temperature_c, battery_pct)"
            " VALUES (?, 5.0, 50.0, 20.0, 80)",
            (old_ts,)
        )
        conn.commit()
        conn.close()
        db.log_rain_measurement(1.0, 6.0, 20.0, 80)
        total = db.get_rain_sum_last_24h()
        self.assertAlmostEqual(total, 1.0)

    def test_get_rain_stats_last_24h(self):
        db.log_rain_measurement(1.0, 10.0, 20.0, 90)
        db.log_rain_measurement(2.0, 12.0, 25.0, 88)
        stats = db.get_rain_stats_last_24h()
        self.assertAlmostEqual(stats["rain_sum"], 3.0)
        self.assertAlmostEqual(stats["rain_max"], 2.0)
        self.assertAlmostEqual(stats["temp_avg"], 22.5)
        self.assertAlmostEqual(stats["temp_max"], 25.0)

    def test_get_rain_stats_returns_empty_when_no_data(self):
        stats = db.get_rain_stats_last_24h()
        self.assertEqual(stats, {})


# ---------------------------------------------------------------------------
# 4. DatabaseLoggerAdapter — Regensensor-Logging
# ---------------------------------------------------------------------------

class TestDatabaseAdapterRainSensor(unittest.TestCase):

    @patch("daemon.adapters.database.log_rain_measurement")
    def test_rain_sensor_event_logged(self, mock_log):
        from daemon.adapters.database_adapter import DatabaseLoggerAdapter
        bus = EventBus()
        DatabaseLoggerAdapter(bus)

        bus.publish(RainSensorMeasured(1.4, 18.2, 21.8, 95, is_raining=True))

        mock_log.assert_called_once_with(1.4, 18.2, 21.8, 95)

    @patch("daemon.adapters.database.log_watering")
    def test_watering_interrupted_logged_as_interrupted(self, mock_log):
        from daemon.adapters.database_adapter import DatabaseLoggerAdapter
        bus = EventBus()
        DatabaseLoggerAdapter(bus)

        bus.publish(WateringCycleInterrupted(
            duration_run=4, volume_run=2.1, source="manual",
            details="Regen erkannt · 1.4 mm erkannt", mqtt_name="garten", rain_mm=1.4
        ))

        mock_log.assert_called_once_with(
            4, "manual", "interrupted",
            "Regen erkannt · 1.4 mm erkannt",
            watered_volume=2.1
        )


# ---------------------------------------------------------------------------
# 5. Wetter-Dienst — Sensor als primäre Quelle
# ---------------------------------------------------------------------------

class TestWeatherSensorPriority(unittest.TestCase):
    """Prüft, dass weather.py den Regensensor als primäre Quelle nutzt."""

    def _run_get_weather_data(self, sensor_last, sensor_rain_sum):
        """Ruft get_weather_data() mit gemockten Abhängigkeiten auf."""
        import daemon.adapters.weather as weather_mod

        now = datetime.now()
        mock_response_data = {
            "current": {"temperature_2m": 20.0, "precipitation": 0.0, "weather_code": 0},
            "daily": {
                "time": [now.strftime("%Y-%m-%d")],
                "temperature_2m_max": [25.0],
                "temperature_2m_min": [15.0],
            },
            "hourly": {
                "time": [(now - timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(48, -1, -1)],
                "precipitation": [0.0] * 49,
                "precipitation_probability": [0] * 49,
                "temperature_2m": [20.0] * 49,
                "weather_code": [0] * 49,
            }
        }

        class FakeResponse:
            def read(self):
                import json
                return json.dumps(mock_response_data).encode()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        with patch("daemon.adapters.weather.database.get_last_rain_measurement", return_value=sensor_last), \
             patch("daemon.adapters.weather.database.get_rain_sum_last_24h", return_value=sensor_rain_sum), \
             patch("daemon.adapters.weather._fetch_measured_rain_last", return_value=3.0), \
             patch("daemon.adapters.weather._global_bus") as mock_bus, \
             patch("urllib.request.urlopen", return_value=FakeResponse()):
            result = weather_mod.get_weather_data(52.0, 13.0)
        return result, mock_bus

    def test_sensor_used_when_fresh(self):
        fresh_ts = (datetime.now() - timedelta(hours=1)).isoformat()
        sensor_last = {"timestamp": fresh_ts}
        result, mock_bus = self._run_get_weather_data(sensor_last, 2.5)
        self.assertIsNotNone(result)
        rain_last, _, _, _, _, _, _, rain_source = result
        self.assertEqual(rain_source, "sensor")
        self.assertAlmostEqual(rain_last, 2.5)

    def test_era5_fallback_when_sensor_stale(self):
        old_ts = (datetime.now() - timedelta(hours=20)).isoformat()
        sensor_last = {"timestamp": old_ts}
        with patch("daemon.adapters.weather.config.RAIN_SENSOR_OFFLINE_HOURS", 18.0):
            result, mock_bus = self._run_get_weather_data(sensor_last, 0.0)
        self.assertIsNotNone(result)
        rain_last, _, _, _, _, _, _, rain_source = result
        self.assertEqual(rain_source, "measured")
        self.assertAlmostEqual(rain_last, 3.0)

    def test_era5_fallback_when_no_sensor_data(self):
        result, _ = self._run_get_weather_data(None, 0.0)
        self.assertIsNotNone(result)
        _, _, _, _, _, _, _, rain_source = result
        self.assertEqual(rain_source, "measured")


# ---------------------------------------------------------------------------
# 6. Watchdog — Regensensor-Inaktivität
# ---------------------------------------------------------------------------

class TestWatchdogRainSensor(unittest.TestCase):

    def setUp(self):
        self.db_path = _make_temp_db()
        self._patcher = patch.object(db, "DB_PATH", self.db_path)
        self._patcher.start()
        db.init_db()

    def tearDown(self):
        self._patcher.stop()
        import gc
        gc.collect()
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_alert_triggered_when_sensor_silent_too_long(self):
        from daemon.adapters import watchdog
        old_ts = (datetime.now() - timedelta(hours=20)).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO rain_measurements (timestamp, rainlevel_mm, raintotal_mm, temperature_c, battery_pct)"
            " VALUES (?, 1.0, 10.0, 20.0, 80)",
            (old_ts,)
        )
        conn.commit()
        conn.close()

        triggered = []
        _global_bus.subscribe(RainSensorInactivityAlertTriggered, triggered.append)
        try:
            with patch("daemon.adapters.watchdog.config.WATCHDOG_ENABLED", True), \
                 patch("daemon.adapters.watchdog.config.RAIN_SENSOR_OFFLINE_HOURS", 18.0):
                watchdog.run_watchdog_check()
        finally:
            _global_bus.unsubscribe(RainSensorInactivityAlertTriggered, triggered.append)

        self.assertEqual(len(triggered), 1)
        self.assertGreater(triggered[0].hours_silent, 18.0)
        self.assertEqual(db.get_metadata("watchdog_alert_active_rain_sensor"), "1")

    def test_no_duplicate_alert_when_flag_already_set(self):
        from daemon.adapters import watchdog
        old_ts = (datetime.now() - timedelta(hours=20)).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO rain_measurements (timestamp, rainlevel_mm, raintotal_mm, temperature_c, battery_pct)"
            " VALUES (?, 1.0, 10.0, 20.0, 80)",
            (old_ts,)
        )
        conn.commit()
        conn.close()
        db.set_metadata("watchdog_alert_active_rain_sensor", "1")

        triggered = []
        _global_bus.subscribe(RainSensorInactivityAlertTriggered, triggered.append)
        try:
            with patch("daemon.adapters.watchdog.config.WATCHDOG_ENABLED", True), \
                 patch("daemon.adapters.watchdog.config.RAIN_SENSOR_OFFLINE_HOURS", 18.0):
                watchdog.run_watchdog_check()
        finally:
            _global_bus.unsubscribe(RainSensorInactivityAlertTriggered, triggered.append)

        self.assertEqual(len(triggered), 0)

    def test_resolution_via_watchdog_check(self):
        from daemon.adapters import watchdog
        fresh_ts = (datetime.now() - timedelta(hours=1)).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO rain_measurements (timestamp, rainlevel_mm, raintotal_mm, temperature_c, battery_pct)"
            " VALUES (?, 0.5, 5.0, 20.0, 85)",
            (fresh_ts,)
        )
        conn.commit()
        conn.close()
        db.set_metadata("watchdog_alert_active_rain_sensor", "1")

        resolved = []
        _global_bus.subscribe(RainSensorInactivityAlertResolved, resolved.append)
        try:
            with patch("daemon.adapters.watchdog.config.WATCHDOG_ENABLED", True), \
                 patch("daemon.adapters.watchdog.config.RAIN_SENSOR_OFFLINE_HOURS", 18.0):
                watchdog.run_watchdog_check()
        finally:
            _global_bus.unsubscribe(RainSensorInactivityAlertResolved, resolved.append)

        self.assertEqual(len(resolved), 1)
        self.assertNotEqual(db.get_metadata("watchdog_alert_active_rain_sensor"), "1")

    def test_immediate_resolution_on_measurement(self):
        from daemon.adapters import watchdog
        db.set_metadata("watchdog_alert_active_rain_sensor", "1")
        watchdog.initialize()

        resolved = []
        _global_bus.subscribe(RainSensorInactivityAlertResolved, resolved.append)
        try:
            _global_bus.publish(RainSensorMeasured(1.0, 10.0, 20.0, 80, is_raining=True))
        finally:
            _global_bus.unsubscribe(RainSensorInactivityAlertResolved, resolved.append)

        self.assertEqual(len(resolved), 1)
        self.assertNotEqual(db.get_metadata("watchdog_alert_active_rain_sensor"), "1")

    def test_no_alert_when_no_sensor_data_in_db(self):
        from daemon.adapters import watchdog
        triggered = []
        _global_bus.subscribe(RainSensorInactivityAlertTriggered, triggered.append)
        try:
            with patch("daemon.adapters.watchdog.config.WATCHDOG_ENABLED", True):
                watchdog.run_watchdog_check()
        finally:
            _global_bus.unsubscribe(RainSensorInactivityAlertTriggered, triggered.append)
        self.assertEqual(len(triggered), 0)


# ---------------------------------------------------------------------------
# 7. Telegram-UI — Flankensteuerung
# ---------------------------------------------------------------------------

class TestTelegramRainNotifications(unittest.TestCase):
    """Die früheren Flankentests der UI entfielen mit ADR 0043: die Zustandslogik liegt
    jetzt im Kern (tests/core/test_rain_event.py), die Persistenz im Adapter
    (tests/adapters/test_rain_event_adapter.py), die Texte in
    tests/ui/test_rain_event_messages.py."""

    def test_watering_interrupted_notification(self):
        from daemon.ui.telegram_ui import _on_watering_interrupted
        with patch("daemon.ui.telegram_ui.database") as mock_db, \
             patch("daemon.ui.telegram_ui.telegram_client") as mock_tc:
            mock_db.get_valve_by_mqtt_name.return_value = {"wish_name": "Terrasse"}
            _on_watering_interrupted(WateringCycleInterrupted(
                duration_run=4, volume_run=2.1, source="manual",
                details="Regen erkannt · 0.6 mm erkannt",
                mqtt_name="terrasse", rain_mm=0.6,
            ))
            msg = mock_tc.broadcast_notification.call_args[0][0]
            self.assertIn("Regen übernimmt", msg)
            self.assertIn("Terrasse", msg)
            self.assertIn("4 Min", msg)
            self.assertIn("2.1 l", msg)
            self.assertIn("0.6 mm", msg)


if __name__ == "__main__":
    unittest.main()
