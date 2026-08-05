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

    def test_suedhalbkugel_hat_die_jahreszeit_umgekehrt(self):
        """Sydney (33.87 S), 21.06.2026 — dort Wintersonnenwende: Aufgang ~07:00, Untergang ~16:54.

        Zusammen mit Berlin faengt dieser Fall ein falsches Vorzeichen in sin(phi)*sin(decl):
        beide Orte haben dasselbe Datum, aber gegenlaeufige Tageslaenge.
        """
        sydney = ZoneInfo("Australia/Sydney")
        aufgang, untergang = sun.sun_times(date(2026, 6, 21), -33.87, 151.21, tz=sydney)

        assert abs(_minuten(aufgang) - (7 * 60 + 0)) <= 4
        assert abs(_minuten(untergang) - (16 * 60 + 54)) <= 4

    def test_negativer_laengengrad(self):
        """New York (74.01 W), 21.06.2026: Aufgang ~05:25, Untergang ~20:31 (EDT).

        Faengt ein falsches Vorzeichen in `j_star = n - longitude/360` — Berlin allein
        (oestliche Laenge) wuerde es durchgehen lassen.
        """
        new_york = ZoneInfo("America/New_York")
        aufgang, untergang = sun.sun_times(date(2026, 6, 21), 40.71, -74.01, tz=new_york)

        assert abs(_minuten(aufgang) - (5 * 60 + 25)) <= 4
        assert abs(_minuten(untergang) - (20 * 60 + 31)) <= 4

    def test_aequinoktium_ist_etwas_laenger_als_zwoelf_stunden(self):
        """Zur Tagundnachtgleiche misst der Tag mehr als 12 h — und das ist richtig so.

        Auf- und Untergang gelten, wenn der *obere Rand* der Sonne den Horizont beruehrt, und
        die Refraktion hebt ihn zusaetzlich (`_SUN_DISC_ALTITUDE = -0.833°`). In Berlin macht
        das rund 13 Minuten aus. Ein Ergebnis von exakt 12 h waere ein Zeichen dafuer, dass der
        Sonnendurchmesser unterschlagen wurde.
        """
        aufgang, untergang = sun.sun_times(date(2026, 9, 22), LAT, LON, tz=BERLIN)

        tageslaenge = _minuten(untergang) - _minuten(aufgang)
        assert 12 * 60 + 5 <= tageslaenge <= 12 * 60 + 25

    def test_polartag_liefert_none(self):
        """Spitzbergen im Juni: Die Sonne geht nicht unter — kein Auf-/Untergang bestimmbar."""
        assert sun.sun_times(date(2026, 6, 21), SVALBARD_LAT, SVALBARD_LON, tz=BERLIN) is None

    def test_polarnacht_liefert_none(self):
        """Spitzbergen im Dezember: Die Sonne geht nicht auf."""
        assert sun.sun_times(date(2026, 12, 21), SVALBARD_LAT, SVALBARD_LON, tz=BERLIN) is None

    def test_grosser_zeitzonen_versatz_liefert_den_richtigen_tag(self):
        """Kiritimati (157 W, aber UTC+14): lokales und UT-Datum fallen auseinander.

        Genau hier bricht ein Anker auf 00:00 UT — er berechnete den Bogen des Nachbartags.
        Geprueft wird die Eigenschaft, nicht die Minute: Der Aufgang gehoert zum angefragten
        lokalen Datum und liegt am Morgen, der Untergang am Abend. Aequatornah gilt das
        ganzjaehrig.
        """
        kiritimati = ZoneInfo("Pacific/Kiritimati")
        angefragt = date(2026, 6, 21)

        aufgang, untergang = sun.sun_times(angefragt, 1.87, -157.43, tz=kiritimati)

        assert aufgang.date() == angefragt
        assert untergang.date() == angefragt
        assert 5 * 60 <= _minuten(aufgang) <= 7 * 60 + 30
        assert 17 * 60 + 30 <= _minuten(untergang) <= 19 * 60 + 30

    def test_exakt_am_pol(self):
        """Am Pol selbst wird cos(phi) null — die Deklination entscheidet ueber die Jahreszeit."""
        assert sun.sun_times(date(2026, 6, 21), 90.0, 0.0, tz=BERLIN) is None
        assert sun.sun_times(date(2026, 12, 21), -90.0, 0.0, tz=BERLIN) is None

        nordpol = sun.daylight_predicate(90.0, 0.0, 0, tz=BERLIN)
        assert nordpol(datetime(2026, 6, 21, 3, 0)) is True    # Polartag
        assert nordpol(datetime(2026, 12, 21, 12, 0)) is False  # Polarnacht

        suedpol = sun.daylight_predicate(-90.0, 0.0, 0, tz=BERLIN)
        assert suedpol(datetime(2026, 6, 21, 12, 0)) is False   # dort Polarnacht

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
