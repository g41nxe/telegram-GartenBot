import json
import logging
import urllib.request
import urllib.error
import threading
import time
from .. import config

logger = logging.getLogger("garden_telegram_client")

active_chats = set()
on_update_callback = None

def register_update_callback(callback_fn):
    """Registriert das callback zur Verarbeitung von eingehenden Nachrichten/Callback Queries."""
    global on_update_callback
    on_update_callback = callback_fn

def send_message(chat_id: int, text: str, reply_markup: dict = None) -> bool:
    """Sendet eine Textnachricht (mit optionaler Tastatur) über die Telegram-API."""
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram Bot Token nicht konfiguriert. Nachricht wird nicht gesendet.")
        return False
        
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
        
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status == 200
    except Exception as e:
        logger.error(f"Fehler beim Senden der Telegram-Nachricht an {chat_id}: {e}")
        return False

def edit_message_text(chat_id: int, message_id: int, text: str, reply_markup: dict = None) -> bool:
    """Editiert den Text einer bestehenden Nachricht."""
    if not config.TELEGRAM_BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status == 200
    except Exception as e:
        logger.error(f"Fehler beim Editieren der Nachricht {message_id} für {chat_id}: {e}")
        return False

def answer_callback_query(callback_query_id: str, text: str = None, show_alert: bool = False):
    """Quittiert einen Inline-Button-Klick in Telegram, damit das 'Sanduhr'-Laden verschwindet."""
    if not config.TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    payload = {
        "callback_query_id": callback_query_id
    }
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = True
        
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:
        logger.error(f"Fehler beim Quittieren der Callback-Query: {e}")

def broadcast_notification(message: str):
    """Sendet eine Push-Meldung an alle bekannten autorisierten Benutzer."""
    # Füge standardmäßig die erlaubten User-IDs zu den aktiven Chats hinzu
    for user_id in config.TELEGRAM_ALLOWED_USER_IDS:
        active_chats.add(user_id)
        
    for chat_id in active_chats:
        send_message(chat_id, message)

def _polling_loop():
    """Hintergrund-Long-Polling-Schleife zur Abfrage neuer Nachrichten."""
    logger.info("Telegram-Polling gestartet.")
    offset = 0
    
    while True:
        if not config.TELEGRAM_BOT_TOKEN:
            logger.error("Kein Telegram Bot Token konfiguriert. Polling ausgesetzt.")
            time.sleep(10)
            continue
            
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates?offset={offset}&timeout=30"
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'GardenIrrigationDaemon/1.0'})
            with urllib.request.urlopen(req, timeout=35) as response:
                result = json.loads(response.read().decode("utf-8"))
                
            if not result.get("ok"):
                logger.error(f"Fehlerantwort von Telegram-API: {result}")
                time.sleep(5)
                continue
                
            updates = result.get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                
                # Prüfe Absender (Security Whitelist)
                msg_obj = update.get("message")
                cb_obj = update.get("callback_query")
                
                sender_id = None
                if msg_obj:
                    sender_id = msg_obj["from"]["id"]
                elif cb_obj:
                    sender_id = cb_obj["from"]["id"]
                    
                if sender_id not in config.TELEGRAM_ALLOWED_USER_IDS:
                    logger.warning(f"Unautorisierter Zugriff von User-ID {sender_id} blockiert!")
                    continue
                    
                # Chat ID merken
                active_chats.add(sender_id)
                
                # An registrierten Controller weiterleiten
                if on_update_callback:
                    try:
                        on_update_callback(msg_obj, cb_obj)
                    except Exception as e:
                        logger.error(f"Fehler im Telegram-Update-Callback: {e}")
                        
        except urllib.error.URLError as e:
            logger.debug(f"Verbindungsfehler im Telegram-Polling: {e}")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Unerwarteter Fehler im Telegram-Polling: {e}")
            time.sleep(5)

def start_polling():
    """Startet den long-polling loop Thread."""
    t = threading.Thread(target=_polling_loop, daemon=True)
    t.start()
    logger.info("Telegram-Bot-Client (Transport) im Hintergrund gestartet.")
