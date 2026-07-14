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


# ===========================================================================
# Getimte Kamera-Aufnahmen — Feature 0030
# ===========================================================================

JPEG_PAYLOAD = b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00'


def test_config_gibt_dynamische_schlafdauer_bei_foto_uhrzeit(running_server):
    """/config gibt eine kürzere Schlafdauer zurück, wenn eine Foto-Uhrzeit bald ansteht."""
    database.add_camera("FC:00:01:02:03:04", "TimeCam")
    # Kamera hat Intervall 900 s; Foto-Uhrzeit in 5 Minuten
    from datetime import datetime, timedelta
    from src.daemon import config as cfg
    target = datetime.now() + timedelta(minutes=5)
    time_str = target.strftime("%H:%M")
    database.add_photo_time(time_str)

    url = f"http://127.0.0.1:{running_server}/config"
    req = urllib.request.Request(url, headers={"X-Camera-MAC": "FC:00:01:02:03:04"}, method="GET")
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    sleep = data["sleep_duration_seconds"]
    # Muss kürzer als Intervall (900) sein, mindestens 60 s
    assert 60 <= sleep < 900


def test_upload_innerhalb_toleranz_publiziert_timed_photo(running_server, event_bus):
    """/upload innerhalb des Toleranzfensters einer Foto-Uhrzeit → TimedPhotoCaptured."""
    from datetime import datetime
    from src.daemon.core.camera_events import TimedPhotoCaptured

    database.add_camera("FC:00:AA:BB:CC:DD", "TolCam")

    # Foto-Uhrzeit = jetzt (Upload fällt genau ins Fenster)
    now = datetime.now()
    database.add_photo_time(now.strftime("%H:%M"))

    captured = []
    event_bus.subscribe(TimedPhotoCaptured, captured.append)

    url = f"http://127.0.0.1:{running_server}/upload"
    req = urllib.request.Request(
        url,
        headers={"X-Camera-MAC": "FC:00:AA:BB:CC:DD"},
        data=JPEG_PAYLOAD,
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200

    assert len(captured) == 1
    assert captured[0].wish_name == "TolCam"
    assert "Foto um" in captured[0].caption


def test_doppel_upload_im_selben_fenster_nur_ein_timed_photo(running_server, event_bus):
    """Zwei Uploads derselben Kamera im selben Toleranzfenster → nur EIN TimedPhotoCaptured (Dedup)."""
    from datetime import datetime
    from src.daemon.core.camera_events import TimedPhotoCaptured

    database.add_camera("DE:DU:PE:00:00:01", "DupCam")
    now = datetime.now()
    database.add_photo_time(now.strftime("%H:%M"))

    captured = []
    event_bus.subscribe(TimedPhotoCaptured, captured.append)

    url = f"http://127.0.0.1:{running_server}/upload"
    for _ in range(2):
        req = urllib.request.Request(
            url,
            headers={"X-Camera-MAC": "DE:DU:PE:00:00:01"},
            data=JPEG_PAYLOAD,
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200

    assert len(captured) == 1, f"Erwartet genau 1 TimedPhotoCaptured (Dedup), war {len(captured)}"


def test_zwei_kameras_im_selben_fenster_je_ein_timed_photo(running_server, event_bus):
    """Zwei verschiedene Kameras im selben Fenster → je ein TimedPhotoCaptured (Dedup ist pro MAC)."""
    from datetime import datetime
    from src.daemon.core.camera_events import TimedPhotoCaptured

    database.add_camera("CA:M1:00:00:00:01", "CamEins")
    database.add_camera("CA:M2:00:00:00:02", "CamZwei")
    now = datetime.now()
    database.add_photo_time(now.strftime("%H:%M"))

    captured = []
    event_bus.subscribe(TimedPhotoCaptured, captured.append)

    url = f"http://127.0.0.1:{running_server}/upload"
    for mac in ("CA:M1:00:00:00:01", "CA:M2:00:00:00:02"):
        req = urllib.request.Request(
            url,
            headers={"X-Camera-MAC": mac},
            data=JPEG_PAYLOAD,
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200

    assert len(captured) == 2, f"Erwartet ein Foto je Kamera, war {len(captured)}"
    assert {e.wish_name for e in captured} == {"CamEins", "CamZwei"}


def test_upload_vor_dem_aufnahme_zeitpunkt_erfuellt_ihn_nicht(running_server, event_bus):
    """Ein Bild VOR dem Aufnahme-Zeitpunkt erfüllt ihn nicht (ADR 0040).

    Die Kamera wacht bauartbedingt bis zu 60 s zu früh auf; ein Bild vor dem Nach-Offset
    könnte das Beet mitten im Guss zeigen. Sie wacht kurz darauf ohnehin erneut auf.
    """
    from datetime import datetime, timedelta
    from src.daemon.core import camera_schedule
    from src.daemon.core.camera_events import TimedPhotoCaptured

    database.add_camera("FC:00:EE:FF:00:11", "NoCam")

    # Einziger Aufnahme-Zeitpunkt liegt 10 Minuten in der Zukunft
    target = datetime.now() + timedelta(minutes=10)
    database.add_photo_time(target.strftime("%H:%M"))

    # Alles, was jetzt schon faellig ist (der gleichnamige Zeitpunkt des Vortags), gilt als
    # zugestellt — nicht von Hand ausgerechnet, sonst kippt der Test um Mitternacht.
    bereits_faellig = camera_schedule.faelliger_aufnahme_zeitpunkt(
        datetime.now(), database.get_schedules(), database.get_photo_times(),
        config.CAMERA_AFTER_GUSS_OFFSET_MINUTES,
    )
    assert bereits_faellig is not None
    database.set_metadata(
        "last_delivered_target:FC:00:EE:FF:00:11", bereits_faellig[0].isoformat()
    )

    captured = []
    event_bus.subscribe(TimedPhotoCaptured, captured.append)

    url = f"http://127.0.0.1:{running_server}/upload"
    req = urllib.request.Request(
        url,
        headers={"X-Camera-MAC": "FC:00:EE:FF:00:11"},
        data=JPEG_PAYLOAD,
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200

    assert len(captured) == 0


def test_ohne_aufnahme_zeitpunkt_keine_zustellung(running_server, event_bus):
    """Reguläre Intervall-Bilder werden nicht zugestellt (CONTEXT.md: Aufnahme-Zeitpunkt)."""
    from src.daemon.core.camera_events import TimedPhotoCaptured

    database.add_camera("FC:00:EE:FF:00:22", "IntervalCam")

    captured = []
    event_bus.subscribe(TimedPhotoCaptured, captured.append)

    url = f"http://127.0.0.1:{running_server}/upload"
    req = urllib.request.Request(
        url,
        headers={"X-Camera-MAC": "FC:00:EE:FF:00:22"},
        data=JPEG_PAYLOAD,
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200

    assert len(captured) == 0


# ── Feature 0041: Zustellung nach Aufnahme-Verzug (ADR 0040) ─────────────────

def test_verspaeteter_upload_wird_zugestellt(running_server, event_bus):
    """Der reale Bug: Ein Upload 28 Minuten nach dem Aufnahme-Zeitpunkt muss zugestellt werden.

    Am 13.07.2026 kam das Bild zum 08:00-Zeitpunkt um 08:28:59 an und wurde still verworfen,
    weil es das +-5-Minuten-Fenster verfehlte. 5 von 7 getimten Fotos gingen so verloren.
    """
    from datetime import datetime, timedelta
    from src.daemon.core.camera_events import TimedPhotoCaptured

    database.add_camera("FC:00:VE:RZ:UG:01", "VerzugCam")

    # Aufnahme-Zeitpunkt lag vor 28 Minuten
    target = datetime.now() - timedelta(minutes=28)
    database.add_photo_time(target.strftime("%H:%M"))

    captured = []
    event_bus.subscribe(TimedPhotoCaptured, captured.append)

    url = f"http://127.0.0.1:{running_server}/upload"
    req = urllib.request.Request(
        url,
        headers={"X-Camera-MAC": "FC:00:VE:RZ:UG:01"},
        data=JPEG_PAYLOAD,
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200

    assert len(captured) == 1, "Ein um 28 min verspaetetes Bild muss den Aufnahme-Zeitpunkt erfuellen"
    assert "aufgenommen" in captured[0].caption, "Die Beschriftung muss die echte Aufnahmezeit nennen"


def test_zwei_namenlose_zeitplaene_liefern_zwei_guss_fotos(running_server, event_bus):
    """Alter Dedup-Schluessel war `Datum|Beschriftung` — zwei namenlose Zeitplaene kollidierten,
    das zweite Guss-Foto des Tages wurde still verschluckt. Der Ziel-Zeitstempel ist eindeutig.
    """
    from datetime import datetime, timedelta
    from src.daemon.core.camera_events import TimedPhotoCaptured

    database.add_camera("FC:00:DU:PL:00:99", "GussCam")
    now = datetime.now()

    # Zwei namenlose Zeitplaene, deren Aufnahme-Zeitpunkte 40 bzw. 10 Minuten zurueckliegen.
    # Aufnahme-Zeitpunkt = Startzeit + Dauer + Nach-Offset (2 min), Dauer hier 0.
    for minuten_her in (40, 10):
        start = now - timedelta(minutes=minuten_her + 2)
        database.add_schedule("", start.strftime("%H:%M"), "mo,di,mi,do,fr,sa,so", 0)

    captured = []
    event_bus.subscribe(TimedPhotoCaptured, captured.append)

    url = f"http://127.0.0.1:{running_server}/upload"
    for _ in range(2):
        req = urllib.request.Request(
            url,
            headers={"X-Camera-MAC": "FC:00:DU:PL:00:99"},
            data=JPEG_PAYLOAD,
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200

    # Beide Uploads liegen nach dem juengeren Zeitpunkt -> dieser wird genau einmal erfuellt.
    assert len(captured) == 1
    assert captured[0].target_dt is not None


def test_geloeschte_fotozeit_belebt_keinen_alten_zeitpunkt(running_server, event_bus):
    """Nach dem Loeschen einer Fotozeit darf kein aelterer Aufnahme-Zeitpunkt neu zustellen.

    Der Vergleich muss lauten 'juenger als der zuletzt zugestellte', nicht 'ungleich' —
    sonst wird ein laengst bedienter Zeitpunkt wieder faellig und stellt ein veraltetes Bild zu.
    """
    from datetime import datetime, timedelta
    from src.daemon.core.camera_events import TimedPhotoCaptured

    mac = "FC:00:AL:T0:00:01"
    database.add_camera(mac, "AltCam")
    now = datetime.now()

    # Fotozeit, die vor 2 Stunden faellig war — sie wurde bereits zugestellt.
    frueher = (now - timedelta(hours=2)).replace(second=0, microsecond=0)
    zuletzt = (now - timedelta(minutes=30)).replace(second=0, microsecond=0)
    database.set_metadata(f"last_delivered_target:{mac}", zuletzt.isoformat())
    database.add_photo_time(frueher.strftime("%H:%M"))

    captured = []
    event_bus.subscribe(TimedPhotoCaptured, captured.append)

    url = f"http://127.0.0.1:{running_server}/upload"
    req = urllib.request.Request(
        url, headers={"X-Camera-MAC": mac}, data=JPEG_PAYLOAD, method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200

    assert len(captured) == 0, "Ein aelterer Aufnahme-Zeitpunkt als der zuletzt zugestellte darf nicht zustellen"
