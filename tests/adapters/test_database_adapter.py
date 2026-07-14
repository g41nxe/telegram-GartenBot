import sys
import unittest
from pathlib import Path
from unittest.mock import patch, call

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.event_bus import EventBus
from daemon.core.watering_controller import (
    WateringCycleStarted,
    WateringCycleCompleted,
    WateringCycleFailed,
    WateringCycleStopped
)
from daemon.core.scheduler_events import WeatherDataFetched
from daemon.core.nebel_events import NebelIntervalStarted, NebelIntervalEnded
from daemon.adapters.database_adapter import DatabaseLoggerAdapter

class TestDatabaseAdapter(unittest.TestCase):
    @patch("daemon.adapters.database.log_watering")
    def test_routing_events_to_database(self, mock_log_watering):
        """Verifies that the DatabaseLoggerAdapter intercepts events and logs them in SQLite."""
        bus = EventBus()
        adapter = DatabaseLoggerAdapter(bus)
        
        # 1. Test started event routing
        bus.publish(WateringCycleStarted(duration=15, target_volume=40, source="schedule"))
        mock_log_watering.assert_called_once_with(
            15, "schedule", "completed", "Bewässerung gestartet (Zeitlimit: 15 Min | Volumenlimit: 40 Liter)."
        )
        
        # Reset mock
        mock_log_watering.reset_mock()
        
        # 2. Test completed event routing
        bus.publish(WateringCycleCompleted(duration_run=12, volume_run=40.0, source="schedule", details="Target reached"))
        mock_log_watering.assert_called_once_with(
            12, "schedule", "completed", "Target reached", watered_volume=40.0
        )
        
        # Reset mock
        mock_log_watering.reset_mock()
        
        # 3. Test failed event routing
        bus.publish(WateringCycleFailed(duration_run=15, volume_run=3.5, source="manual", details="Emergency shutdown"))
        mock_log_watering.assert_called_once_with(
            15, "manual", "failed", "Emergency shutdown", watered_volume=3.5
        )

        # Reset mock
        mock_log_watering.reset_mock()
        
        # 4. Test stopped event routing
        bus.publish(WateringCycleStopped(duration_run=5, volume_run=10.0, source="manual", details="Stopped by user"))
        mock_log_watering.assert_called_once_with(
            5, "manual", "stopped", "Stopped by user", watered_volume=10.0
        )


class TestNebelIntervalLogging(unittest.TestCase):
    """Nebel-Intervall wird pro Fenster protokolliert (Feature 0032)."""

    @patch("daemon.adapters.database.log_watering")
    def test_nebel_started_logged_once(self, mock_log):
        bus = EventBus()
        DatabaseLoggerAdapter(bus)
        bus.publish(NebelIntervalStarted("terrace_mist", "nebel", "2026-06-27T18:00:00"))
        mock_log.assert_called_once_with(0, "nebel", "started", "Nebel-Intervall gestartet.")

    @patch("daemon.adapters.database.log_watering")
    def test_nebel_ended_logged_once(self, mock_log):
        bus = EventBus()
        DatabaseLoggerAdapter(bus)
        bus.publish(NebelIntervalEnded("terrace_mist", "nebel", 45, 9, "Fensterende erreicht: 9 Nebelstöße in 45 Min."))
        mock_log.assert_called_once_with(45, "nebel", "completed", "Fensterende erreicht: 9 Nebelstöße in 45 Min.")


class TestWeatherDataFetchedForwarding(unittest.TestCase):
    """Stellt sicher, dass WeatherDataFetched-Ereignisse die neuen Felder korrekt weiterleiten."""

    @patch("daemon.adapters.database.log_weather")
    def test_new_fields_forwarded_to_log_weather(self, mock_log_weather):
        bus = EventBus()
        DatabaseLoggerAdapter(bus)

        bus.publish(WeatherDataFetched(
            rain_last_24h=2.5,
            rain_next_24h=1.0,
            current_temp=19.0,
            weather_code=61,
            temp_min=15.0,
            temp_max=23.0,
            rain_prob=70,
            current_precipitation=0.3,
            hourly_forecast_json='{"times":["2026-06-13T14:00"]}',
            rain_last_source="measured",
        ))

        mock_log_weather.assert_called_once_with(
            2.5, 1.0, 19.0, 61, 15.0, 23.0, 70,
            current_precipitation_mm=0.3,
            hourly_forecast_json='{"times":["2026-06-13T14:00"]}',
            rain_last_source="measured",
        )

    @patch("daemon.adapters.database.log_weather")
    def test_defaults_used_when_new_fields_omitted(self, mock_log_weather):
        """Ereignisse ohne neue Felder (Altcode-Erzeuger) müssen weiterhin funktionieren."""
        bus = EventBus()
        DatabaseLoggerAdapter(bus)

        bus.publish(WeatherDataFetched(
            rain_last_24h=0.0,
            rain_next_24h=0.0,
            current_temp=20.0,
            weather_code=0,
            temp_min=15.0,
            temp_max=25.0,
            rain_prob=0,
        ))

        _, kwargs = mock_log_weather.call_args
        self.assertEqual(kwargs.get("current_precipitation_mm"), 0.0)
        self.assertEqual(kwargs.get("hourly_forecast_json"), "")
        self.assertEqual(kwargs.get("rain_last_source"), "measured")


if __name__ == "__main__":
    unittest.main()


class TestTimedPhotoDeliveryFailed(unittest.TestCase):
    """Ein gescheiterter Versand oeffnet den Aufnahme-Zeitpunkt wieder (ADR 0040)."""

    def test_fehlgeschlagene_zustellung_nimmt_den_vermerk_zurueck(self):
        from datetime import datetime
        from daemon.adapters import database
        from daemon.adapters.database_adapter import DatabaseLoggerAdapter
        from daemon.core.camera_events import TimedPhotoDeliveryFailed

        import tempfile, os
        temp_db = tempfile.NamedTemporaryFile(delete=False)
        temp_db.close()
        orig = database.DB_PATH
        database.DB_PATH = temp_db.name
        try:
            database.init_db()
            bus = EventBus()
            DatabaseLoggerAdapter(bus)

            mac = "AA:BB:CC:DD:EE:FF"
            target = datetime(2026, 7, 14, 8, 0)
            database.set_metadata(f"last_delivered_target:{mac}", target.isoformat())

            bus.publish(TimedPhotoDeliveryFailed(mac, target))

            anker = database.get_metadata(f"last_delivered_target:{mac}")
            assert anker, \
                "Der Anker darf nicht zerstoert werden — sonst wird die Kamera-Ueberwachung blind"
            assert datetime.fromisoformat(anker) < target, \
                "Der Anker muss VOR dem Zeitpunkt liegen, damit dieser wieder offen ist"
        finally:
            database.DB_PATH = orig
            os.unlink(temp_db.name)
