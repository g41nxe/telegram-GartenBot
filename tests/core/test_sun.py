"""Tests für src/daemon/core/sun.py — reine Sonnenstands-Rechnung, keine I/O."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.daemon.core import sun


BERLIN = ZoneInfo("Europe/Berlin")
LAT, LON = 52.52, 13.405          # Berlin-Mitte
SVALBARD_LAT, SVALBARD_LON = 78.22, 15.65


def _minuten(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


# ===========================================================================
# sun_times
# ===========================================================================

class TestSunTimes:
    def test_sommersonnenwende_berlin(self):
        """21.06.2026, Berlin: Aufgang ~04:43, Untergang ~21:33 (MESZ)."""
        aufgang, untergang = sun.sun_times(date(2026, 6, 21), LAT, LON, tz=BERLIN)

        assert abs(_minuten(aufgang) - (4 * 60 + 43)) <= 3
        assert abs(_minuten(untergang) - (21 * 60 + 33)) <= 3

    def test_wintersonnenwende_berlin(self):
        """21.12.2026, Berlin: Aufgang ~08:15, Untergang ~15:53 (MEZ)."""
        aufgang, untergang = sun.sun_times(date(2026, 12, 21), LAT, LON, tz=BERLIN)

        assert abs(_minuten(aufgang) - (8 * 60 + 15)) <= 3
        assert abs(_minuten(untergang) - (15 * 60 + 53)) <= 3

    def test_rueckgabe_ist_naive_lokale_wanduhrzeit(self):
        """camera_schedule rechnet in naiver lokaler Wanduhrzeit — sun_times liefert dieselbe."""
        aufgang, untergang = sun.sun_times(date(2026, 6, 21), LAT, LON, tz=BERLIN)

        assert aufgang.tzinfo is None
        assert untergang.tzinfo is None
        assert aufgang.date() == date(2026, 6, 21)

    def test_sommerzeit_umstellung_wird_beruecksichtigt(self):
        """Der Tag vor und nach der Umstellung unterscheidet sich um rund eine Stunde."""
        vor = sun.sun_times(date(2026, 3, 28), LAT, LON, tz=BERLIN)[0]      # MEZ
        nach = sun.sun_times(date(2026, 3, 29), LAT, LON, tz=BERLIN)[0]     # MESZ

        # Naive Wanduhrzeit springt um ~1 h vor (abzüglich ~2 min echter Tagesdrift).
        assert 55 <= _minuten(nach) - _minuten(vor) <= 62

    def test_polartag_liefert_none(self):
        """Spitzbergen im Juni: Die Sonne geht nicht unter — kein Auf-/Untergang bestimmbar."""
        assert sun.sun_times(date(2026, 6, 21), SVALBARD_LAT, SVALBARD_LON, tz=BERLIN) is None

    def test_polarnacht_liefert_none(self):
        """Spitzbergen im Dezember: Die Sonne geht nicht auf."""
        assert sun.sun_times(date(2026, 12, 21), SVALBARD_LAT, SVALBARD_LON, tz=BERLIN) is None

    def test_ohne_zeitzone_wird_utc_gerechnet(self):
        """Ohne tz bleibt das Ergebnis UTC-Wanduhrzeit — Aufgang am 21.06. gegen 02:43 UTC."""
        aufgang, _ = sun.sun_times(date(2026, 6, 21), LAT, LON, tz=None)

        assert abs(_minuten(aufgang) - (2 * 60 + 43)) <= 3


# ===========================================================================
# daylight_predicate
# ===========================================================================

class TestDaylightPredicate:
    def test_mittags_ist_hell(self):
        ist_hell = sun.daylight_predicate(LAT, LON, margin_minutes=30, tz=BERLIN)

        assert ist_hell(datetime(2026, 6, 21, 12, 0)) is True

    def test_mitternacht_ist_dunkel(self):
        ist_hell = sun.daylight_predicate(LAT, LON, margin_minutes=30, tz=BERLIN)

        assert ist_hell(datetime(2026, 6, 21, 1, 0)) is False

    def test_puffer_verschiebt_die_grenze_nach_innen(self):
        """Der Puffer verlangt echtes Licht, nicht bloß den Moment des Aufgangs."""
        ist_hell = sun.daylight_predicate(LAT, LON, margin_minutes=30, tz=BERLIN)
        aufgang, untergang = sun.sun_times(date(2026, 6, 21), LAT, LON, tz=BERLIN)

        from datetime import timedelta
        assert ist_hell(aufgang + timedelta(minutes=10)) is False
        assert ist_hell(aufgang + timedelta(minutes=40)) is True
        assert ist_hell(untergang - timedelta(minutes=10)) is False
        assert ist_hell(untergang - timedelta(minutes=40)) is True

    def test_ohne_puffer_gilt_der_reine_sonnenstand(self):
        ist_hell = sun.daylight_predicate(LAT, LON, margin_minutes=0, tz=BERLIN)
        aufgang, _ = sun.sun_times(date(2026, 6, 21), LAT, LON, tz=BERLIN)

        from datetime import timedelta
        assert ist_hell(aufgang + timedelta(minutes=1)) is True
        assert ist_hell(aufgang - timedelta(minutes=1)) is False

    def test_winterabend_ist_dunkel(self):
        """21:30 im Dezember — im Sommer hell, im Winter längst dunkel."""
        ist_hell = sun.daylight_predicate(LAT, LON, margin_minutes=30, tz=BERLIN)

        assert ist_hell(datetime(2026, 6, 21, 20, 30)) is True
        assert ist_hell(datetime(2026, 12, 21, 20, 30)) is False

    def test_polartag_gilt_als_hell(self):
        """Ohne Untergang ist es durchgehend hell — nicht durchgehend dunkel."""
        ist_hell = sun.daylight_predicate(SVALBARD_LAT, SVALBARD_LON, 30, tz=BERLIN)

        assert ist_hell(datetime(2026, 6, 21, 2, 0)) is True

    def test_polarnacht_gilt_als_dunkel(self):
        ist_hell = sun.daylight_predicate(SVALBARD_LAT, SVALBARD_LON, 30, tz=BERLIN)

        assert ist_hell(datetime(2026, 12, 21, 12, 0)) is False

    def test_puffer_groesser_als_der_tag_laesst_nichts_uebrig(self):
        """Ein Puffer, der den kurzen Wintertag aufzehrt, meldet durchgehend dunkel —
        statt die Grenzen zu vertauschen und alles für hell zu erklären."""
        ist_hell = sun.daylight_predicate(LAT, LON, margin_minutes=300, tz=BERLIN)

        assert ist_hell(datetime(2026, 12, 21, 12, 0)) is False
