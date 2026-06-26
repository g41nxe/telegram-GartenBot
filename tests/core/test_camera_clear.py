from datetime import datetime, timedelta
from pathlib import Path
from src.daemon import scheduler, config


def _make_history(cam_dir: Path, count: int):
    """Legt `count` Historienbilder (photo_*.jpg) plus eine latest.jpg an."""
    cam_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    for i in range(count):
        dt = now - timedelta(hours=i)
        p = cam_dir / f"photo_{dt.strftime('%Y%m%d_%H%M%S')}.jpg"
        p.write_text("dummy")
    (cam_dir / "latest.jpg").write_text("dummy")


def test_clear_deletes_history_keeps_latest(tmp_path):
    """Alle photo_*.jpg werden gelöscht, latest.jpg bleibt erhalten, Rückgabe = Anzahl gelöschter Bilder."""
    config.CAMERA_IMAGE_DIR = str(tmp_path)
    cam_dir = tmp_path / "Garten"
    _make_history(cam_dir, 3)

    deleted = scheduler.clear_camera_history("Garten")

    assert deleted == 3
    assert list(cam_dir.glob("photo_*.jpg")) == [], "Alle Historienbilder sollten gelöscht sein"
    assert (cam_dir / "latest.jpg").exists(), "latest.jpg sollte erhalten bleiben"


def test_clear_missing_dir_returns_zero(tmp_path):
    """Ein fehlendes Kamera-Verzeichnis liefert 0 ohne Fehler."""
    config.CAMERA_IMAGE_DIR = str(tmp_path)

    assert scheduler.clear_camera_history("GibtEsNicht") == 0


def test_clear_leaves_other_cameras_untouched(tmp_path):
    """Bilder anderer Garten-Kameras bleiben unberührt."""
    config.CAMERA_IMAGE_DIR = str(tmp_path)
    _make_history(tmp_path / "Garten", 2)
    _make_history(tmp_path / "Terrasse", 4)

    scheduler.clear_camera_history("Garten")

    assert list((tmp_path / "Terrasse").glob("photo_*.jpg")), "Terrasse-Bilder sollten erhalten bleiben"


def test_count_history_does_not_delete(tmp_path):
    """count_camera_history zählt die Historienbilder ohne zu löschen."""
    config.CAMERA_IMAGE_DIR = str(tmp_path)
    cam_dir = tmp_path / "Garten"
    _make_history(cam_dir, 5)

    count = scheduler.count_camera_history("Garten")

    assert count == 5
    assert len(list(cam_dir.glob("photo_*.jpg"))) == 5, "Zählen darf nichts löschen"


def test_count_missing_dir_returns_zero(tmp_path):
    """Ein fehlendes Verzeichnis liefert beim Zählen 0."""
    config.CAMERA_IMAGE_DIR = str(tmp_path)

    assert scheduler.count_camera_history("GibtEsNicht") == 0


def test_clear_continues_on_unlink_error(tmp_path, monkeypatch):
    """Schlägt das Löschen einer Datei fehl, läuft die Funktion weiter und zählt nur erfolgreiche Löschungen."""
    config.CAMERA_IMAGE_DIR = str(tmp_path)
    cam_dir = tmp_path / "Garten"
    _make_history(cam_dir, 2)

    def boom(self):
        raise OSError("permission denied")
    monkeypatch.setattr(Path, "unlink", boom)

    deleted = scheduler.clear_camera_history("Garten")

    assert deleted == 0
    assert len(list(cam_dir.glob("photo_*.jpg"))) == 2, "Bei Fehler bleiben die Dateien erhalten"
