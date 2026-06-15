import os
import time
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from src.daemon import scheduler, config

def test_cleanup_camera_photos(tmp_path):
    config.CAMERA_IMAGE_DIR = str(tmp_path)
    config.CAMERA_CLEANUP_DAYS = 30
    
    cam_dir = tmp_path / "TestCam"
    cam_dir.mkdir()
    
    now = datetime.now()
    
    # 1. Sehr altes Foto vor 12 Uhr -> wird gelöscht
    old_dt1 = now - timedelta(days=40)
    old_dt1 = old_dt1.replace(hour=10, minute=0, second=0)
    p1 = cam_dir / f"photo_{old_dt1.strftime('%Y%m%d_%H%M%S')}.jpg"
    p1.write_text("dummy")
    
    # 2. Sehr altes Foto nach 12 Uhr -> wird behalten (Zeitraffer-Bild des Tages)
    old_dt2 = now - timedelta(days=40)
    old_dt2 = old_dt2.replace(hour=13, minute=0, second=0)
    p2 = cam_dir / f"photo_{old_dt2.strftime('%Y%m%d_%H%M%S')}.jpg"
    p2.write_text("dummy")
    
    # 3. Kürzliches Foto -> wird behalten
    recent_dt = now - timedelta(days=10)
    p3 = cam_dir / f"photo_{recent_dt.strftime('%Y%m%d_%H%M%S')}.jpg"
    p3.write_text("dummy")
    
    # 4. latest.jpg -> wird behalten
    p4 = cam_dir / "latest.jpg"
    p4.write_text("dummy")
    
    scheduler.cleanup_camera_photos()
    
    assert not p1.exists(), "Altes Foto vor 12 Uhr sollte gelöscht sein"
    assert p2.exists(), "Erstes altes Foto nach 12 Uhr sollte als Zeitraffer-Bild behalten werden"
    assert p3.exists(), "Neueres Foto sollte behalten werden"
    assert p4.exists(), "latest.jpg sollte behalten werden"
