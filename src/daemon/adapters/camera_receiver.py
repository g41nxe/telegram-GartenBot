import time
import json
import shutil
import logging
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from pathlib import Path

from src.daemon import config
from src.daemon.adapters import database
from src.daemon.core.event_bus import EventBus
from src.daemon.core.camera_events import CameraImageReceived, CameraRegistered

logger = logging.getLogger("garden_camera_receiver")

_global_bus = None

class CameraHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/register":
            self.handle_register()
        elif parsed_path.path == "/upload":
            self.handle_upload()
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/config":
            self.handle_config()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Unterdrücke die Standardausgabe der HTTP-Requests für ein saubereres Log
        pass

    def handle_register(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 1024 or content_length == 0:
            self.send_response(400)
            self.end_headers()
            return
            
        post_data = self.rfile.read(content_length)
        
        try:
            body = post_data.decode('utf-8').strip()
            if body.startswith("{"):
                data = json.loads(body)
                mac = data.get("mac", "")
            else:
                mac = body
        except Exception:
            self.send_response(400)
            self.end_headers()
            return

        if not mac:
            self.send_response(400)
            self.end_headers()
            return
            
        # 1. Ist die Kamera bereits registriert? -> Idempotent
        camera = database.get_camera(mac)
        if camera:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            return
            
        # 2. Prüfe Koppel-Metadaten in der DB
        is_active = database.get_metadata("camera_pairing_active")
        if is_active != "1":
            self.send_response(403)
            self.end_headers()
            return
            
        expires_at_str = database.get_metadata("camera_pairing_expires_at")
        try:
            expires_at = float(expires_at_str)
        except (TypeError, ValueError):
            expires_at = 0
            
        if time.time() > expires_at:
            self.send_response(403)
            self.end_headers()
            return
            
        # Erfolgreich registrieren
        wish_name = database.get_metadata("camera_pairing_wish_name")
        if not wish_name:
            wish_name = f"camera_{mac[-4:]}"
            
        success = database.add_camera(mac, wish_name)
        if success:
            if _global_bus:
                _global_bus.publish(CameraRegistered(mac, wish_name))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(500)
            self.end_headers()

    def handle_config(self):
        mac = self.headers.get("X-Camera-MAC")
        if not mac:
            self.send_response(400)
            self.end_headers()
            return
            
        camera = database.get_camera(mac)
        if not camera:
            self.send_response(403)
            self.end_headers()
            return
            
        settings = {
            "sleep_duration_seconds": camera.get("sleep_duration_seconds", 900),
            "resolution": camera.get("resolution", "XGA"),
            "quality": camera.get("quality", 10)
        }
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(settings).encode('utf-8'))

    def handle_upload(self):
        mac = self.headers.get("X-Camera-MAC")
        if not mac:
            self.send_response(400)
            self.end_headers()
            return
            
        camera = database.get_camera(mac)
        if not camera:
            self.send_response(403)
            self.end_headers()
            return
            
        content_length = int(self.headers.get('Content-Length', 0))
        max_bytes = getattr(config, 'CAMERA_MAX_UPLOAD_BYTES', 512000)
        if content_length > max_bytes or content_length == 0:
            self.send_response(400)
            self.end_headers()
            return
            
        payload = self.rfile.read(content_length)
        
        # Validierung: JPEG Magic Bytes (\xFF\xD8) am Anfang
        if len(payload) < 2 or payload[0] != 0xFF or payload[1] != 0xD8:
            logger.warning(f"Kamera Upload abgelehnt: Ungültige JPEG Magic Bytes von MAC {mac}")
            self.send_response(400)
            self.end_headers()
            return
            
        battery_header = self.headers.get("X-Battery-Level")
        battery = None
        if battery_header is not None:
            try:
                battery = int(float(battery_header))
                if not (0 <= battery <= 100):
                    battery = None
            except ValueError:
                battery = None
        database.update_camera_on_upload(mac, battery=battery)
        wish_name = camera.get("wish_name", "unknown")
        
        now = datetime.now()
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        filename = f"photo_{timestamp_str}.jpg"
        
        base_dir = Path(config.CAMERA_IMAGE_DIR)
        cam_dir = base_dir / wish_name
        cam_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = cam_dir / filename
        with open(file_path, "wb") as f:
            f.write(payload)
            
        # Kopie als latest.jpg ablegen
        latest_path = cam_dir / "latest.jpg"
        shutil.copy2(file_path, latest_path)

        logger.info(f"Bild von Kamera \"{wish_name}\" empfangen: {len(payload)} Bytes ({filename})")

        if _global_bus:
            _global_bus.publish(CameraImageReceived(mac, wish_name, str(file_path)))
            
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

_server_instance = None


def run_server(httpd):
    logger.info(f"Kamera-HTTP-Server lauscht auf Port {httpd.server_address[1]}")
    try:
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"Kamera-HTTP-Server Fehler: {e}")


def initialize(event_bus: EventBus):
    """Startet den HTTP-Server für die Kameras in einem Hintergrund-Thread.

    Gibt (port, thread) zurück. Port 0 lässt das OS einen freien Port wählen
    (nützlich in Tests). shutdown() muss im teardown aufgerufen werden.
    """
    global _global_bus, _server_instance
    _global_bus = event_bus

    port = getattr(config, 'CAMERA_RECEIVER_PORT', 8080)
    httpd = HTTPServer(('0.0.0.0', port), CameraHTTPRequestHandler)
    httpd.socket.settimeout(5.0)
    _server_instance = httpd

    bound_port = httpd.server_address[1]
    t = threading.Thread(target=run_server, args=(httpd,), daemon=True)
    t.start()
    return bound_port, t


def shutdown():
    """Fährt den HTTP-Server sauber herunter. In Tests im teardown aufrufen."""
    global _server_instance
    if _server_instance:
        _server_instance.shutdown()
        _server_instance = None
