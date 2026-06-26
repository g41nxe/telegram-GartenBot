"""Tests für src/daemon/core/camera_schedule.py — reine Core-Funktionen, keine I/O."""
from datetime import datetime
import pytest
from src.daemon.core import camera_schedule


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _schedule(time_str, duration_minutes, is_active=1):
    return {"time": time_str, "duration_minutes": duration_minutes, "is_active": is_active}


def _photo_time(time_str):
    return {"time": time_str}


def _now(h, m, s=0):
    return datetime(2026, 6, 26, h, m, s)


INTERVAL = 900  # 15 Minuten als Basis-Intervall für die meisten Tests
OFFSET = 2      # Nach-Guss-Offset
TOLERANCE = 5   # Toleranzfenster


# ===========================================================================
# compute_next_sleep_seconds
# ===========================================================================

class TestComputeNextSleepSeconds:
    def test_kein_ziel_gibt_volles_intervall(self):
        """Ohne aktive Zeitpläne und ohne Foto-Uhrzeiten → volles Intervall."""
        result = camera_schedule.compute_next_sleep_seconds(
            _now(10, 0), [], [], INTERVAL, OFFSET
        )
        assert result == INTERVAL

    def test_absolutes_ziel_in_reichweite(self):
        """Absolute Foto-Uhrzeit in 10 Minuten → sleep = 600 s."""
        result = camera_schedule.compute_next_sleep_seconds(
            _now(10, 0), [], [_photo_time("10:10")], INTERVAL, OFFSET
        )
        assert result == 600

    def test_guss_ziel_start_plus_dauer_plus_offset(self):
        """Zeitplan 10:00, 8 min Dauer, Offset 2 → Ziel 10:10 → sleep = 600 s."""
        result = camera_schedule.compute_next_sleep_seconds(
            _now(10, 0), [_schedule("10:00", 8)], [], INTERVAL, OFFSET
        )
        assert result == 600  # 10 Minuten = 600 s

    def test_deckelung_durch_intervall(self):
        """Ziel weit in der Zukunft → sleep = Intervall (Deckelung)."""
        result = camera_schedule.compute_next_sleep_seconds(
            _now(10, 0), [], [_photo_time("11:00")], INTERVAL, OFFSET
        )
        assert result == INTERVAL

    def test_mehrere_ziele_kleinster_wert_gewinnt(self):
        """Mehrere Ziele → das nächste (kleinste sleep) gewinnt."""
        result = camera_schedule.compute_next_sleep_seconds(
            _now(10, 0),
            [_schedule("10:00", 8)],   # Ziel 10:10 → 600 s
            [_photo_time("10:05")],    # Ziel 10:05 → 300 s
            INTERVAL, OFFSET
        )
        assert result == 300

    def test_inaktiver_zeitplan_wird_ignoriert(self):
        """Inaktiver Zeitplan darf kein Ziel erzeugen."""
        result = camera_schedule.compute_next_sleep_seconds(
            _now(10, 0), [_schedule("10:00", 8, is_active=0)], [], INTERVAL, OFFSET
        )
        assert result == INTERVAL

    def test_minimum_60_sekunden(self):
        """sleep darf nie unter 60 Sekunden fallen (Kamera-Constraint)."""
        result = camera_schedule.compute_next_sleep_seconds(
            _now(10, 0), [], [_photo_time("10:00")], INTERVAL, OFFSET
        )
        assert result >= 60

    def test_ziel_in_vergangenheit_wird_ignoriert(self):
        """Ziel, das in der Vergangenheit liegt, wird nicht zurückgegeben."""
        # Absolute Uhrzeit 09:00 liegt vor jetzt (10:00) → kein Ziel heute mehr
        # Nächstes Ziel wäre morgen → außerhalb Intervall → volles Intervall
        result = camera_schedule.compute_next_sleep_seconds(
            _now(10, 0), [], [_photo_time("09:00")], INTERVAL, OFFSET
        )
        assert result == INTERVAL

    def test_tagesgrenze_ziel_morgen(self):
        """Absolute Uhrzeit 00:05 bei jetzt 23:50 → ca. 15 Minuten → sleep = 900 s (Intervall klein)."""
        interval = 1800  # 30 Minuten
        result = camera_schedule.compute_next_sleep_seconds(
            _now(23, 50), [], [_photo_time("00:05")], interval, OFFSET
        )
        assert result == 15 * 60  # 15 Minuten = 900 s

    def test_genau_auf_ziel_gibt_minimum(self):
        """now == Ziel genau → sleep = 60 s (Minimum)."""
        result = camera_schedule.compute_next_sleep_seconds(
            _now(10, 10), [], [_photo_time("10:10")], INTERVAL, OFFSET
        )
        assert result == 60


# ===========================================================================
# find_matching_photo_target
# ===========================================================================

class TestFindMatchingPhotoTarget:
    def test_kein_treffer_gibt_none(self):
        """Kein Aufnahme-Zeitpunkt nahe 'now' → None."""
        result = camera_schedule.find_matching_photo_target(
            _now(10, 0), [], [], OFFSET, TOLERANCE
        )
        assert result is None

    def test_absolutes_ziel_genau_getroffen(self):
        """now == absolutes Ziel → Treffer mit Beschriftung '📷 Foto um 10:00'."""
        result = camera_schedule.find_matching_photo_target(
            _now(10, 0), [], [_photo_time("10:00")], OFFSET, TOLERANCE
        )
        assert result == "📷 Foto um 10:00"

    def test_absolutes_ziel_innerhalb_toleranz_vor(self):
        """now = Ziel − 3 min → innerhalb Toleranz → Treffer."""
        result = camera_schedule.find_matching_photo_target(
            _now(9, 57), [], [_photo_time("10:00")], OFFSET, TOLERANCE
        )
        assert result is not None

    def test_absolutes_ziel_innerhalb_toleranz_nach(self):
        """now = Ziel + 4 min → innerhalb Toleranz → Treffer."""
        result = camera_schedule.find_matching_photo_target(
            _now(10, 4), [], [_photo_time("10:00")], OFFSET, TOLERANCE
        )
        assert result is not None

    def test_absolutes_ziel_ausserhalb_toleranz(self):
        """now = Ziel + 6 min → außerhalb Toleranz → None."""
        result = camera_schedule.find_matching_photo_target(
            _now(10, 6), [], [_photo_time("10:00")], OFFSET, TOLERANCE
        )
        assert result is None

    def test_guss_ziel_beschriftung(self):
        """Treffer durch Zeitplan → Beschriftung enthält Guss-Startzeit."""
        # Zeitplan 10:00, 8 min Dauer → Ziel 10:10 → now = 10:10
        result = camera_schedule.find_matching_photo_target(
            _now(10, 10), [_schedule("10:00", 8)], [], OFFSET, TOLERANCE
        )
        assert result == "📷 Nach dem Guss um 10:00"

    def test_mehrere_treffer_naechster_gewinnt(self):
        """Mehrere Aufnahme-Zeitpunkte im Toleranzfenster → nächstgelegener gewinnt."""
        # Zwei absolute Zeiten: 10:00 (Δ = 0 min) und 09:58 (Δ = 2 min)
        result = camera_schedule.find_matching_photo_target(
            _now(10, 0),
            [],
            [_photo_time("10:00"), _photo_time("09:58")],
            OFFSET, TOLERANCE
        )
        assert result == "📷 Foto um 10:00"

    def test_absolut_und_guss_beide_im_fenster(self):
        """Absolutes Ziel und Guss-Ziel im Fenster → nächstgelegener gewinnt."""
        # now = 10:10; Guss-Ziel = 10:10 (Δ=0); Absolut 10:08 (Δ=2 min)
        result = camera_schedule.find_matching_photo_target(
            _now(10, 10),
            [_schedule("10:00", 8)],   # Ziel 10:10
            [_photo_time("10:08")],    # Ziel 10:08 (Δ=2 min)
            OFFSET, TOLERANCE
        )
        assert result == "📷 Nach dem Guss um 10:00"

    def test_inaktiver_zeitplan_kein_treffer(self):
        """Inaktiver Zeitplan darf kein Matching erzeugen."""
        result = camera_schedule.find_matching_photo_target(
            _now(10, 10), [_schedule("10:00", 8, is_active=0)], [], OFFSET, TOLERANCE
        )
        assert result is None
