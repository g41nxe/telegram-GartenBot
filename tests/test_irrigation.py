import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import io
from datetime import timedelta
import json
from daemon.adapters.daily_report import generate_daily_report

# src-Ordner zum Python-Path hinzufügen, damit wir 'daemon' importieren können
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from daemon import config
from daemon.adapters import database, weather, mqtt_client
from daemon.core.watering_advice import WateringDecision

_FULL_WATERING = WateringDecision(factor=1.0, verdict="🚿 Voller Guss", reasons=["OK"], skip=False)

class TestGardenIrrigation(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        """Initialisiert die Testdatenbank und erzwingt den Simulationsmodus."""
        database.init_db()
        mqtt_client.HAS_PAHO = False

        # Telegram-Blocking ist bereits durch tests/__init__.py (drei Schutzschichten)
        # aktiv. Kein weiteres Patching hier nötig.

        # Guss-Steuerung & einheitlichen Client für Legacy-Tests initialisieren und verdrahten
        from daemon import scheduler
        from daemon.core.event_bus import EventBus
        from daemon.core.watering_controller import WateringController
        from daemon.adapters.database_adapter import DatabaseLoggerAdapter

        mqtt_client.start_client()
        watering_ctrl = WateringController(mqtt_client._global_bus, mqtt_client.client_instance.publish)
        cls.watering_ctrl = watering_ctrl
        scheduler.set_controller(watering_ctrl)
        cls.db_adapter = DatabaseLoggerAdapter(mqtt_client._global_bus)
        
    def test_01_config_defaults(self):
        """Überprüft, ob Standard-Konfigurationswerte korrekt geladen werden."""
        self.assertEqual(config.RAIN_THRESHOLD_MM, 3.0)
        self.assertEqual(config.SAFETY_TIMEOUT_MINUTES, 30)
        self.assertEqual(config.MQTT_BROKER_PORT, 1883)
        self.assertTrue(config.UNEXPECTED_VALVE_ALERT_ENABLED)
        
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
        self.watering_ctrl.stop_watering()
        
        # Startet eine Bewässerung mit 10 Minuten Zeitlimit und 5 Litern Volumenlimit
        success, msg = self.watering_ctrl.start_watering(duration_minutes=10, target_volume_liters=5, source="test")
        self.assertTrue(success)
        self.assertEqual(mqtt_client.get_valve_status()["state"], "ON")
        self.assertIsNotNone(self.watering_ctrl.get_active_cycle())
        
        # Simuliert, dass das Volumenlimit überschritten wird
        scheduler._controller._active_cycles["garden_valve"]["current_volume"] = 6.0

        # Warte kurz, bis der Volumen-Wächter-Thread (schlägt beim nächsten MQTT-Event zu)
        time.sleep(3)
        
        # Prüfen, ob das Ventil geschlossen wurde
        self.assertEqual(mqtt_client.get_valve_status()["state"], "OFF")
        self.assertIsNone(self.watering_ctrl.get_active_cycle())
        
        # Überprüfen, ob das Protokoll korrekt weggeschrieben wurde
        history = database.get_recent_history(1)
        self.assertGreater(len(history), 0)
        self.assertEqual(history[0]["status"], "completed")
        self.assertIn("Volumenlimit", history[0]["details"])

    @patch("daemon.adapters.weather.database.get_daily_max_temps", return_value=[])
    @patch("urllib.request.urlopen")
    def test_06_weather_api_parsing_and_skip(self, mock_urlopen, _mock_temps):
        """Simuliert eine erfolgreiche Open-Meteo API-Antwort und testet die Skip-Logik.

        Verwendet einen kühlen Tag (temp_max=15°C) ohne Hitzestrecke, sodass die
        Schwelle nicht angehoben wird. rain_last=1.5mm + rain_next_eff≈1.875mm > 3.0mm → skip.
        Patch auf get_daily_max_temps nötig: die echte DB kann Hitzetage aus dem
        Produktivbetrieb enthalten, die hitze_faktor > 1 erzeugen und T_eff über R_eff heben.
        """
        # Mocking der stündlichen Niederschläge (48 Stunden: 24h Vergangenheit + 24h Zukunft)
        precipitation = [0.0] * 48
        precipitation[10] = 1.5  # In der Vergangenheit (rain_last)
        precipitation[30] = 2.5  # In der Zukunft (prob-gewichtet: 2.5*75%=1.875mm → R_eff≈3.375)

        # Stündliche Regenwahrscheinlichkeit
        precip_probability = [10] * 48
        precip_probability[30] = 75

        # Erstelle eine Mock-Stundenliste
        from datetime import datetime
        now = datetime.now()
        times = []
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        start_hour = current_hour - timedelta(hours=24)
        for i in range(48):
            t = start_hour + timedelta(hours=i)
            times.append(t.strftime("%Y-%m-%dT%H:00"))

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "current": {
                "temperature_2m": 12.5,
                "weather_code": 3
            },
            "hourly": {
                "time": times,
                "precipitation": precipitation,
                "precipitation_probability": precip_probability
            },
            "daily": {
                "time": [
                    (now - timedelta(days=1)).strftime("%Y-%m-%d"),
                    now.strftime("%Y-%m-%d"),
                    (now + timedelta(days=1)).strftime("%Y-%m-%d")
                ],
                "temperature_2m_max": [20.0, 15.0, 14.0],
                "temperature_2m_min": [10.0, 8.0, 7.0]
            }
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        # Führe Abfrage aus
        rain_last, rain_next, temp, code, temp_min, temp_max, rain_prob, rain_last_source = weather.get_weather_data(52.5, 13.5)

        self.assertEqual(rain_last, 1.5)
        self.assertEqual(rain_next, 2.5)
        self.assertEqual(temp, 12.5)
        self.assertEqual(code, 3)
        self.assertEqual(temp_min, 8.0)
        self.assertEqual(temp_max, 15.0)
        self.assertEqual(rain_prob, 75)

        # Skip-Logik: kühler Tag, R_eff ≈ 3.375 mm > Schwelle 3.0 mm → skip=True
        should_skip, details = weather.should_skip_watering()
        self.assertTrue(should_skip)
        self.assertIn("mm", details)

    @patch("daemon.adapters.weather.database.get_last_weather", return_value=None)
    @patch("urllib.request.urlopen")
    def test_07_weather_offline_fallback(self, mock_urlopen, mock_get_last_weather):
        """Testet das Offline-first Fallback bei einem API-Ausfall ohne DB-Cache."""
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Mocked network timeout")

        # Bei Netzwerkfehler gibt get_weather_data None zurück
        result = weather.get_weather_data(52.5, 13.5)
        self.assertIsNone(result)

        # Kein Cache + kein Netz → skip=False (Guss wird durchgeführt)
        should_skip, details = weather.should_skip_watering()
        self.assertFalse(should_skip)
        self.assertIn("Keine Wetterdaten verfügbar", details)

    def test_08_first_to_hit_time_limit_with_unreached_volume(self):
        """Testet, ob das Zeitlimit bei nicht erreichtem Volumenlimit eine Notfall-Abschaltung auslöst."""
        from daemon import scheduler
        
        # Sicherstellen, dass kein Zyklus aktiv ist
        self.watering_ctrl.stop_watering()
        
        # Starte eine Bewässerung mit 10 Minuten Zeitlimit und 5 Litern Volumenlimit
        success, msg = self.watering_ctrl.start_watering(duration_minutes=10, target_volume_liters=5, source="test")
        self.assertTrue(success)
        self.assertEqual(mqtt_client.get_valve_status()["state"], "ON")
        
        from daemon.core.watering_controller import WateringCycleFailed
        
        # Mocking des Event-Busses
        mock_event_handler = MagicMock()
        mqtt_client._global_bus.subscribe(WateringCycleFailed, mock_event_handler)
        
        # Simuliere, dass das Volumenlimit vor Ablauf der Zeit nicht erreicht wurde (z.B. nur 3 Liter)
        scheduler._controller._active_cycles["garden_valve"]["current_volume"] = 3.0
        
        # Manuelles Auslösen des Timeouts
        self.watering_ctrl._time_limit_callback()
        
        # Überprüfen, ob das Ventil geschlossen wurde
        self.assertEqual(mqtt_client.get_valve_status()["state"], "OFF")
        self.assertIsNone(self.watering_ctrl.get_active_cycle())
        
        # Überprüfen, ob die Historie als "failed" weggeschrieben wurde
        history = database.get_recent_history(1)
        self.assertGreater(len(history), 0)
        self.assertEqual(history[0]["status"], "failed")
        self.assertIn("Notfall-Abschaltung", history[0]["details"])
        self.assertIn("3.0l geflossen", history[0]["details"])
        
        # Benachrichtigung auf Notfall-Text prüfen
        mock_event_handler.assert_called_once()
        event = mock_event_handler.call_args[0][0]
        self.assertIn("Notfall-Abschaltung", event.details)
        self.assertIn("Zielwassermenge", event.details)

    def test_09_mqtt_time_gap_capping(self):
        """Testet, ob ein Zeit-Gap von >= 60 Sek in der Durchfluss-Integration auf 60 Sek gedeckelt wird."""
        from datetime import datetime, timedelta
        from daemon import scheduler
        from daemon.adapters.mqtt_client import ValveStatusReported

        # Vorherige Zyklen bereinigen
        self.watering_ctrl.stop_watering()

        # Starte Bewässerung mit großem Volumenziel, damit der Hintergrund-Simulator es nicht zufällig schließt
        success, msg = self.watering_ctrl.start_watering(duration_minutes=10, target_volume_liters=100, source="test")
        self.assertTrue(success, f"Bewässerung konnte nicht gestartet werden: {msg}")

        # Hintergrund-Simulator pausieren: valve_status auf OFF setzen, damit der Sim-Loop keine
        # ON-Events feuert, die die künstlich gesetzte _last_flow_update_time konsumieren würden.
        mqtt_client.valve_status["state"] = "OFF"

        # Setze den Controller künstlich auf 10 Liter in die Vergangenheit
        scheduler._controller._active_cycles["garden_valve"]["current_volume"] = 10.0
        scheduler._controller._last_flow_update_time["garden_valve"] = datetime.now() - timedelta(seconds=75)

        # Simuliere ON-Event mit Flow-Rate 6.0 L/min
        scheduler._controller.event_bus.publish(ValveStatusReported("garden_valve", "ON", 6.0, 95, 120, "normal"))

        # Durch die Deckelung auf max. 60 Sek:
        # Zuwachs = 6.0 L/min * (60.0 / 60.0) = 6.0 Liter
        # Erwartetes Gesamtvolumen = 10.0 + 6.0 = 16.0 Liter
        self.assertAlmostEqual(scheduler._controller.get_active_volume(), 16.0, places=1)
        self.watering_ctrl.stop_watering()

    def test_10_startup_safety_shutdown(self):
        """Testet die Sicherheits-Schließung beim Systemstart bei unerwartet offenem Ventil."""
        from daemon import scheduler
        
        # Sicherstellen, dass kein Zyklus aktiv ist
        self.watering_ctrl.stop_watering()
        self.assertIsNone(self.watering_ctrl.get_active_cycle())
        
        # Mocking des Ventil-Zustands auf ON
        mqtt_client.valve_status["state"] = "ON"
        
        from daemon.core.scheduler_events import ScheduleFailed
        
        # Mocking Event Bus
        mock_event_handler = MagicMock()
        mqtt_client._global_bus.subscribe(ScheduleFailed, mock_event_handler)
        
        # Führe den Sicherheitscheck aus
        triggered = scheduler.check_startup_safety()
        
        # Assertions
        self.assertTrue(triggered)
        self.assertEqual(mqtt_client.get_valve_status()["state"], "OFF")
        mock_event_handler.assert_called_once()
        self.assertIn("Sicherheits-Schließung", mock_event_handler.call_args[0][0].details)

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
            mock_weather_data.return_value = (1.5, 2.0, 21.0, 3, 12.5, 25.0, 80, "measured")  # Bedeckt

            # Watchdog-Flags zurücksetzen (könnten von vorherigen Testläufen gesetzt worden sein)
            for v in database.get_all_valves():
                database.set_metadata(f"watchdog_alert_active_valve_{v['id']}", "0")

            # 1. Fall: Normaler Zustand (Keine Warnungen) — Ventil-Status via DB setzen
            database.update_valve_status("garden_valve", 90, 140, datetime.now().isoformat(), "normal")

            report = generate_daily_report("2026-06-07")
            self.assertIn("07.06.", report)
            self.assertIn("💧", report)  # Wässerungs-Sektion
            self.assertIn("12–25 °C", report)  # Temperatur-Range (gerundet)
            self.assertIn("2.0 mm erwartet", report)  # Regen-Info im neuen Format
            self.assertIn("alles in Ordnung", report)  # System-OK-Zeile

            # 2. Fall: Batterie schwach, Watchdog-Flag gesetzt, abnormaler Zustand (Warnungen)
            old_time = (datetime.now() - timedelta(hours=25)).isoformat()
            database.update_valve_status("garden_valve", 15, 140, old_time, "water_shortage")
            valve = database.get_valve_by_mqtt_name("garden_valve")
            database.set_metadata(f"watchdog_alert_active_valve_{valve['id']}", "1")

            report_warn = generate_daily_report("2026-06-07")
            self.assertIn("Anomalie erkannt (water_shortage)", report_warn)
            self.assertIn("kein Signal (Watchdog aktiv)", report_warn)

            # DB-Status und Watchdog-Flag für Folgetests zurücksetzen
            database.update_valve_status("garden_valve", 95, 140, datetime.now().isoformat(), "normal")
            database.set_metadata(f"watchdog_alert_active_valve_{valve['id']}", "0")

            # 3. Fall: Broker disconnected, Mittelweg-Dienst offline
            try:
                mqtt_client.HAS_PAHO = True

                with patch("daemon.adapters.mqtt_client.is_broker_connected", return_value=False), \
                     patch("daemon.adapters.mqtt_client.get_bridge_status", return_value="offline"):
                    report_serv_offline = generate_daily_report("2026-06-07")
                    self.assertIn("MQTT-Broker nicht erreichbar", report_serv_offline)

                with patch("daemon.adapters.mqtt_client.is_broker_connected", return_value=True), \
                     patch("daemon.adapters.mqtt_client.get_bridge_status", return_value="offline"):
                    report_z2m_offline = generate_daily_report("2026-06-07")
                    self.assertIn("Mittelweg-Dienst (Zigbee2MQTT) offline", report_z2m_offline)
            finally:
                mqtt_client.HAS_PAHO = False

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
        conn.execute("INSERT INTO device_status_log (timestamp, device_name, battery, linkquality) VALUES (?, ?, ?, ?)", (time1, "garden_valve", 95, 150))

        # Meldung 2: Vor 12 Stunden, LQI = 120
        time2 = (now - timedelta(hours=12)).isoformat()
        conn.execute("INSERT INTO device_status_log (timestamp, device_name, battery, linkquality) VALUES (?, ?, ?, ?)", (time2, "garden_valve", 94, 120))

        # Meldung 3: Vor 2 Stunden, LQI = 130
        time3 = (now - timedelta(hours=2)).isoformat()
        conn.execute("INSERT INTO device_status_log (timestamp, device_name, battery, linkquality) VALUES (?, ?, ?, ?)", (time3, "garden_valve", 93, 130))

        conn.commit()
        conn.close()

        # 3. Statistik abrufen
        stats = database.get_device_status_stats_last_24h("garden_valve")
        
        self.assertEqual(stats["count"], 3)
        self.assertEqual(stats["avg_lqi"], 133.3)  # (150 + 120 + 130) / 3 = 133.333...
        
        # Längste Lücke zwischen Meldung 2 (vor 12h) und Meldung 3 (vor 2h) -> 10 Stunden
        self.assertAlmostEqual(stats["max_gap_hours"], 10.0, places=1)

    def test_14_mqtt_bridge_status_parsing(self):
        """Testet das Empfangen und Verarbeiten des Bridge-Status in on_message."""
        # Initialer Zustand
        mqtt_client.bridge_status = "offline"
        
        # Simuliere eingehende Nachricht
        class MockMsg:
            def __init__(self, topic, payload):
                self.topic = topic
                self.payload = payload
                
        # Send online payload (altes Format)
        msg_online = MockMsg("zigbee2mqtt/bridge/state", b"online")
        mqtt_client.on_message(None, None, msg_online)
        self.assertEqual(mqtt_client.get_bridge_status(), "online")
        
        # Send offline payload (altes Format)
        msg_offline = MockMsg("zigbee2mqtt/bridge/state", b"offline")
        mqtt_client.on_message(None, None, msg_offline)
        self.assertEqual(mqtt_client.get_bridge_status(), "offline")

        # Send online JSON payload (neues Format)
        msg_online_json = MockMsg("zigbee2mqtt/bridge/state", b'{"state":"online"}')
        mqtt_client.on_message(None, None, msg_online_json)
        self.assertEqual(mqtt_client.get_bridge_status(), "online")
        
        # Send offline JSON payload (neues Format)
        msg_offline_json = MockMsg("zigbee2mqtt/bridge/state", b'{"state":"offline"}')
        mqtt_client.on_message(None, None, msg_offline_json)
        self.assertEqual(mqtt_client.get_bridge_status(), "offline")

    def test_15_scheduler_trigger_watering(self):
        """Testet die Wetter-Skip und Start-Logik in _trigger_scheduled_watering."""
        from daemon import scheduler
        from daemon.core.scheduler_events import WateringSkipped, ScheduleFailed
        from daemon.core.watering_advice import WateringDecision

        skip_decision = WateringDecision(factor=0.0, verdict="🌧 Kein Gießen nötig", reasons=["Too wet"], skip=True)

        # Mock weather skip
        with patch("daemon.adapters.weather.evaluate_watering_factor", return_value=skip_decision):
            mock_handler = MagicMock()
            mqtt_client._global_bus.subscribe(WateringSkipped, mock_handler)
            scheduler._trigger_scheduled_watering({"name": "Test1", "duration_minutes": 10})
            mock_handler.assert_called_once()
            self.assertIn("Too wet", mock_handler.call_args[0][0].details)

        # Mock weather exception — Ventil-Start schlägt fehl → ScheduleFailed
        with patch("daemon.adapters.weather.evaluate_watering_factor", side_effect=Exception("API down")), \
             patch.object(scheduler._controller, "start_watering", return_value=(False, "Failed start")):
            mock_fail = MagicMock()
            mqtt_client._global_bus.subscribe(ScheduleFailed, mock_fail)
            scheduler._trigger_scheduled_watering({"name": "Test2", "duration_minutes": 10})
            mock_fail.assert_called_once()
            self.assertIn("Failed start", mock_fail.call_args[0][0].details)
            
    def test_15b_scheduler_graduated_scaling(self):
        """Graduierte Gieß-Steuerung: Faktor 50% halbiert Dauer und Volumen, publiziert WateringScaled."""
        from daemon import scheduler
        from daemon.core.scheduler_events import WateringScaled
        from daemon.core.watering_advice import WateringDecision

        scaled_decision = WateringDecision(
            factor=0.5, verdict="💧 Reduzierter Guss (50 %)", reasons=["1.5 mm Regen."], skip=False
        )

        call_args = []
        original_start = scheduler._controller.start_watering

        def mock_start(duration, volume, source, mqtt_name="garden_valve", valve_topic=None):
            call_args.append((duration, volume))
            return True, "OK"

        scheduler._controller.start_watering = mock_start
        try:
            scaled_events = []
            mqtt_client._global_bus.subscribe(WateringScaled, lambda e: scaled_events.append(e))

            with patch("daemon.adapters.weather.evaluate_watering_factor", return_value=scaled_decision):
                scheduler._trigger_scheduled_watering({
                    "name": "Skala-Test", "duration_minutes": 10, "target_volume_liters": 20,
                    "execution_mode": "sequential",
                })

            self.assertEqual(len(scaled_events), 1, "WateringScaled muss einmal publiziert werden")
            self.assertAlmostEqual(scaled_events[0].factor, 0.5)
            self.assertEqual(scaled_events[0].duration_scaled, 5)
            self.assertEqual(scaled_events[0].volume_scaled, 10)

            self.assertEqual(len(call_args), 1, "Ventil-Start muss einmal aufgerufen werden")
            self.assertEqual(call_args[0][0], 5, "Skalierte Dauer: 10 * 0.5 = 5")
            self.assertEqual(call_args[0][1], 10, "Skaliertes Volumen: 20 * 0.5 = 10")
        finally:
            scheduler._controller.start_watering = original_start

    def test_15c_scheduler_full_factor_no_scaling(self):
        """Faktor=1.0 → Zeitplan läuft unverändert, kein WateringScaled-Event."""
        from daemon import scheduler
        from daemon.core.scheduler_events import WateringScaled

        call_args = []
        original_start = scheduler._controller.start_watering

        def mock_start(duration, volume, source, mqtt_name="garden_valve", valve_topic=None):
            call_args.append((duration, volume))
            return True, "OK"

        scheduler._controller.start_watering = mock_start
        try:
            scaled_events = []
            mqtt_client._global_bus.subscribe(WateringScaled, lambda e: scaled_events.append(e))

            with patch("daemon.adapters.weather.evaluate_watering_factor", return_value=_FULL_WATERING):
                scheduler._trigger_scheduled_watering({
                    "name": "Voll-Test", "duration_minutes": 10, "target_volume_liters": 20,
                    "execution_mode": "sequential",
                })

            self.assertEqual(len(scaled_events), 0, "Kein WateringScaled bei Faktor=1.0")
            self.assertEqual(call_args[0][0], 10, "Dauer unverändert")
            self.assertEqual(call_args[0][1], 20, "Volumen unverändert")
        finally:
            scheduler._controller.start_watering = original_start

    def test_16_scheduler_loop_and_daily_report(self):
        """Testet den main _scheduler_loop auf weather updates und daily reports."""
        from daemon import scheduler
        from datetime import datetime
        
        with patch("daemon.scheduler.datetime") as mock_datetime, \
             patch("daemon.scheduler.time.sleep") as mock_sleep, \
             patch("daemon.scheduler.check_startup_safety") as mock_safety, \
             patch("daemon.scheduler.send_daily_report") as mock_report, \
             patch("daemon.adapters.weather.get_weather_data") as mock_weather:
            
            # Setup mock time
            mock_now = datetime(2026, 6, 9, 8, 5) # 08:05
            mock_datetime.now.return_value = mock_now
            mock_datetime.fromisoformat = datetime.fromisoformat
            
            # Simulate one loop iteration
            sleep_calls = [0]
            def side_effect_sleep(*args):
                sleep_calls[0] += 1
                if sleep_calls[0] > 1:
                    scheduler.scheduler_running = False # Stop loop
                
            mock_sleep.side_effect = side_effect_sleep
            
            database.set_metadata("last_daily_report_date", "2026-06-08") # Yesterday
            
            scheduler.scheduler_running = True
            scheduler._scheduler_loop()
            
            mock_safety.assert_called_once()
            # The thread is started, mock_report should be called in thread.
            # But thread might take a moment.
            
    def test_18_generate_daily_report_exception(self):
        from daemon import scheduler
        with patch("daemon.adapters.weather.get_weather_data", side_effect=Exception("API error")):
            report = generate_daily_report("2026-06-09")
            self.assertIn("09.06.", report)  # Datum erscheint auch bei Wetterfehler

    def test_19_scheduler_sequential_multi_valve(self):
        """_trigger_scheduled_watering startet mehrere Ventile nacheinander (sequentiell)."""
        from daemon import scheduler
        from daemon.core.watering_controller import WateringCycleCompleted

        self.watering_ctrl.stop_watering()

        # Zweites Test-Ventil anlegen (idempotent: bestehendes holen wenn schon vorhanden)
        valve2_id = database.add_valve("Terrasse", "valve_seq_test")
        if valve2_id <= 0:
            existing = database.get_valve_by_mqtt_name("valve_seq_test")
            valve2_id = existing["id"] if existing else 1
        sched_id = database.add_schedule("SeqTest", "03:00", "Mon", 5, 0)
        database.set_schedule_valves(sched_id, [1, valve2_id])

        started_valves = []
        original_start = scheduler._controller.start_watering

        def mock_start(duration, volume, source, mqtt_name="garden_valve", valve_topic=None):
            started_valves.append(mqtt_name)
            return True, "OK"

        scheduler._controller.start_watering = mock_start
        try:
            sched = {"id": sched_id, "name": "SeqTest", "duration_minutes": 5,
                     "target_volume_liters": 0, "execution_mode": "sequential"}

            with patch("daemon.adapters.weather.evaluate_watering_factor", return_value=_FULL_WATERING):
                scheduler._trigger_scheduled_watering(sched)

            # Nur das erste Ventil (garden_valve, id=1) soll sofort starten
            self.assertEqual(len(started_valves), 1, "Erstes Ventil soll sofort starten")
            self.assertEqual(started_valves[0], "garden_valve")

            # WateringCycleCompleted feuern → zweites Ventil muss starten
            mqtt_client._global_bus.publish(WateringCycleCompleted(5, 0.0, "schedule", "done"))

            self.assertEqual(len(started_valves), 2, "Zweites Ventil soll nach Abschluss des ersten starten")
            self.assertEqual(started_valves[1], "valve_seq_test")
        finally:
            scheduler._controller.start_watering = original_start
            database.delete_schedule(sched_id)

    def test_20_scheduler_parallel_multi_valve(self):
        """_trigger_scheduled_watering startet mehrere Ventile gleichzeitig (parallel)."""
        from daemon import scheduler

        self.watering_ctrl.stop_watering()

        valve2_id = database.add_valve("Rasen", "valve_par_test")
        if valve2_id <= 0:
            existing = database.get_valve_by_mqtt_name("valve_par_test")
            valve2_id = existing["id"] if existing else 1
        sched_id = database.add_schedule("ParTest", "04:00", "Mon", 5, 0)
        database.set_schedule_valves(sched_id, [1, valve2_id])

        started_valves = []
        original_start = scheduler._controller.start_watering

        def mock_start(duration, volume, source, mqtt_name="garden_valve", valve_topic=None):
            started_valves.append(mqtt_name)
            return True, "OK"

        scheduler._controller.start_watering = mock_start
        try:
            sched = {"id": sched_id, "name": "ParTest", "duration_minutes": 5,
                     "target_volume_liters": 0, "execution_mode": "parallel"}

            with patch("daemon.adapters.weather.evaluate_watering_factor", return_value=_FULL_WATERING):
                scheduler._trigger_scheduled_watering(sched)

            # Beide Ventile müssen sofort gestartet sein
            self.assertEqual(len(started_valves), 2, "Beide Ventile sollen gleichzeitig starten")
            self.assertIn("garden_valve", started_valves)
            self.assertIn("valve_par_test", started_valves)
        finally:
            scheduler._controller.start_watering = original_start
            database.delete_schedule(sched_id)

    def test_22_daily_report_iterates_all_valves(self):
        """Morgen-Bericht iteriert alle Ventile: grüner Pfad zeigt Kurzform, Problemfall zeigt Ventilname."""
        from datetime import datetime

        valve2_id = database.add_valve("Rasen", "valve_report_test")
        if valve2_id <= 0:
            existing = database.get_valve_by_mqtt_name("valve_report_test")
            valve2_id = existing["id"] if existing else 1

        now_str = datetime.now().isoformat()
        database.update_valve_status("garden_valve", 95, 140, now_str, "normal")
        database.update_valve_status("valve_report_test", 80, 120, now_str, "normal")

        with patch("daemon.adapters.weather.get_weather_data") as mock_weather:
            mock_weather.return_value = (0.0, 0.0, 20.0, 0, 15.0, 25.0, 10, "measured")
            report = generate_daily_report("2026-06-13")

        # Grüner Pfad: beide Ventile OK → Kurzform ohne Ventildetails
        self.assertIn("alles in Ordnung", report)
        self.assertNotIn("Anomalie", report)

        # Problemfall: Rasen-Ventil hat schwache Batterie → erscheint im Bericht
        database.update_valve_status("valve_report_test", 10, 120, now_str, "normal")
        with patch("daemon.adapters.weather.get_weather_data") as mock_weather:
            mock_weather.return_value = (0.0, 0.0, 20.0, 0, 15.0, 25.0, 10, "measured")
            report_warn = generate_daily_report("2026-06-13")
        self.assertIn("Rasen", report_warn)
        self.assertIn("Batterie schwach", report_warn)
        # Aufräumen
        database.update_valve_status("valve_report_test", 80, 120, now_str, "normal")

    def test_21_scheduler_fallback_garden_valve(self):
        """_trigger_scheduled_watering fällt auf garden_valve zurück wenn keine Ventile zugewiesen."""
        from daemon import scheduler

        self.watering_ctrl.stop_watering()
        sched_id = database.add_schedule("FallbackTest", "05:00", "Mon", 5, 0)
        # Absichtlich kein set_schedule_valves → Fallback auf garden_valve

        call_args = []
        original_start = scheduler._controller.start_watering

        def mock_start(duration, volume, source, mqtt_name="garden_valve", valve_topic=None):
            call_args.append((mqtt_name, valve_topic))
            return True, "OK"

        scheduler._controller.start_watering = mock_start
        try:
            sched = {"id": sched_id, "name": "FallbackTest", "duration_minutes": 5,
                     "target_volume_liters": 0, "execution_mode": "sequential"}

            with patch("daemon.adapters.weather.evaluate_watering_factor", return_value=_FULL_WATERING):
                scheduler._trigger_scheduled_watering(sched)

            self.assertEqual(len(call_args), 1, "Genau ein Aufruf erwartet")
            self.assertEqual(call_args[0][0], "garden_valve", "Fallback-Ventil muss garden_valve sein")
            self.assertEqual(call_args[0][1], "zigbee2mqtt/garden_valve", "Topic muss korrekt gesetzt sein")
        finally:
            scheduler._controller.start_watering = original_start
            database.delete_schedule(sched_id)

    def test_23_unexpected_valve_open_emits_and_resolves(self):
        """End-to-End: Ventil öffnet ohne aktiven Guss → UnexpectedValveOpened; schließt → Resolved."""
        from daemon.core.valve_events import (
            ValveStatusReported, UnexpectedValveOpened, UnexpectedValveResolved,
        )
        bus = mqtt_client._global_bus
        self.watering_ctrl.stop_watering()
        mqtt_client.valve_status["state"] = "OFF"  # Simulations-Loop ruhig halten
        # Bekannten Vorzustand OFF setzen + evtl. Alt-Episode löschen (vor dem Subscriben)
        bus.publish(ValveStatusReported("garden_valve", "OFF", 0.0, 95, 120))

        opened, resolved = MagicMock(), MagicMock()
        bus.subscribe(UnexpectedValveOpened, opened)
        bus.subscribe(UnexpectedValveResolved, resolved)
        try:
            bus.publish(ValveStatusReported("garden_valve", "ON", 0.0, 95, 120))
            opened.assert_called_once()
            self.assertEqual(opened.call_args[0][0].mqtt_name, "garden_valve")

            bus.publish(ValveStatusReported("garden_valve", "OFF", 0.0, 95, 120))
            resolved.assert_called_once()
        finally:
            bus.unsubscribe(UnexpectedValveOpened, opened)
            bus.unsubscribe(UnexpectedValveResolved, resolved)

    def test_24_regular_guss_no_unexpected_event(self):
        """Regression: ein regulärer Guss (Start → Stopp) erzeugt keine UnexpectedValveOpened."""
        from daemon.core.valve_events import ValveStatusReported, UnexpectedValveOpened
        bus = mqtt_client._global_bus
        self.watering_ctrl.stop_watering()
        mqtt_client.valve_status["state"] = "OFF"
        bus.publish(ValveStatusReported("garden_valve", "OFF", 0.0, 95, 120))

        opened = MagicMock()
        bus.subscribe(UnexpectedValveOpened, opened)
        try:
            ok, _ = self.watering_ctrl.start_watering(
                5, 0, "manual", mqtt_name="garden_valve", valve_topic="zigbee2mqtt/garden_valve")
            self.assertTrue(ok)
            bus.publish(ValveStatusReported("garden_valve", "ON", 0.0, 95, 120))  # ON während Zyklus
            self.watering_ctrl.stop_watering("garden_valve")
            opened.assert_not_called()
        finally:
            self.watering_ctrl.stop_watering()
            bus.unsubscribe(UnexpectedValveOpened, opened)

if __name__ == "__main__":
    unittest.main()


