import pytest
import time
import logging
import urllib.request
import urllib.error
import json
import os
import tempfile
import shutil
from src.daemon.adapters import camera_receiver, database
from src.daemon.core.event_bus import EventBus
from src.daemon import config

@pytest.fixture
def test_db():
    temp_db = tempfile.NamedTemporaryFile(delete=False)
    temp_db.close()

    orig_path = database.DB_PATH
    database.DB_PATH = temp_db.name
    database.init_db()

    yield

    database.DB_PATH = orig_path
    os.unlink(temp_db.name)

@pytest.fixture
def event_bus():
    return EventBus()

@pytest.fixture
def running_server(test_db, event_bus):
    config.CAMERA_RECEIVER_PORT = 18080
    temp_dir = tempfile.mkdtemp()
    config.CAMERA_IMAGE_DIR = temp_dir

    port, server = camera_receiver.initialize(event_bus)
    time.sleep(0.3)

    yield port

    camera_receiver.shutdown()
    shutil.rmtree(temp_dir)

def test_register_camera(running_server):
    database.set_metadata("camera_pairing_active", "1")
    database.set_metadata("camera_pairing_wish_name", "TestCam")
    database.set_metadata("camera_pairing_expires_at", str(time.time() + 90))

    url = f"http://127.0.0.1:{running_server}/register"
    req = urllib.request.Request(url, data=b"AA:BB:CC:DD:EE:FF", method="POST")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        assert resp.read() == b"OK"

    cam = database.get_camera("AA:BB:CC:DD:EE:FF")
    assert cam is not None
    assert cam["wish_name"] == "TestCam"

def test_config_endpoint(running_server):
    database.add_camera("11:22:33", "MyCam")
    url = f"http://127.0.0.1:{running_server}/config"
    req = urllib.request.Request(url, headers={"X-Camera-MAC": "11:22:33"}, method="GET")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read())
        assert "sleep_duration_seconds" in data
        assert data["sleep_duration_seconds"] == 900

def test_upload_image(running_server):
    database.add_camera("AA:BB:CC", "UploadCam")
    url = f"http://127.0.0.1:{running_server}/upload"

    payload = b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00'
    req = urllib.request.Request(url, headers={"X-Camera-MAC": "AA:BB:CC", "Content-Type": "image/jpeg"}, data=payload, method="POST")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        assert resp.read() == b"OK"

    latest_path = os.path.join(config.CAMERA_IMAGE_DIR, "UploadCam", "latest.jpg")
    assert os.path.exists(latest_path)

def test_upload_logs_success(running_server, caplog):
    """Ein erfolgreicher Upload schreibt eine INFO-Log-Zeile mit Kamera-Name und Bildgröße."""
    database.add_camera("DD:EE:FF", "LogCam")
    url = f"http://127.0.0.1:{running_server}/upload"
    payload = b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00'

    with caplog.at_level(logging.INFO, logger="garden_camera_receiver"):
        req = urllib.request.Request(
            url,
            headers={"X-Camera-MAC": "DD:EE:FF", "Content-Type": "image/jpeg"},
            data=payload,
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200

    messages = [r.getMessage() for r in caplog.records if r.name == "garden_camera_receiver"]
    assert any("LogCam" in m and str(len(payload)) in m for m in messages), \
        f"Erwartete Upload-Log-Zeile fehlt, gesehen: {messages}"

def test_upload_rejected_when_exceeds_config_limit(running_server):
    """Upload > CAMERA_MAX_UPLOAD_BYTES wird mit 400 abgelehnt (nicht 2-MB-Hardcode)."""
    original_limit = getattr(config, 'CAMERA_MAX_UPLOAD_BYTES', 2 * 1024 * 1024)
    config.CAMERA_MAX_UPLOAD_BYTES = 100
    try:
        database.add_camera("EE:FF:00:11:22:33", "LimitCam")
        url = f"http://127.0.0.1:{running_server}/upload"
        payload = b'\xFF\xD8' + b'\x00' * 200  # 202 Bytes > Limit 100
        req = urllib.request.Request(
            url,
            headers={"X-Camera-MAC": "EE:FF:00:11:22:33"},
            data=payload,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req):
                pytest.fail("Erwartet HTTP-Fehler, Upload wurde akzeptiert")
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        config.CAMERA_MAX_UPLOAD_BYTES = original_limit


def test_upload_speichert_akkustand(running_server):
    """X-Battery-Level Header wird beim Upload in der DB gespeichert."""
    database.add_camera("BA:BB:CC:DD:EE:FF", "AkkuCam")
    url = f"http://127.0.0.1:{running_server}/upload"
    payload = b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00'
    req = urllib.request.Request(
        url,
        headers={"X-Camera-MAC": "BA:BB:CC:DD:EE:FF", "X-Battery-Level": "78"},
        data=payload,
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200

    cam = database.get_camera("BA:BB:CC:DD:EE:FF")
    assert cam["battery"] == 78


def test_upload_ohne_akkuheader_behaelt_wert(running_server):
    """Fehlt X-Battery-Level, bleibt der gespeicherte Wert unverändert."""
    database.add_camera("CA:BB:CC:DD:EE:FF", "NoBatCam")
    database.update_camera_on_upload("CA:BB:CC:DD:EE:FF", battery=55)

    url = f"http://127.0.0.1:{running_server}/upload"
    payload = b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00'
    req = urllib.request.Request(
        url,
        headers={"X-Camera-MAC": "CA:BB:CC:DD:EE:FF"},
        data=payload,
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200

    cam = database.get_camera("CA:BB:CC:DD:EE:FF")
    assert cam["battery"] == 55
