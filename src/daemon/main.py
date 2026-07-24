import time
import logging
import sys
from . import config, scheduler
from .adapters import database, mqtt_client

# Zentrales Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("garden_main")


def register_telegram_commands():
    """Registriert das native Telegram-Befehlsmenü (sichtbar im '/' Eingabefeld des Chats)."""
    from .ui import telegram_client
    # Feature 0031: De-dup zwischen /-Menü und Tastatur (siehe .agents/rules/telegram_messages.md).
    # Registriert nur Befehle ohne gleichwertigen Button (/tagesbericht, /diagnose) oder die in
    # Nachrichten verlinkt sind (/status: Kopplung/OTA/Hinweise · /update: CI-Build). /zeitplaene,
    # /einstellungen und /stopp wurden ganz entfernt (nur noch über ihren Tastatur-Button).
    commands = [
        {"command": "status",        "description": "Systemstatus anzeigen"},
        {"command": "tagesbericht",  "description": "Tagesbericht anzeigen"},
        {"command": "update",        "description": "Software-Update starten"},
        {"command": "diagnose",      "description": "Diagnose-Paket senden"},
    ]
    telegram_client.set_my_commands(commands)


def main():
    logger.info("==============================================")
    logger.info("Starte Gartenbewässerungs-Steuerung Daemon...")
    logger.info("==============================================")
    
    # 1. Datenbank initialisieren
    try:
        database.init_db()
    except Exception as e:
        logger.error(f"Kritischer Fehler bei der Datenbankinitialisierung: {e}")
        sys.exit(1)
        
    # 2. MQTT-Client starten und alle bekannten Ventile registrieren
    logger.info("Initialisiere MQTT-Dienst...")
    if not mqtt_client.start_client():
        logger.warning("MQTT-Dienst konnte nicht gestartet werden. Prüfen Sie Ihren Broker.")
    for _v in database.get_all_valves():
        mqtt_client.register_valve_topic(_v["mqtt_name"])
        
    # 3. Ereignis-Kanal & Guss-Steuerung initialisieren und verdrahten (IoC)
    logger.info("Initialisiere Ereignis-Kanal & Guss-Steuerung...")
    from .core.watering_controller import WateringController
    from .core.nebel_controller import NebelController
    from .adapters.database_adapter import DatabaseLoggerAdapter
    from .adapters.rain_event_adapter import RainEventAdapter

    watering_ctrl = WateringController(mqtt_client._global_bus, mqtt_client.client_instance.publish)
    scheduler.set_controller(watering_ctrl)

    # Nebel-Steuerung (Feature 0032): eigene Engine fürs Kühlen; beansprucht ihr Ventil
    # bei der Guss-Steuerung, damit Nebelstöße nicht als Fremdöffnung gelten.
    nebel_ctrl = NebelController(
        mqtt_client._global_bus, mqtt_client.client_instance.publish,
        claim_fn=watering_ctrl.claim_valve, release_fn=watering_ctrl.release_valve,
    )
    scheduler.set_nebel_controller(nebel_ctrl)

    # Initialisiere den DB-Logger Adapter zur Event-Archivierung
    db_adapter = DatabaseLoggerAdapter(mqtt_client._global_bus)

    # Regenereignis-Zustand mit Karenzzeit (ADR 0043): fasst einzelne Kipps der Regenwippe
    # zu einem Ereignis zusammen, damit die Meldungen nicht flattern.
    rain_event_adapter = RainEventAdapter(mqtt_client._global_bus)
        
    # 4. Kamera-Komponenten initialisieren
    logger.info("Initialisiere Kamera-Empfänger und Kopplungslogik...")
    from .adapters import camera_receiver, camera_pairing
    camera_pairing.init_pairing(mqtt_client._global_bus)
    camera_receiver.initialize(mqtt_client._global_bus)

    # 5. Inaktivitäts-Watchdog initialisieren
    from .adapters import watchdog
    watchdog.initialize()

    # 6. Zeitpläne/Scheduler starten
    logger.info("Initialisiere Bewässerungs-Scheduler...")
    scheduler.start_scheduler()
    
    # 7. Telegram-UI-Event-Handler verdrahten und Bot starten
    logger.info("Initialisiere Telegram-Bot...")
    from .ui import telegram_ui as _telegram_ui
    _telegram_ui.set_watering_controller(watering_ctrl)
    _telegram_ui.set_nebel_controller(nebel_ctrl)
    _telegram_ui.subscribe_event_handlers()
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning(
            "TELEGRAM_BOT_TOKEN ist nicht in .env konfiguriert. "
            "Der Bot steht nicht zur Verfügung!"
        )
    else:
        from .ui import telegram_client
        telegram_client.register_update_callback(_telegram_ui.on_telegram_update)
        telegram_client.start_polling()
        register_telegram_commands()
        logger.info("Telegram-Bot-System (entkoppelter Client & UI-Controller) erfolgreich initialisiert.")

    # Update-Benachrichtigung (ADR 0044): meldet einen Versionswechsel bzw. Rollback.
    # Bewusst außerhalb des Token-Zweigs, damit der Zustand (announced_version, Rollback-Marker)
    # bei jedem Start konsistent fortgeschrieben wird — sonst bliebe ohne Bot ein alter Marker
    # liegen und würde später eine falsche Fehlschlag-Meldung auslösen. Die Nachricht selbst ist
    # Best-Effort (der Ereignis-Kanal schluckt Handler-Fehler).
    from .adapters.version_announce_adapter import announce_on_start
    logger.info("Laufende Version: %s", config.read_version())
    announce_on_start(mqtt_client._global_bus)

    logger.info("----------------------------------------------")
    logger.info("System läuft erfolgreich. Drücken Sie Strg+C zum Beenden.")
    logger.info("----------------------------------------------")
    
    # Hauptthread am Leben erhalten
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Beende Daemon...")
        scheduler.stop_scheduler()
        logger.info("System ordnungsgemäß heruntergefahren. Auf Wiedersehen!")

if __name__ == "__main__":
    main()
