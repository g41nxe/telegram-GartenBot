import logging
from . import telegram_client, telegram_ui

logger = logging.getLogger("garden_telegram_bot_façade")

def start_bot():
    """Initialisiert und startet den Telegram-Bot."""
    telegram_client.register_update_callback(telegram_ui.on_telegram_update)
    telegram_client.start_polling()
    logger.info("Telegram-Bot-System (entkoppelter Client & UI-Controller) erfolgreich initialisiert.")

def broadcast_notification(message: str):
    """Sendet eine Push-Meldung an alle bekannten autorisierten Benutzer."""
    telegram_client.broadcast_notification(message)
