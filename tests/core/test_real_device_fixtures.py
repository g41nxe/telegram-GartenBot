"""Regressionstests gegen echte Sonoff-SWV-ZFE-Payloads (siehe tests/fixtures/README.md).

Treibt reale, mitgeschnittene Geräte-Nachrichten durch den echten Adapter-Parser
(`PahoMqttAdapter._on_message`, läuft auch ohne installiertes paho-mqtt) in die
Guss-Steuerung. Damit ist die Volumen-Logik gegen reale Daten abgesichert, nicht nur
gegen handgebaute Minimal-Dicts. Hintergrund: ADR 0007."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from daemon import config
from daemon.core.event_bus import EventBus
from daemon.adapters.mqtt_client import PahoMqttAdapter
from daemon.core.watering_controller import WateringController, WateringCycleCompleted

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
VALVE_TOPIC = config.MQTT_VALVE_TOPIC
VALVE_NAME = VALVE_TOPIC.split("/")[-1]


def _load(name):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


class _Msg:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload


class TestRealDeviceFixtures(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.adapter = PahoMqttAdapter(self.bus)  # _on_message funktioniert ohne paho
        self.published = []
        self.controller = WateringController(
            self.bus, lambda topic, payload: (self.published.append((topic, payload)) or True)
        )

    def _feed(self, payload: dict):
        self.adapter._on_message(None, None, _Msg(VALVE_TOPIC, json.dumps(payload).encode()))

    def test_real_single_guss_volume_tracks_actual_amount(self):
        """Ohne Volumenlimit folgt das Guss-Volumen der realen actual_irrigation_amount-Sequenz (~40 L)."""
        ok, _ = self.controller.start_watering(
            duration_minutes=10, target_volume_liters=0, source="manual",
            mqtt_name=VALVE_NAME, valve_topic=VALVE_TOPIC,
        )
        self.assertTrue(ok)
        for msg in _load("swv_zfe_single_guss.jsonl"):
            self._feed(msg)
        # Endwert der Session; der eingefrorene real_time_irrigation_volume darf keine Rolle spielen.
        self.assertAlmostEqual(self.controller.get_active_volume(VALVE_NAME), 40.0, places=1)

    def test_real_single_guss_limit_trips_near_target(self):
        """Volumenlimit greift nahe am Ziel (nicht erst beim Session-Endwert 40)."""
        completed = []
        self.bus.subscribe(WateringCycleCompleted, lambda e: completed.append(e))
        ok, _ = self.controller.start_watering(
            duration_minutes=10, target_volume_liters=5, source="manual",
            mqtt_name=VALVE_NAME, valve_topic=VALVE_TOPIC,
        )
        self.assertTrue(ok)
        for msg in _load("swv_zfe_single_guss.jsonl"):
            self._feed(msg)
        self.assertIsNone(self.controller.get_active_cycle(VALVE_NAME))
        self.assertEqual(len(completed), 1)
        self.assertGreaterEqual(completed[0].volume_run, 5.0)
        self.assertLess(completed[0].volume_run, 10.0)
        self.assertIn("Volumenlimit", completed[0].details)

    def test_real_lagged_end_does_not_poison_new_guss(self):
        """Der reale verspätete 'end'-Report (actual=40) darf einen frischen Guss nicht sofort beenden."""
        msgs = _load("swv_zfe_back_to_back.jsonl")
        lagged_end = next(
            m for m in msgs
            if m.get("state") == "ON"
            and (m.get("irrigation_schedule_status") or {}).get("schedule_status") == "end"
            and (m.get("irrigation_schedule_status") or {}).get("actual_irrigation_amount") == 40
        )
        ok, _ = self.controller.start_watering(
            duration_minutes=1, target_volume_liters=10, source="schedule",
            mqtt_name=VALVE_NAME, valve_topic=VALVE_TOPIC,
        )
        self.assertTrue(ok)
        self._feed(lagged_end)
        self.assertIsNotNone(
            self.controller.get_active_cycle(VALVE_NAME),
            "Verspäteter Vorsession-Wert darf den Folge-Guss nicht sofort beenden",
        )
        self.assertAlmostEqual(self.controller.get_active_volume(VALVE_NAME), 0.0, places=2)


if __name__ == "__main__":
    unittest.main()
