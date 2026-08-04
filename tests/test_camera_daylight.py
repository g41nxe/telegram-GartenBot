"""Tests für src/daemon/camera_daylight.py — die Naht zwischen Konfiguration und Kern."""
from datetime import datetime

import pytest

from src.daemon import camera_daylight, config


BERLIN_LAT, BERLIN_LON = 52.52, 13.405


@pytest.fixture
def berlin(monkeypatch):
    monkeypatch.setattr(config, "LATITUDE", BERLIN_LAT)
    monkeypatch.setattr(config, "LONGITUDE", BERLIN_LON)
    monkeypatch.setattr(config, "TIMEZONE", "Europe/Berlin")
    monkeypatch.setattr(config, "CAMERA_DAYLIGHT_MARGIN_MINUTES", 30)
    monkeypatch.setattr(config, "CAMERA_DAYLIGHT_FILTER_TYPES", frozenset({"guss", "fix"}))


class TestLocalTz:
    def test_gueltige_zeitzone(self, berlin):
        assert camera_daylight.local_tz() is not None

    def test_unbekannte_zeitzone_faellt_auf_naiv_zurueck(self, monkeypatch, caplog):
        """Ein Tippfehler in der Konfiguration darf den Daemon nicht abschießen."""
        monkeypatch.setattr(config, "TIMEZONE", "Europa/Berlin")

        assert camera_daylight.local_tz() is None
        assert any("Europa/Berlin" in r.getMessage() for r in caplog.records)


class TestPhotoAllowed:
    def test_ohne_koordinaten_kein_filter(self, monkeypatch):
        """Vorgabe 0.0/0.0 ist der Golf von Guinea — dann lieber gar nicht filtern."""
        monkeypatch.setattr(config, "LATITUDE", 0.0)
        monkeypatch.setattr(config, "LONGITUDE", 0.0)

        assert camera_daylight.build_photo_filter() is None

    def test_leere_typmenge_kein_filter(self, berlin, monkeypatch):
        monkeypatch.setattr(config, "CAMERA_DAYLIGHT_FILTER_TYPES", frozenset())

        assert camera_daylight.build_photo_filter() is None

    def test_halb_gesetzte_koordinaten_schalten_ab(self, berlin, monkeypatch, caplog):
        """LATITUDE gesetzt, LONGITUDE vergessen → der Ort laege auf dem Nullmeridian.

        Das Fenster waere um Stunden verschoben: Fotos am hellen Tag unterdrueckt, naechtliche
        durchgelassen — genau das Gegenteil des Gewollten. Lieber gar nicht filtern.
        """
        monkeypatch.setattr(config, "LONGITUDE", 0.0)

        assert camera_daylight.build_photo_filter() is None
        assert any("Unvollständige Koordinaten" in r.getMessage() for r in caplog.records)

    def test_unbrauchbare_zeitzone_schaltet_ab(self, berlin, monkeypatch, caplog):
        """Ohne Zeitzone rechnete `sun` in UTC, die Aufnahme-Zeitpunkte sind aber Ortszeit."""
        monkeypatch.setattr(config, "TIMEZONE", "Europa/Berlin")

        assert camera_daylight.build_photo_filter() is None
        assert any("Tageslicht-Filter bleibt aus" in r.getMessage() for r in caplog.records)

    def test_unbekannter_typwert_warnt_bleibt_aber_wirksam(self, berlin, monkeypatch, caplog):
        """Ein Tippfehler wie `fest` statt `fix` verengt den Filter stillschweigend — daher Warnung."""
        monkeypatch.setattr(
            config, "CAMERA_DAYLIGHT_FILTER_TYPES", frozenset({"guss", "fest"})
        )

        f = camera_daylight.build_photo_filter()

        assert f is not None, "Der gueltige Anteil muss weiter wirken"
        assert f(datetime(2026, 6, 21, 23, 0), {"type": "guss"}) is False
        assert any("unbekannte Werte" in r.getMessage() for r in caplog.records)

    def test_naechtlicher_guss_wird_abgelehnt(self, berlin):
        """22:32 im Juni liegt in Berlin nach Sonnenuntergang (21:33) — kein Foto."""
        f = camera_daylight.build_photo_filter()

        assert f(datetime(2026, 6, 21, 22, 32), {"type": "guss"}) is False

    def test_mittagsguss_wird_zugelassen(self, berlin):
        f = camera_daylight.build_photo_filter()

        assert f(datetime(2026, 6, 21, 12, 32), {"type": "guss"}) is True

    def test_winterabend_wird_abgelehnt(self, berlin):
        """19:00 ist im Juni hell, im Dezember (Untergang 15:53) längst dunkel."""
        f = camera_daylight.build_photo_filter()

        assert f(datetime(2026, 6, 21, 19, 0), {"type": "fix"}) is True
        assert f(datetime(2026, 12, 21, 19, 0), {"type": "fix"}) is False

    def test_typmenge_beschraenkt_den_geltungsbereich(self, berlin, monkeypatch):
        """Nur `guss` konfiguriert → die bewusst gesetzte feste Fotozeit bleibt auch nachts."""
        monkeypatch.setattr(config, "CAMERA_DAYLIGHT_FILTER_TYPES", frozenset({"guss"}))
        f = camera_daylight.build_photo_filter()

        assert f(datetime(2026, 6, 21, 23, 0), {"type": "guss"}) is False
        assert f(datetime(2026, 6, 21, 23, 0), {"type": "fix"}) is True

    def test_puffer_wirkt(self, berlin, monkeypatch):
        """Ohne Puffer ist der Moment kurz nach Sonnenaufgang hell, mit 30 min noch nicht."""
        monkeypatch.setattr(config, "CAMERA_DAYLIGHT_MARGIN_MINUTES", 0)
        ohne_puffer = camera_daylight.build_photo_filter()
        monkeypatch.setattr(config, "CAMERA_DAYLIGHT_MARGIN_MINUTES", 30)
        mit_puffer = camera_daylight.build_photo_filter()

        kurz_nach_aufgang = datetime(2026, 6, 21, 4, 55)  # Aufgang ~04:43
        assert ohne_puffer(kurz_nach_aufgang, {"type": "guss"}) is True
        assert mit_puffer(kurz_nach_aufgang, {"type": "guss"}) is False
