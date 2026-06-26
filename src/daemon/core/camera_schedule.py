"""Reine Core-Funktionen für getimte Kamera-Aufnahmen.

Keine I/O. Eingaben kommen vom camera_receiver-Adapter (DB-Abfragen),
Ausgaben sind skalare Werte oder Optional[str].
"""
from datetime import datetime, timedelta


def _guss_targets(now: datetime, schedules: list, after_offset_minutes: int):
    """Liefert (target_dt, caption) für alle aktiven Zeitpläne heute und morgen."""
    targets = []
    for s in schedules:
        if not s.get("is_active", 1):
            continue
        h, m = map(int, s["time"].split(":"))
        duration = s["duration_minutes"]
        for day_offset in (0, 1):
            base = now.replace(hour=h, minute=m, second=0, microsecond=0)
            base += timedelta(days=day_offset)
            target = base + timedelta(minutes=duration + after_offset_minutes)
            caption = f"📷 Nach dem Guss um {h:02d}:{m:02d}"
            targets.append((target, caption))
    return targets


def _absolute_targets(now: datetime, photo_times: list):
    """Liefert (target_dt, caption) für alle absoluten Foto-Uhrzeiten heute und morgen."""
    targets = []
    for pt in photo_times:
        h, m = map(int, pt["time"].split(":"))
        for day_offset in (0, 1):
            base = now.replace(hour=h, minute=m, second=0, microsecond=0)
            base += timedelta(days=day_offset)
            caption = f"📷 Foto um {h:02d}:{m:02d}"
            targets.append((base, caption))
    return targets


def compute_next_sleep_seconds(
    now: datetime,
    schedules: list,
    photo_times: list,
    interval_seconds: int,
    after_offset_minutes: int,
) -> int:
    """Berechnet die optimale Schlafdauer für die Kamera.

    Gibt Min(interval_seconds, Sekunden_bis_nächsten_Aufnahme_Zeitpunkt) zurück.
    Minimum 60 Sekunden (Kamera-Constraint).
    """
    deadline = now + timedelta(seconds=interval_seconds)
    best_seconds = interval_seconds

    all_targets = (
        _guss_targets(now, schedules, after_offset_minutes)
        + _absolute_targets(now, photo_times)
    )

    for target_dt, _ in all_targets:
        if now <= target_dt <= deadline:
            secs = int((target_dt - now).total_seconds())
            if secs < best_seconds:
                best_seconds = secs

    return max(60, best_seconds)


def find_matching_photo_target(
    now: datetime,
    schedules: list,
    photo_times: list,
    after_offset_minutes: int,
    tolerance_minutes: int,
) -> str | None:
    """Prüft, ob 'now' innerhalb des Toleranzfensters eines Aufnahme-Zeitpunkts liegt.

    Gibt die Beschriftung des nächstgelegenen Treffers zurück, oder None.
    """
    window = timedelta(minutes=tolerance_minutes)
    best_delta = None
    best_caption = None

    all_targets = (
        _guss_targets(now, schedules, after_offset_minutes)
        + _absolute_targets(now, photo_times)
    )

    for target_dt, caption in all_targets:
        delta = abs((now - target_dt).total_seconds())
        if delta <= window.total_seconds():
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_caption = caption

    return best_caption
