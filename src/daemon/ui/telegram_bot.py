import logging
from . import telegram_client, telegram_ui
from .. import scheduler

logger = logging.getLogger("garden_telegram_bot_façade")

def start_bot():
    """Initialisiert und startet den Telegram-Bot."""
    # 1. Registriere das Update-Routing vom Client (Transport) zum UI-Controller (Präsentation)
    telegram_client.register_update_callback(telegram_ui.on_telegram_update)
    
    # 2. Verbinde den Scheduler mit dem Client-Broadcaster für Legacy-Push-Nachrichten
    scheduler.register_notification_callback(telegram_client.broadcast_notification)
    
    # 3. Starte den Long-Polling-Verbindungsprozess im Hintergrund
    telegram_client.start_polling()
    logger.info("Telegram-Bot-System (entkoppelter Client & UI-Controller) erfolgreich initialisiert.")

def broadcast_notification(message: str):
    """Sendet eine Push-Meldung an alle bekannten autorisierten Benutzer."""
    telegram_client.broadcast_notification(message)
