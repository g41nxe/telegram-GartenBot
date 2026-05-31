import time
import logging
import sys
from . import config, database, mqtt_client, scheduler, telegram_bot

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
        
    # 3. Zeitpläne/Scheduler starten
    logger.info("Initialisiere Bewässerungs-Scheduler...")
    scheduler.start_scheduler()
    
    # 4. Telegram-Bot starten
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
