import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.event_bus import EventBus
from daemon.core.watering_controller import (
    WateringCycleStarted,
    WateringCycleCompleted,
    WateringCycleFailed,
    WateringCycleStopped
)
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

if __name__ == "__main__":
    unittest.main()
