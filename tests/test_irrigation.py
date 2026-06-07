import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import io
from datetime import timedelta
import json

# src-Ordner zum Python-Path hinzufügen, damit wir 'daemon' importieren können
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from daemon import config
from daemon.adapters import database, weather, mqtt_client

class TestGardenIrrigation(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        """Initialisiert die Testdatenbank und erzwingt den Simulationsmodus."""
        database.init_db()
        mqtt_client.HAS_PAHO = False
        # Guss-Steuerung & einheitlichen Client für Legacy-Tests initialisieren und verdrahten
        from daemon import scheduler
        from daemon.core.event_bus import EventBus
        from daemon.core.watering_controller import WateringController
        from daemon.adapters.database_adapter import DatabaseLoggerAdapter
        
        mqtt_client.start_client()
        watering_ctrl = WateringController(mqtt_client._global_bus, mqtt_client.client_instance)
        scheduler.controller = watering_ctrl
        cls.db_adapter = DatabaseLoggerAdapter(mqtt_client._global_bus)
        
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

    def test_08_first_to_hit_time_limit_with_unreached_volume(self):
        """Testet, ob das Zeitlimit bei nicht erreichtem Volumenlimit eine Notfall-Abschaltung auslöst."""
        from daemon import scheduler
        
        # Sicherstellen, dass kein Zyklus aktiv ist
        scheduler.stop_watering()
        
        # Starte eine Bewässerung mit 10 Minuten Zeitlimit und 5 Litern Volumenlimit
        success, msg = scheduler.start_watering(duration_minutes=10, target_volume_liters=5, source="test")
        self.assertTrue(success)
        self.assertEqual(mqtt_client.get_valve_status()["state"], "ON")
        
        # Mocking des Telegram-Callbacks, um die Push-Nachricht zu überprüfen
        mock_notification = MagicMock()
        scheduler.register_notification_callback(mock_notification)
        
        # Simuliere, dass das Volumenlimit vor Ablauf der Zeit nicht erreicht wurde (z.B. nur 3 Liter)
        mqtt_client.active_cycle_volume = 3.0
        
        # Manuelles Auslösen des Timeouts
        scheduler._time_limit_callback()
        
        # Überprüfen, ob das Ventil geschlossen wurde
        self.assertEqual(mqtt_client.get_valve_status()["state"], "OFF")
        self.assertIsNone(scheduler.get_active_cycle())
        
        # Überprüfen, ob die Historie als "failed" weggeschrieben wurde
        history = database.get_recent_history(1)
        self.assertGreater(len(history), 0)
        self.assertEqual(history[0]["status"], "failed")
        self.assertIn("Notfall-Abschaltung", history[0]["details"])
        self.assertIn("3.0l geflossen", history[0]["details"])
        
        # Benachrichtigung auf Notfall-Text prüfen
        mock_notification.assert_called_once()
        notification_text = mock_notification.call_args[0][0]
        self.assertIn("Notfall-Abschaltung", notification_text)
        self.assertIn("Zielwassermenge", notification_text)
        self.assertIn("3.0 Liter", notification_text)

    def test_09_mqtt_time_gap_capping(self):
        """Testet, ob ein Zeit-Gap von >= 60 Sek in der MQTT-Durchfluss-Integration auf 60 Sek gedeckelt wird."""
        from datetime import datetime, timedelta
        
        # Client starten und Ventil auf ON setzen
        mqtt_client.start_client()
        mqtt_client.valve_status["state"] = "ON"
        mqtt_client.active_cycle_volume = 10.0
        
        # Mocking der letzten Update-Zeit auf 75 Sekunden in der Vergangenheit
        mqtt_client.last_flow_update_time = datetime.now() - timedelta(seconds=75)
        
        # Mock-Nachricht mit flow_rate = 6.0 L/min (0.1 l/s)
        class MockMsg:
            def __init__(self, payload):
                self.payload = payload
        
        payload = json.dumps({
            "state": "ON",
            "flow_rate": 6.0,
            "battery": 95,
            "linkquality": 120
        }).encode("utf-8")
        msg = MockMsg(payload)
        
        # on_message direkt triggern
        mqtt_client.on_message(None, None, msg)
        
        # Durch die Deckelung auf max. 60 Sek:
        # Zuwachs = 6.0 L/min * (60.0 / 60.0) = 6.0 Liter
        # Erwartetes Gesamtvolumen = 10.0 + 6.0 = 16.0 Liter
        self.assertAlmostEqual(mqtt_client.get_active_volume(), 16.0, places=1)

    def test_10_startup_safety_shutdown(self):
        """Testet die Sicherheits-Schließung beim Systemstart bei unerwartet offenem Ventil."""
        from daemon import scheduler
        
        # Sicherstellen, dass kein Zyklus aktiv ist
        scheduler.stop_watering()
        self.assertIsNone(scheduler.get_active_cycle())
        
        # Mocking des Ventil-Zustands auf ON
        mqtt_client.valve_status["state"] = "ON"
        
        # Mocking der Telegram-Push-Meldung
        mock_notification = MagicMock()
        scheduler.register_notification_callback(mock_notification)
        
        # Führe den Sicherheitscheck aus
        triggered = scheduler.check_startup_safety()
        
        # Assertions
        self.assertTrue(triggered)
        self.assertEqual(mqtt_client.get_valve_status()["state"], "OFF")
        mock_notification.assert_called_once()
        self.assertIn("Sicherheits-Schließung", mock_notification.call_args[0][0])

    def test_11_database_metadata_and_stats(self):
        """Testet get/set_metadata und get_watering_stats_last_24h in der Datenbank."""
        # Test 1: Metadaten
        database.set_metadata("test_key", "test_value")
        self.assertEqual(database.get_metadata("test_key"), "test_value")
        self.assertEqual(database.get_metadata("non_existent_key", "default_val"), "default_val")

        # Test 2: Guss-Statistiken der letzten 24h
        # Zunächst löschen wir die watering_history für saubere Testbedingungen
        conn = database.get_connection()
        conn.execute("DELETE FROM watering_history")
        conn.commit()
        conn.close()

        # Logge erfolgreiche und fehlgeschlagene Läufe der letzten 24h
        database.log_watering(10, "schedule", "completed", "Erfolgreicher Lauf", watered_volume=12.5)
        database.log_watering(5, "manual", "stopped", "Vorzeitig gestoppt", watered_volume=3.2)
        database.log_watering(15, "schedule", "failed", "Fehlgeschlagener Lauf", watered_volume=0.0)

        # Logge einen Lauf, der älter als 24h ist (sollte ignoriert werden)
        from datetime import datetime, timedelta
        conn = database.get_connection()
        old_time = (datetime.now() - timedelta(hours=25)).isoformat()
        conn.execute(
            "INSERT INTO watering_history (timestamp, duration_minutes, source, status, details, watered_volume) VALUES (?, ?, ?, ?, ?, ?)",
            (old_time, 20, "schedule", "completed", "Alter Lauf", 50.0)
        )
        conn.commit()
        conn.close()

        success_count, failed_count, total_volume = database.get_watering_stats_last_24h()
        # Vorzeitig gestoppt und completed gelten als erfolgreich; failed als fehlgeschlagen.
        self.assertEqual(success_count, 2)
        self.assertEqual(failed_count, 1)
        self.assertEqual(total_volume, 15.7)

    def test_12_daily_report_generation(self):
        """Testet die Generierung des Tagesberichts und das Erkennen von Warnungen."""
        from datetime import datetime, timedelta
        from daemon import scheduler
        
        # Mocke Wetterdaten
        with patch("daemon.adapters.weather.get_weather_data") as mock_weather_data:
            mock_weather_data.return_value = (1.5, 2.0, 21.0, 3) # Bedeckt
            
            # 1. Fall: Normaler Zustand (Keine Warnungen)
            mqtt_client.valve_status["battery"] = 90
            mqtt_client.valve_status["valve_abnormal_state"] = "normal"
            mqtt_client.valve_status["last_update"] = datetime.now().isoformat()
            
            report = scheduler.generate_daily_report("2026-06-07")
            self.assertIn("Statusbericht vom 07.06.2026", report)
            self.assertIn("Erfolgreiche Zyklen", report)
            self.assertIn("Temperatur: 21.0 °C", report)
            self.assertNotIn("System-Warnungen", report)
            
            # 2. Fall: Batterie schwach, Offline und abnormaler Zustand (Warnungen)
            mqtt_client.valve_status["battery"] = 15 # Unter 20%
            mqtt_client.valve_status["valve_abnormal_state"] = "water_shortage"
            # Letztes Signal vor 25 Stunden
            mqtt_client.valve_status["last_update"] = (datetime.now() - timedelta(hours=25)).isoformat()
            
            report_warn = scheduler.generate_daily_report("2026-06-07")
            self.assertIn("System-Warnungen", report_warn)
            self.assertIn("Niedriger Batteriestand", report_warn)
            self.assertIn("Verbindung verloren", report_warn)
            self.assertIn("Ventil-Anomalie erkannt", report_warn)

    def test_13_device_status_stats(self):
        """Testet das passive Loggen des Gerätestatus und die Berechnung der LQI- und Funklücken-Statistik."""
        # 1. Datenbank-Tabelle leeren
        conn = database.get_connection()
        conn.execute("DELETE FROM device_status_log")
        conn.commit()
        conn.close()

        # 2. Logge Status-Meldungen zu verschiedenen Zeitpunkten
        from datetime import datetime, timedelta
        now = datetime.now()
        
        conn = database.get_connection()
        
        # Meldung 1: Vor 20 Stunden, LQI = 150
        time1 = (now - timedelta(hours=20)).isoformat()
        conn.execute("INSERT INTO device_status_log (timestamp, battery, linkquality) VALUES (?, ?, ?)", (time1, 95, 150))
        
        # Meldung 2: Vor 12 Stunden, LQI = 120
        time2 = (now - timedelta(hours=12)).isoformat()
        conn.execute("INSERT INTO device_status_log (timestamp, battery, linkquality) VALUES (?, ?, ?)", (time2, 94, 120))
        
        # Meldung 3: Vor 2 Stunden, LQI = 130
        time3 = (now - timedelta(hours=2)).isoformat()
        conn.execute("INSERT INTO device_status_log (timestamp, battery, linkquality) VALUES (?, ?, ?)", (time3, 93, 130))
        
        conn.commit()
        conn.close()

        # 3. Statistik abrufen
        stats = database.get_device_status_stats_last_24h()
        
        self.assertEqual(stats["count"], 3)
        self.assertEqual(stats["avg_lqi"], 133.3)  # (150 + 120 + 130) / 3 = 133.333...
        
        # Längste Lücke zwischen Meldung 2 (vor 12h) und Meldung 3 (vor 2h) -> 10 Stunden
        self.assertAlmostEqual(stats["max_gap_hours"], 10.0, places=1)


if __name__ == "__main__":
    unittest.main()


