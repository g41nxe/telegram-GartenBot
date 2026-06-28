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

def _post_send_message(url: str, payload: dict) -> bool:
    """Sendet ein sendMessage-Payload; True bei HTTP 200. Wirft bei HTTP-/Netzfehler."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.status == 200


def _telegram_error_detail(e: "urllib.error.HTTPError") -> str:
    """Liest die genaue Telegram-Fehlerbeschreibung aus dem Antwort-Body.

    Telegram liefert bei 400 ein JSON wie {"description": "Bad Request: can't parse
    entities: ..."} — diese Beschreibung ist der eigentliche Anhaltspunkt und geht
    sonst hinter dem nichtssagenden „HTTP Error 400: Bad Request" verloren.
    """
    try:
        body = e.read().decode("utf-8", "replace")
        return json.loads(body).get("description") or body or str(e)
    except Exception:
        return str(e)


def _text_preview(text: str, limit: int = 160) -> str:
    """Einzeilige, gekürzte Vorschau des Nachrichtentexts fürs Logging."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


# Telegram begrenzt sendMessage auf 4096 UTF-16-Einheiten. Wir teilen knapp darunter.
TELEGRAM_TEXT_LIMIT = 4000


def _utf16_len(s: str) -> int:
    """Länge in UTF-16-Einheiten — so zählt Telegram (Emojis = 2)."""
    return len(s.encode("utf-16-le")) // 2


def _split_message(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list:
    """Teilt langen Text an Zeilengrenzen in Stücke ≤ limit (UTF-16). Hält Markdown-Zeilen intakt."""
    chunks, current = [], ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if current and _utf16_len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
        while _utf16_len(current) > limit:   # einzelne überlange Zeile hart zerlegen (selten)
            chunks.append(current[:limit])
            current = current[limit:]
    if current:
        chunks.append(current)
    return chunks


def send_message(chat_id: int, text: str, reply_markup: dict = None) -> bool:
    """Sendet eine Textnachricht (mit optionaler Tastatur) über die Telegram-API.

    Lange Nachrichten (> Telegram-Limit) werden an Zeilengrenzen in mehrere Nachrichten
    aufgeteilt; die Tastatur hängt an der letzten. Schlägt der Markdown-Versand eines
    Teilstücks mit HTTP 400 fehl, wird es ohne Formatierung erneut gesendet.
    """
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram Bot Token nicht konfiguriert. Nachricht wird nicht gesendet.")
        return False

    chunks = _split_message(text) if _utf16_len(text) > TELEGRAM_TEXT_LIMIT else [text]
    if len(chunks) > 1:
        logger.info(f"Nachricht an {chat_id} zu lang ({_utf16_len(text)} Zeichen) — in {len(chunks)} Teile aufgeteilt.")
    last = len(chunks) - 1
    ok = True
    for i, chunk in enumerate(chunks):
        ok = _send_chunk(chat_id, chunk, reply_markup if i == last else None) and ok
    return ok


def _send_chunk(chat_id: int, text: str, reply_markup: dict = None) -> bool:
    """Sendet ein einzelnes (bereits längen-begrenztes) Nachrichten-Teilstück inkl. Klartext-Fallback."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    preview = _text_preview(text)
    try:
        return _post_send_message(url, payload)
    except urllib.error.HTTPError as e:
        detail = _telegram_error_detail(e)
        if e.code == 400:
            logger.warning(
                f"Telegram lehnte Markdown-Nachricht an {chat_id} ab (HTTP 400). "
                f"Grund: {detail} | Nachricht: \"{preview}\" — sende ohne Formatierung erneut."
            )
            payload.pop("parse_mode", None)
            try:
                ok = _post_send_message(url, payload)
                if ok:
                    logger.info(f"Klartext-Fallback an {chat_id} erfolgreich zugestellt.")
                return ok
            except urllib.error.HTTPError as e2:
                logger.error(
                    f"Klartext-Fallback an {chat_id} ebenfalls abgelehnt (HTTP {e2.code}). "
                    f"Grund: {_telegram_error_detail(e2)} | Nachricht: \"{preview}\""
                )
                return False
            except Exception as e2:
                logger.error(f"Klartext-Fallback an {chat_id} fehlgeschlagen: {e2} | Nachricht: \"{preview}\"")
                return False
        logger.error(
            f"Fehler beim Senden der Telegram-Nachricht an {chat_id} (HTTP {e.code}). "
            f"Grund: {detail} | Nachricht: \"{preview}\""
        )
        return False
    except Exception as e:
        logger.error(f"Fehler beim Senden der Telegram-Nachricht an {chat_id}: {e} | Nachricht: \"{preview}\"")
        return False

def send_photo(chat_id: int, image_bytes: bytes, caption: str = None) -> bool:
    """Sendet ein PNG-Bild per Multipart-Upload an einen Telegram-Chat."""
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram Bot Token nicht konfiguriert. Foto wird nicht gesendet.")
        return False

    import email.mime.multipart
    import email.mime.base
    import email.encoders
    import io

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto"

    boundary = b"----TelegramBoundary"
    body_parts = []

    def add_field(name: str, value: str):
        body_parts.append(
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="' + name.encode() + b'"\r\n\r\n'
            + value.encode("utf-8") + b"\r\n"
        )

    add_field("chat_id", str(chat_id))
    if caption:
        add_field("caption", caption)
        add_field("parse_mode", "Markdown")

    body_parts.append(
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="photo"; filename="chart.png"\r\n'
        b"Content-Type: image/png\r\n\r\n"
        + image_bytes + b"\r\n"
    )
    body_parts.append(b"--" + boundary + b"--\r\n")

    body = b"".join(body_parts)

    try:
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary.decode()}"},
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status == 200
    except Exception as e:
        logger.error(f"Fehler beim Senden des Fotos an {chat_id}: {e}")
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

def send_chat_action(chat_id: int, action: str) -> None:
    """Sendet eine Chat-Aktion (z.B. 'typing') an Telegram."""
    if not config.TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendChatAction"
    payload = {"chat_id": chat_id, "action": action}
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception as e:
        logger.debug(f"send_chat_action fehlgeschlagen: {e}")


def set_my_commands(commands: list) -> None:
    """Registriert die Bot-Befehle im nativen Telegram-Befehlsmenü."""
    if not config.TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/setMyCommands"
    payload = {"commands": commands}
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
        logger.info("Telegram-Befehlsmenü registriert.")
    except Exception as e:
        logger.error(f"set_my_commands fehlgeschlagen: {e}")


def broadcast_notification(message: str, reply_markup: dict = None):
    """Sendet eine Push-Meldung an alle bekannten autorisierten Benutzer.

    Optionales reply_markup hängt ein Inline-Keyboard an (z. B. Guss-Vorwarnung)."""
    for user_id in config.TELEGRAM_ALLOWED_USER_IDS:
        active_chats.add(user_id)
    for chat_id in active_chats:
        send_message(chat_id, message, reply_markup)

def broadcast_photo(image_bytes: bytes, caption: str = None):
    """Sendet ein PNG-Bild an alle bekannten autorisierten Benutzer."""
    for user_id in config.TELEGRAM_ALLOWED_USER_IDS:
        active_chats.add(user_id)
    for chat_id in active_chats:
        send_photo(chat_id, image_bytes, caption)

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
