import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import io
from datetime import timedelta
import json

# src-Ordner zum Python-Path hinzufügen, damit wir 'daemon' importieren können
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from daemon import config, database, weather, mqtt_client

class TestGardenIrrigation(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        """Initialisiert die Testdatenbank und erzwingt den Simulationsmodus."""
        database.init_db()
        mqtt_client.HAS_PAHO = False
        
    def test_01_config_defaults(self):
        """Überprüft, ob Standard-Konfigurationswerte korrekt geladen werden."""
        self.assertEqual(config.RAIN_THRESHOLD_MM, 3.0)
        self.assertEqual(config.SAFETY_TIMEOUT_MINUTES, 30)
        self.assertEqual(config.MQTT_BROKER_PORT, 1883)
        
    def test_02_database_schedule_crud(self):
        """Testet das Anlegen, Modifizieren, Umschalten und Löschen von Zeitplänen."""
        # 1. Anlegen
        sched_id = database.add_schedule("Morgen-Test", "06:15", "everyday", 12, 0, 1)
        self.assertGreater(sched_id, 0)
        
        # 2. Auslesen
        schedules = database.get_schedules()
        target = next((s for s in schedules if s["id"] == sched_id), None)
        self.assertIsNotNone(target)
        self.assertEqual(target["name"], "Morgen-Test")
        self.assertEqual(target["time"], "06:15")
        self.assertEqual(target["duration_minutes"], 12)
        self.assertEqual(target["is_active"], 1)
        
        # 3. Umschalten (Toggle/Update)
        success = database.update_schedule(sched_id, "Morgen-Test", "06:15", "everyday", 12, 0, 0)
        self.assertTrue(success)
        
        schedules_after_update = database.get_schedules()
        target_updated = next((s for s in schedules_after_update if s["id"] == sched_id), None)
        self.assertEqual(target_updated["is_active"], 0)
        
        # 4. Löschen
        deleted = database.delete_schedule(sched_id)
        self.assertTrue(deleted)
        
        schedules_after_delete = database.get_schedules()
        self.assertFalse(any(s["id"] == sched_id for s in schedules_after_delete))
        
    def test_03_watering_history_logging(self):
        """Testet das korrekte Protokollieren von Bewässerungseinsätzen."""
        database.log_watering(15, "manual", "completed", "Testlauf erfolgreich")
        
        history = database.get_recent_history(5)
        self.assertGreater(len(history), 0)
        self.assertEqual(history[0]["duration_minutes"], 15)
        self.assertEqual(history[0]["source"], "manual")
        self.assertEqual(history[0]["status"], "completed")
        self.assertEqual(history[0]["details"], "Testlauf erfolgreich")
        
    def test_04_simulated_mqtt_state(self):
        """Testet die Ventilsteuerung im integrierten Simulationsmodus."""
        # Da wir standardmäßig im Mock-Modus starten, wenn paho nicht da ist, können wir den state abfragen
        mqtt_client.start_client()
        
        # Ventil öffnen
        self.assertTrue(mqtt_client.open_valve())
        self.assertEqual(mqtt_client.get_valve_status()["state"], "ON")
        
        # Ventil schließen
        self.assertTrue(mqtt_client.close_valve())
        self.assertEqual(mqtt_client.get_valve_status()["state"], "OFF")
        
    def test_05_first_to_hit_volume_limit(self):
        """Testet das First-to-Hit-Verhalten bei Erreichen des Volumenlimits."""
        from daemon import scheduler
        import time
        
        # Sicherstellen, dass kein Zyklus läuft
        scheduler.stop_watering()
        
        # Startet eine Bewässerung mit 10 Minuten Zeitlimit und 5 Litern Volumenlimit
        success, msg = scheduler.start_watering(duration_minutes=10, target_volume_liters=5, source="test")
        self.assertTrue(success)
        self.assertEqual(mqtt_client.get_valve_status()["state"], "ON")
        self.assertIsNotNone(scheduler.get_active_cycle())
        
        # Simuliert, dass das Volumenlimit überschritten wird
        mqtt_client.active_cycle_volume = 6.0
        
        # Warte kurz, bis der Volumen-Wächter-Thread (schläft 2 Sek) zuschlägt
        time.sleep(3)
        
        # Prüfen, ob das Ventil geschlossen wurde
        self.assertEqual(mqtt_client.get_valve_status()["state"], "OFF")
        self.assertIsNone(scheduler.get_active_cycle())
        
        # Überprüfen, ob das Protokoll korrekt weggeschrieben wurde
        history = database.get_recent_history(1)
        self.assertGreater(len(history), 0)
        self.assertEqual(history[0]["status"], "completed")
        self.assertIn("Volumenlimit", history[0]["details"])

    @patch("urllib.request.urlopen")
    def test_06_weather_api_parsing_and_skip(self, mock_urlopen):
        """Simuliert eine erfolgreiche Open-Meteo API-Antwort und testet die Skip-Logik."""
        # Mocking der stündlichen Niederschläge (48 Stunden: 24h Vergangenheit + 24h Zukunft)
        # Wir setzen die Niederschläge so, dass die Summe 4.0 mm beträgt (> RAIN_THRESHOLD_MM = 3.0)
        precipitation = [0.0] * 48
        precipitation[10] = 1.5  # In der Vergangenheit
        precipitation[30] = 2.5  # In der Zukunft (Summe = 4.0 mm)
        
        # Erstelle eine Mock-Stundenliste
        from datetime import datetime
        now = datetime.now()
        times = []
        # Die API liefert past_days=1 (gestern) und forecast_days=2 (heute + morgen)
        # Die aktuelle Stunde sollte exakt gematcht werden.
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        start_hour = current_hour - timedelta(hours=24)
        for i in range(48):
            t = start_hour + timedelta(hours=i)
            times.append(t.strftime("%Y-%m-%dT%H:00"))

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "current": {
                "temperature_2m": 22.5,
                "weather_code": 3
            },
            "hourly": {
                "time": times,
                "precipitation": precipitation
            }
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        # Führe Abfrage aus
        rain_last, rain_next, temp, code = weather.get_weather_data(52.5, 13.5)
        
        self.assertEqual(rain_last, 1.5)
        self.assertEqual(rain_next, 2.5)
        self.assertEqual(temp, 22.5)
        self.assertEqual(code, 3)

        # Skip-Logik testen
        should_skip, details = weather.should_skip_watering()
        self.assertTrue(should_skip)
        self.assertIn("Regenschwelle überschritten", details)

    @patch("urllib.request.urlopen")
    def test_07_weather_offline_fallback(self, mock_urlopen):
        """Testet das Offline-first Fallback bei einem API-Ausfall."""
        # urllib.error.URLError simulieren
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Mocked network timeout")

        # Fallback 1: Datenbank enthält bereits einen Wettereintrag
        database.log_weather(1.0, 2.5, 18.0, 1) # Gesamt = 3.5 mm (> 3.0)

        # Abfrage ausführen
        rain_last, rain_next, temp, code = weather.get_weather_data(52.5, 13.5)
        self.assertEqual(rain_last, 1.0)
        self.assertEqual(rain_next, 2.5)
        self.assertEqual(temp, 18.0)
        self.assertEqual(code, 1)

        should_skip, details = weather.should_skip_watering()
        self.assertTrue(should_skip)
        self.assertIn("Regenschwelle überschritten", details)

        # Fallback 2: Datenbank ist leer (wir leeren die Wettertabelle temporär)
        conn = database.get_connection()
        conn.execute("DELETE FROM weather_history")
        conn.commit()
        conn.close()

        # Abfrage ohne DB-Einträge ausführen
        rain_last, rain_next, temp, code = weather.get_weather_data(52.5, 13.5)
        self.assertEqual(rain_last, 0.0)
        self.assertEqual(rain_next, 0.0)
        self.assertEqual(temp, 0.0)
        self.assertEqual(code, 0)

        should_skip, details = weather.should_skip_watering()
        self.assertFalse(should_skip)
        self.assertIn("Regen liegt unter Grenzwert", details)


if __name__ == "__main__":
    unittest.main()


