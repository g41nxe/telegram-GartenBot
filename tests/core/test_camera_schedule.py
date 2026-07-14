"""Tests für src/daemon/core/camera_schedule.py — reine Core-Funktionen, keine I/O."""
from datetime import datetime, timedelta
import pytest
from src.daemon.core import camera_schedule


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _schedule(time_str, duration_minutes, is_active=1, name="Test-Zeitplan"):
    return {"time": time_str, "duration_minutes": duration_minutes, "is_active": is_active, "name": name}


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
# next_photo_target
# ===========================================================================

class TestNextPhotoTarget:
    def test_kein_ziel_gibt_none(self):
        """Keine Zeitpläne, keine festen Zeiten → None."""
        result = camera_schedule.next_photo_target(_now(10, 0), [], [], OFFSET)
        assert result is None

    def test_guss_ziel_korrekte_aufnahmezeit(self):
        """Zeitplan 10:00, 8 min Dauer, Offset 2 → Aufnahmezeit 10:10."""
        result = camera_schedule.next_photo_target(
            _now(9, 50), [_schedule("10:00", 8, name="Rasen")], [], OFFSET
        )
        assert result is not None
        target_dt, label = result
        assert target_dt.hour == 10 and target_dt.minute == 10

    def test_guss_ziel_label_typ_und_name(self):
        """Guss-Ziel → label['type'] == 'guss', label['name'] == Zeitplan-Name."""
        result = camera_schedule.next_photo_target(
            _now(9, 50), [_schedule("10:00", 8, name="Rasen")], [], OFFSET
        )
        assert result is not None
        _, label = result
        assert label["type"] == "guss"
        assert label["name"] == "Rasen"

    def test_fixes_ziel_label_typ(self):
        """Feste Fotozeit → label['type'] == 'fix'."""
        result = camera_schedule.next_photo_target(
            _now(10, 0), [], [_photo_time("10:30")], OFFSET
        )
        assert result is not None
        target_dt, label = result
        assert label["type"] == "fix"
        assert target_dt.hour == 10 and target_dt.minute == 30

    def test_fruehere_von_mehreren_gewinnt(self):
        """Guss-Ziel (10:10) vs. feste Zeit (10:05) → feste Zeit (früher) gewinnt."""
        result = camera_schedule.next_photo_target(
            _now(10, 0),
            [_schedule("10:00", 8, name="Rasen")],   # target 10:10
            [_photo_time("10:05")],                   # target 10:05
            OFFSET,
        )
        assert result is not None
        target_dt, label = result
        assert label["type"] == "fix"
        assert target_dt.minute == 5

    def test_inaktiver_zeitplan_kein_guss_ziel(self):
        """Inaktiver Zeitplan erzeugt kein Guss-Ziel."""
        result = camera_schedule.next_photo_target(
            _now(9, 50), [_schedule("10:00", 8, is_active=0)], [], OFFSET
        )
        assert result is None

    def test_vergangenes_ziel_heute_nimmt_morgen(self):
        """Vergangene feste Zeit heute → morgen gleiche Zeit wird zurückgegeben."""
        result = camera_schedule.next_photo_target(
            _now(10, 0), [], [_photo_time("09:00")], OFFSET
        )
        assert result is not None
        target_dt, _ = result
        assert target_dt.date() == (_now(10, 0) + timedelta(days=1)).date()


# ── Feature 0041: Zustellung nach Aufnahme-Verzug ────────────────────────────

class TestFaelligerAufnahmeZeitpunkt:
    """Ein Aufnahme-Zeitpunkt wird vom ersten Bild NACH ihm erfuellt (ADR 0040)."""

    def test_verspaeteter_upload_erfuellt_den_zeitpunkt(self):
        """Der reale Bug: Upload 28 Minuten nach 08:00 gehoert zum 08:00-Zeitpunkt."""
        now = datetime(2026, 7, 13, 8, 28, 59)
        photo_times = [{"id": 1, "time": "08:00"}, {"id": 2, "time": "20:00"}]

        result = camera_schedule.faelliger_aufnahme_zeitpunkt(now, [], photo_times, 2)

        assert result is not None, "Ein um 28 min verspaeteter Upload muss den 08:00-Zeitpunkt erfuellen"
        target_dt, caption, _label = result
        assert target_dt == datetime(2026, 7, 13, 8, 0)
        assert "08:00" in caption

    def test_zeitpunkt_des_vortags_bleibt_ueber_mitternacht_offen(self):
        """Der 20:00-Zeitpunkt wird erst vom 08:00-Zeitpunkt abgeloest — nicht von Mitternacht."""
        now = datetime(2026, 7, 13, 0, 8, 54)
        photo_times = [{"id": 1, "time": "08:00"}, {"id": 2, "time": "20:00"}]

        result = camera_schedule.faelliger_aufnahme_zeitpunkt(now, [], photo_times, 2)

        assert result is not None, "Nach Mitternacht ist der 20:00-Zeitpunkt des Vortags noch offen"
        assert result[0] == datetime(2026, 7, 12, 20, 0)

    def test_letzter_zeitpunkt_bleibt_offen_bis_sein_nachfolger_faellig_wird(self):
        """Regel A: Mit nur einer Fotozeit loest erst der 08:00 von heute den 08:00 von gestern ab."""
        now = datetime(2026, 7, 13, 6, 0)
        photo_times = [{"id": 1, "time": "08:00"}]

        result = camera_schedule.faelliger_aufnahme_zeitpunkt(now, [], photo_times, 2)

        assert result is not None
        assert result[0] == datetime(2026, 7, 12, 8, 0)

    def test_ohne_aufnahme_zeitpunkte_ist_nichts_faellig(self):
        now = datetime(2026, 7, 13, 6, 0)

        assert camera_schedule.faelliger_aufnahme_zeitpunkt(now, [], [], 2) is None


class TestBeschriftungMitVerzug:
    """Weicht die Aufnahmezeit nennenswert ab, nennt die Beschriftung sie (ADR 0040, Punkt 4)."""

    def test_puenktlich_bleibt_die_beschriftung_unveraendert(self):
        target = datetime(2026, 7, 14, 20, 0)
        captured = datetime(2026, 7, 14, 20, 0, 14)

        text = camera_schedule.beschriftung_mit_verzug("📷 Foto um 20:00", target, captured, 5)

        assert text == "📷 Foto um 20:00"

    def test_verzug_ueber_schwelle_nennt_die_aufnahmezeit(self):
        target = datetime(2026, 7, 13, 8, 0)
        captured = datetime(2026, 7, 13, 8, 28, 59)

        text = camera_schedule.beschriftung_mit_verzug("📷 Foto um 08:00", target, captured, 5)

        assert text == "📷 Foto um 08:00 · aufgenommen 08:28"

    def test_verzug_ueber_tageswechsel_nennt_auch_das_datum(self):
        """Ein Bild vom Folgetag darf nicht wie eines vom selben Morgen aussehen."""
        target = datetime(2026, 7, 12, 20, 0)
        captured = datetime(2026, 7, 13, 0, 8, 54)

        text = camera_schedule.beschriftung_mit_verzug("📷 Foto um 20:00", target, captured, 5)

        assert text == "📷 Foto um 20:00 · aufgenommen 13.07. um 00:08"
