import time
import logging
import sys
from . import config, scheduler
from .adapters import database, mqtt_client
from .ui import telegram_bot

# Zentrales Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("garden_main")

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
        
    # 2. MQTT-Client starten
    logger.info("Initialisiere MQTT-Dienst...")
    if not mqtt_client.start_client():
        logger.warning("MQTT-Dienst konnte nicht gestartet werden. Prüfen Sie Ihren Broker.")
        
    # 3. Ereignis-Kanal & Guss-Steuerung initialisieren und verdrahten (IoC)
    logger.info("Initialisiere Ereignis-Kanal & Guss-Steuerung...")
    from .core.watering_controller import WateringController
    from .adapters.database_adapter import DatabaseLoggerAdapter
    
    # Erzeuge Guss-Steuerung und weise sie dem Scheduler zu (Fassaden-Kopplung)
    watering_ctrl = WateringController(mqtt_client._global_bus, mqtt_client.client_instance.publish)
    scheduler.controller = watering_ctrl
    
    # Initialisiere den DB-Logger Adapter zur Event-Archivierung
    db_adapter = DatabaseLoggerAdapter(mqtt_client._global_bus)
        
    # 4. Inaktivitäts-Watchdog initialisieren
    from .adapters import watchdog
    watchdog.initialize()

    # 5. Zeitpläne/Scheduler starten
    logger.info("Initialisiere Bewässerungs-Scheduler...")
    scheduler.start_scheduler()
    
    # 6. Telegram-Bot starten
    logger.info("Initialisiere Telegram-Bot...")
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning(
            "TELEGRAM_BOT_TOKEN ist nicht in .env konfiguriert. "
            "Der Bot steht nicht zur Verfügung!"
        )
    else:
        telegram_bot.start_bot()
        
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
