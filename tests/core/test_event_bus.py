import sys
import unittest
from pathlib import Path

# Add src/ to python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon.core.event_bus import EventBus, Event

class DummyEvent(Event):
    def __init__(self, data: str):
        self.data = data

class OtherEvent(Event):
    pass

class TestEventBus(unittest.TestCase):
    def test_subscribe_and_publish(self):
        """Verifies that a subscribed listener receives published events of that type."""
        bus = EventBus()
        received_data = []

        def listener(event: DummyEvent):
            received_data.append(event.data)

        bus.subscribe(DummyEvent, listener)
        
        # Publish matching event
        bus.publish(DummyEvent("test-payload"))
        self.assertEqual(received_data, ["test-payload"])

    def test_multiple_listeners(self):
        """Verifies that multiple listeners receive the same published event."""
        bus = EventBus()
        calls = []

        bus.subscribe(DummyEvent, lambda e: calls.append("l1"))
        bus.subscribe(DummyEvent, lambda e: calls.append("l2"))

        bus.publish(DummyEvent("foo"))
        self.assertIn("l1", calls)
        self.assertIn("l2", calls)
        self.assertEqual(len(calls), 2)

    def test_isolation_between_event_types(self):
        """Verifies that subscribers only receive events of the type they subscribed to."""
        bus = EventBus()
        dummy_calls = 0
        other_calls = 0

        bus.subscribe(DummyEvent, lambda e: setattr(sys.modules[__name__], 'dummy_calls', dummy_calls + 1)) # Wait, let's use a mutable list for simplicity
        
        received_dummy = []
        received_other = []

        bus.subscribe(DummyEvent, lambda e: received_dummy.append(e))
        bus.subscribe(OtherEvent, lambda e: received_other.append(e))

        bus.publish(OtherEvent())
        
        self.assertEqual(len(received_dummy), 0)
        self.assertEqual(len(received_other), 1)

if __name__ == "__main__":
    unittest.main()
