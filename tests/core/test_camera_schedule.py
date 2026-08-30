"""Tests für src/daemon/core/camera_schedule.py — reine Core-Funktionen, keine I/O."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
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
# PhotoPlan.sleep_seconds
# ===========================================================================

class TestComputeNextSleepSeconds:
    def test_kein_ziel_gibt_volles_intervall(self):
        """Ohne aktive Zeitpläne und ohne Foto-Uhrzeiten → volles Intervall."""
        result = camera_schedule.PhotoPlan.unfiltered([], [], OFFSET).sleep_seconds(_now(10, 0), INTERVAL)
        assert result == INTERVAL

    def test_absolutes_ziel_in_reichweite(self):
        """Absolute Foto-Uhrzeit in 10 Minuten → sleep = 600 s."""
        result = camera_schedule.PhotoPlan.unfiltered([], [_photo_time("10:10")], OFFSET).sleep_seconds(_now(10, 0), INTERVAL)
        assert result == 600

    def test_guss_ziel_start_plus_dauer_plus_offset(self):
        """Zeitplan 10:00, 8 min Dauer, Offset 2 → Ziel 10:10 → sleep = 600 s."""
        result = camera_schedule.PhotoPlan.unfiltered([_schedule("10:00", 8)], [], OFFSET).sleep_seconds(_now(10, 0), INTERVAL)
        assert result == 600  # 10 Minuten = 600 s

    def test_deckelung_durch_intervall(self):
        """Ziel weit in der Zukunft → sleep = Intervall (Deckelung)."""
        result = camera_schedule.PhotoPlan.unfiltered([], [_photo_time("11:00")], OFFSET).sleep_seconds(_now(10, 0), INTERVAL)
        assert result == INTERVAL

    def test_mehrere_ziele_kleinster_wert_gewinnt(self):
        """Mehrere Ziele → das nächste (kleinste sleep) gewinnt."""
        result = camera_schedule.PhotoPlan.unfiltered([_schedule("10:00", 8)], [_photo_time("10:05")], OFFSET).sleep_seconds(_now(10, 0), INTERVAL)
        assert result == 300

    def test_inaktiver_zeitplan_wird_ignoriert(self):
        """Inaktiver Zeitplan darf kein Ziel erzeugen."""
        result = camera_schedule.PhotoPlan.unfiltered([_schedule("10:00", 8, is_active=0)], [], OFFSET).sleep_seconds(_now(10, 0), INTERVAL)
        assert result == INTERVAL

    def test_minimum_60_sekunden(self):
        """sleep darf nie unter 60 Sekunden fallen (Kamera-Constraint)."""
        result = camera_schedule.PhotoPlan.unfiltered([], [_photo_time("10:00")], OFFSET).sleep_seconds(_now(10, 0), INTERVAL)
        assert result >= 60

    def test_ziel_in_vergangenheit_wird_ignoriert(self):
        """Ziel, das in der Vergangenheit liegt, wird nicht zurückgegeben."""
        # Absolute Uhrzeit 09:00 liegt vor jetzt (10:00) → kein Ziel heute mehr
        # Nächstes Ziel wäre morgen → außerhalb Intervall → volles Intervall
        result = camera_schedule.PhotoPlan.unfiltered([], [_photo_time("09:00")], OFFSET).sleep_seconds(_now(10, 0), INTERVAL)
        assert result == INTERVAL

    def test_tagesgrenze_ziel_morgen(self):
        """Absolute Uhrzeit 00:05 bei jetzt 23:50 → ca. 15 Minuten → sleep = 900 s (Intervall klein)."""
        interval = 1800  # 30 Minuten
        result = camera_schedule.PhotoPlan.unfiltered([], [_photo_time("00:05")], OFFSET).sleep_seconds(_now(23, 50), interval)
        assert result == 15 * 60  # 15 Minuten = 900 s

    def test_genau_auf_ziel_gibt_minimum(self):
        """now == Ziel genau → sleep = 60 s (Minimum)."""
        result = camera_schedule.PhotoPlan.unfiltered([], [_photo_time("10:10")], OFFSET).sleep_seconds(_now(10, 10), INTERVAL)
        assert result == 60


# ===========================================================================
# Sommerzeit-Umstellung (Ticket fok): die Schlafdauer ist die ECHTE verstrichene Zeit
# ===========================================================================

class TestDstSleepSeconds:
    """An den beiden Umstellungstagen ist die naive Wanduhr-Differenz falsch — die Kamera muss
    die tatsächlich verstrichene Zeit schlafen, sonst wacht sie eine Stunde daneben auf."""

    BERLIN = ZoneInfo("Europe/Berlin")

    def test_spring_forward_uses_real_elapsed_seconds(self):
        # 2026-03-29: 02:00 CET -> 03:00 CEST (die Stunde fällt weg).
        # now 01:30, Fotozeit 03:30: Wanduhr-Delta 2 h, ECHT verstrichen nur 1 h.
        now = datetime(2026, 3, 29, 1, 30)
        result = camera_schedule.PhotoPlan.unfiltered([], [_photo_time("03:30")], OFFSET).sleep_seconds(now, 8 * 3600, tz=self.BERLIN)
        assert result == 3600

    def test_fall_back_uses_real_elapsed_seconds(self):
        # 2026-10-25: 03:00 CEST -> 02:00 CET (die Stunde kommt doppelt).
        # now 01:30, Fotozeit 03:30: Wanduhr-Delta 2 h, ECHT verstrichen 3 h.
        now = datetime(2026, 10, 25, 1, 30)
        result = camera_schedule.PhotoPlan.unfiltered([], [_photo_time("03:30")], OFFSET).sleep_seconds(now, 8 * 3600, tz=self.BERLIN)
        assert result == 3 * 3600

    def test_without_tz_stays_naive(self):
        # Ohne tz bleibt es die naive Differenz (Rückwärtskompatibilität, auf Normaltagen gleich).
        now = datetime(2026, 3, 29, 1, 30)
        result = camera_schedule.PhotoPlan.unfiltered([], [_photo_time("03:30")], OFFSET).sleep_seconds(now, 8 * 3600)
        assert result == 2 * 3600

    def test_spring_forward_gate_admits_real_reachable_target(self):
        # Review-Befund: der Ziel-Filter muss die ECHTE Distanz nutzen, nicht die naive.
        # now 01:50 (CET), Ziel 03:00 (CEST): naiv 70 min entfernt, ECHT nur 10 min (600 s) —
        # bei Intervall 900 s reichbar, darf also NICHT verworfen werden (Kamera weckt pünktlich).
        now = datetime(2026, 3, 29, 1, 50)
        result = camera_schedule.PhotoPlan.unfiltered([], [_photo_time("03:00")], OFFSET).sleep_seconds(now, 900, tz=self.BERLIN)
        assert result == 600

    def test_normal_day_identical_with_and_without_tz(self):
        # Kein Umstellungstag: tz-bewusst und naiv liefern dasselbe.
        plan = camera_schedule.PhotoPlan.unfiltered([], [_photo_time("10:10")], OFFSET)
        now = _now(10, 0)
        assert (plan.sleep_seconds(now, INTERVAL, tz=self.BERLIN)
                == plan.sleep_seconds(now, INTERVAL) == 600)


# ===========================================================================
# PhotoPlan.upcoming
# ===========================================================================

class TestNextPhotoTarget:
    def test_kein_ziel_gibt_none(self):
        """Keine Zeitpläne, keine festen Zeiten → None."""
        result = camera_schedule.PhotoPlan.unfiltered([], [], OFFSET).upcoming(_now(10, 0))
        assert result is None

    def test_guss_ziel_korrekte_aufnahmezeit(self):
        """Zeitplan 10:00, 8 min Dauer, Offset 2 → Aufnahmezeit 10:10."""
        result = camera_schedule.PhotoPlan.unfiltered([_schedule("10:00", 8, name="Rasen")], [], OFFSET).upcoming(_now(9, 50))
        assert result is not None
        target_dt, label = result
        assert target_dt.hour == 10 and target_dt.minute == 10

    def test_guss_ziel_label_typ_und_name(self):
        """Guss-Ziel → label['type'] == 'guss', label['name'] == Zeitplan-Name."""
        result = camera_schedule.PhotoPlan.unfiltered([_schedule("10:00", 8, name="Rasen")], [], OFFSET).upcoming(_now(9, 50))
        assert result is not None
        _, label = result
        assert label["type"] == "guss"
        assert label["name"] == "Rasen"

    def test_fixes_ziel_label_typ(self):
        """Feste Fotozeit → label['type'] == 'fix'."""
        result = camera_schedule.PhotoPlan.unfiltered([], [_photo_time("10:30")], OFFSET).upcoming(_now(10, 0))
        assert result is not None
        target_dt, label = result
        assert label["type"] == "fix"
        assert target_dt.hour == 10 and target_dt.minute == 30

    def test_fruehere_von_mehreren_gewinnt(self):
        """Guss-Ziel (10:10) vs. feste Zeit (10:05) → feste Zeit (früher) gewinnt."""
        result = camera_schedule.PhotoPlan.unfiltered([_schedule("10:00", 8, name="Rasen")], [_photo_time("10:05")], OFFSET).upcoming(_now(10, 0))
        assert result is not None
        target_dt, label = result
        assert label["type"] == "fix"
        assert target_dt.minute == 5

    def test_inaktiver_zeitplan_kein_guss_ziel(self):
        """Inaktiver Zeitplan erzeugt kein Guss-Ziel."""
        result = camera_schedule.PhotoPlan.unfiltered([_schedule("10:00", 8, is_active=0)], [], OFFSET).upcoming(_now(9, 50))
        assert result is None

    def test_vergangenes_ziel_heute_nimmt_morgen(self):
        """Vergangene feste Zeit heute → morgen gleiche Zeit wird zurückgegeben."""
        result = camera_schedule.PhotoPlan.unfiltered([], [_photo_time("09:00")], OFFSET).upcoming(_now(10, 0))
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

        result = camera_schedule.PhotoPlan.unfiltered([], photo_times, 2).due(now)

        assert result is not None, "Ein um 28 min verspaeteter Upload muss den 08:00-Zeitpunkt erfuellen"
        target_dt, caption, _label = result
        assert target_dt == datetime(2026, 7, 13, 8, 0)
        assert "08:00" in caption

    def test_zeitpunkt_des_vortags_bleibt_ueber_mitternacht_offen(self):
        """Der 20:00-Zeitpunkt wird erst vom 08:00-Zeitpunkt abgeloest — nicht von Mitternacht."""
        now = datetime(2026, 7, 13, 0, 8, 54)
        photo_times = [{"id": 1, "time": "08:00"}, {"id": 2, "time": "20:00"}]

        result = camera_schedule.PhotoPlan.unfiltered([], photo_times, 2).due(now)

        assert result is not None, "Nach Mitternacht ist der 20:00-Zeitpunkt des Vortags noch offen"
        assert result[0] == datetime(2026, 7, 12, 20, 0)

    def test_letzter_zeitpunkt_bleibt_offen_bis_sein_nachfolger_faellig_wird(self):
        """Regel A: Mit nur einer Fotozeit loest erst der 08:00 von heute den 08:00 von gestern ab."""
        now = datetime(2026, 7, 13, 6, 0)
        photo_times = [{"id": 1, "time": "08:00"}]

        result = camera_schedule.PhotoPlan.unfiltered([], photo_times, 2).due(now)

        assert result is not None
        assert result[0] == datetime(2026, 7, 12, 8, 0)

    def test_ohne_aufnahme_zeitpunkte_ist_nichts_faellig(self):
        now = datetime(2026, 7, 13, 6, 0)

        assert camera_schedule.PhotoPlan.unfiltered([], [], 2).due(now) is None


class TestBeschriftungMitVerzug:
    """Weicht die Aufnahmezeit nennenswert ab, nennt die Beschriftung sie (ADR 0040, Punkt 4)."""

    def test_puenktlich_bleibt_die_beschriftung_unveraendert(self):
        target = datetime(2026, 7, 14, 20, 0)
        captured = datetime(2026, 7, 14, 20, 0, 14)

        text = camera_schedule.caption_with_delay("📷 Foto um 20:00", target, captured, 5)

        assert text == "📷 Foto um 20:00"

    def test_verzug_ueber_schwelle_nennt_die_aufnahmezeit(self):
        target = datetime(2026, 7, 13, 8, 0)
        captured = datetime(2026, 7, 13, 8, 28, 59)

        text = camera_schedule.caption_with_delay("📷 Foto um 08:00", target, captured, 5)

        assert text == "📷 Foto um 08:00 · aufgenommen 08:28"

    def test_verzug_ueber_tageswechsel_nennt_auch_das_datum(self):
        """Ein Bild vom Folgetag darf nicht wie eines vom selben Morgen aussehen."""
        target = datetime(2026, 7, 12, 20, 0)
        captured = datetime(2026, 7, 13, 0, 8, 54)

        text = camera_schedule.caption_with_delay("📷 Foto um 20:00", target, captured, 5)

        assert text == "📷 Foto um 20:00 · aufgenommen 13.07. um 00:08"


class TestNebelZeitplaeneErzeugenKeinGussFoto:
    """Ein Nebel-Intervall ist kein Guss — es darf keinen Aufnahme-Zeitpunkt erzeugen."""

    def _nebel(self, time_str):
        return {"time": time_str, "duration_minutes": 0, "is_active": 1,
                "name": "Terrasse", "mode": "nebel"}

    def test_nebel_intervall_erzeugt_keinen_faelligen_zeitpunkt(self):
        now = datetime(2026, 7, 14, 22, 30)

        result = camera_schedule.PhotoPlan.unfiltered([self._nebel("22:00")], [], 2).due(now)

        assert result is None, "Ein Nebel-Intervall darf kein Guss-Foto ausloesen"

    def test_nebel_intervall_weckt_die_kamera_nicht(self):
        now = datetime(2026, 7, 14, 21, 55)

        sleep = camera_schedule.PhotoPlan.unfiltered([self._nebel("22:00")], [], OFFSET).sleep_seconds(now, INTERVAL)

        assert sleep == INTERVAL, "Fuer ein Nebel-Intervall darf die Kamera nicht geweckt werden"


# ===========================================================================
# Tageslicht-Filter — kein Foto bei Dunkelheit
# ===========================================================================

def _tageslicht(moment):
    """Testdouble statt echter Sonnenstands-Rechnung: hell von 06:00 bis 21:00."""
    return 6 <= moment.hour < 21


class TestDaylightFilter:
    """Der Filter selbst: Welche Aufnahme-Zeitpunkte darf es geben?"""

    def test_dunkler_zeitpunkt_wird_abgelehnt(self):
        f = camera_schedule.daylight_filter(_tageslicht, {"guss", "fix"})

        assert f(_now(12, 0), {"type": "guss"}) is True
        assert f(_now(23, 0), {"type": "guss"}) is False

    def test_nur_konfigurierte_typen_werden_gefiltert(self):
        """Bei `guss` bleibt eine bewusst gesetzte feste Fotozeit auch nachts bestehen."""
        f = camera_schedule.daylight_filter(_tageslicht, {"guss"})

        assert f(_now(23, 0), {"type": "guss"}) is False
        assert f(_now(23, 0), {"type": "fix"}) is True

    def test_leere_typmenge_schaltet_den_filter_ab(self):
        """Keine Typen heißt dasselbe wie kein Filter — nicht ein Prädikat, das alles durchwinkt."""
        assert camera_schedule.daylight_filter(_tageslicht, set()) is None

    def test_ohne_pruefer_kein_filter(self):
        """Fehlen die Koordinaten, liefert die Fabrik None — der Aufrufer filtert dann nicht."""
        assert camera_schedule.daylight_filter(None, {"guss", "fix"}) is None


class TestDunkleAufnahmeZeitpunkteEntfallen:
    """Ein unterdrückter Zeitpunkt existiert für ALLE Verbraucher nicht — sonst würde aus dem
    schwarzen Foto ein Fehlalarm (ADR 0041) oder ein sinnloses Aufwecken der Kamera."""

    def _filter(self, typen={"guss", "fix"}):
        return camera_schedule.daylight_filter(_tageslicht, typen)

    def test_naechtliches_guss_foto_wird_nicht_zugestellt(self):
        """Guss um 22:00, 30 min Dauer → Zeitpunkt 22:32 liegt im Dunkeln."""
        now = datetime(2026, 6, 26, 22, 35)

        result = camera_schedule.PhotoPlan([_schedule("22:00", 30)], [], OFFSET, self._filter()).due(now)

        assert result is None

    def test_taegliches_guss_foto_bleibt(self):
        now = datetime(2026, 6, 26, 10, 35)

        result = camera_schedule.PhotoPlan([_schedule("10:00", 30)], [], OFFSET, self._filter()).due(now)

        assert result is not None
        assert result[0] == datetime(2026, 6, 26, 10, 32)

    def test_kamera_wird_fuer_dunklen_zeitpunkt_nicht_geweckt(self):
        now = datetime(2026, 6, 26, 22, 25)

        sleep = camera_schedule.PhotoPlan([_schedule("22:00", 30)], [], OFFSET, self._filter()).sleep_seconds(now, INTERVAL)

        assert sleep == INTERVAL

    def test_dunkler_zeitpunkt_gilt_nicht_als_verpasst(self):
        """Kein Bild zu einem unterdrückten Zeitpunkt ist der Normalfall, kein Alarm."""
        now = datetime(2026, 6, 27, 8, 0)

        verpasst = camera_schedule.PhotoPlan(
            [_schedule("22:00", 30)],
            [_photo_time("07:00")],
            OFFSET,
            self._filter(),
        ).missed(now, datetime(2026, 6, 26, 12, 0))

        assert verpasst == []

    def test_naechster_zeitpunkt_ueberspringt_die_dunkelheit(self):
        """Um 22:00 ist der nächste sichtbare Zeitpunkt die Fotozeit am Morgen."""
        now = datetime(2026, 6, 26, 22, 0)

        result = camera_schedule.PhotoPlan([_schedule("22:30", 30)], [_photo_time("07:00")], OFFSET, self._filter()).upcoming(now)

        assert result is not None
        assert result[0] == datetime(2026, 6, 27, 7, 0)

    def test_typ_beschraenkung_wirkt_durchgehend(self):
        """Nur Guss-Fotos gefiltert → die feste Fotozeit um 23:00 wird weiter zugestellt."""
        now = datetime(2026, 6, 26, 23, 5)

        result = camera_schedule.PhotoPlan([], [_photo_time("23:00")], OFFSET, self._filter({"guss"})).due(now)

        assert result is not None

    def test_ohne_filter_bleibt_das_verhalten_unveraendert(self):
        now = datetime(2026, 6, 26, 22, 35)

        result = camera_schedule.PhotoPlan.unfiltered([_schedule("22:00", 30)], [], OFFSET).due(now)

        assert result is not None


# ===========================================================================
# PhotoPlan — der Aufnahme-Plan als Typ (Ticket nkl)
# ===========================================================================

class TestPhotoPlan:
    """Der Plan bündelt, was einen Aufnahme-Zeitpunkt ausmacht.

    Vorher reisten (schedules, photo_times, after_offset_minutes, photo_allowed) als
    Klumpen durch fünf Funktionen. Entscheidend ist dabei nicht die Kürze, sondern dass
    der Dunkelheits-Filter nicht mehr stillschweigend weggelassen werden kann: Er hat
    keinen Vorgabewert, der Aufrufer muss sich äußern.
    """

    def _plan(self, photo_allowed, schedules=None, photo_times=None):
        return camera_schedule.PhotoPlan(
            schedules if schedules is not None else [_schedule("10:00", 10)],
            photo_times if photo_times is not None else [],
            OFFSET,
            photo_allowed,
        )

    def test_filter_is_mandatory(self):
        """Ohne Angabe des Filters gibt es keinen Plan — das ist der Kern des Tickets."""
        with pytest.raises(TypeError):
            camera_schedule.PhotoPlan([_schedule("10:00", 10)], [], OFFSET)

    def test_unfiltered_states_the_absence_explicitly(self):
        """`unfiltered()` benennt „kein Filter" als Absicht statt als Versäumnis."""
        plan = camera_schedule.PhotoPlan.unfiltered([_schedule("10:00", 10)], [], OFFSET)
        assert plan.photo_allowed is None
        assert plan.targets(_now(12, 0))

    def test_none_filter_keeps_every_target(self):
        """photo_allowed=None lässt alle Zeitpunkte stehen (Fall ohne Koordinaten)."""
        assert len(self._plan(None).targets(_now(12, 0))) == 3   # Vortag, heute, morgen

    def test_filter_removes_targets(self):
        """Ein ablehnender Filter entfernt die Zeitpunkte für jeden Verbraucher."""
        plan = self._plan(lambda dt, label: False)
        now = _now(12, 0)
        assert plan.targets(now) == []
        assert plan.due(now) is None
        assert plan.upcoming(now) is None
        assert plan.missed(now, _now(0, 0)) == []

    def test_due_returns_most_recent_past_target(self):
        plan = self._plan(None)
        target_dt, _caption, _label = plan.due(_now(12, 0))
        assert target_dt == datetime(2026, 6, 26, 10, 12)

    def test_upcoming_returns_next_future_target(self):
        plan = self._plan(None)
        target_dt, label = plan.upcoming(_now(12, 0))
        assert target_dt == datetime(2026, 6, 27, 10, 12)
        assert label["type"] == "guss"

    def test_missed_skips_the_still_open_target(self):
        """Der jüngste fällige Zeitpunkt ist offen, nicht verpasst (ADR 0041)."""
        plan = self._plan(None, photo_times=[_photo_time("08:00"), _photo_time("09:00")],
                          schedules=[])
        verpasst = plan.missed(_now(12, 0), datetime(2026, 6, 26, 7, 0))
        assert verpasst == [datetime(2026, 6, 26, 8, 0)]

    def test_missed_without_known_state_reports_nothing(self):
        plan = self._plan(None)
        assert plan.missed(_now(12, 0), None) == []

    def test_sleep_seconds_stops_at_next_target(self):
        plan = self._plan(None)
        # 10:00 + 10 Min Dauer + 2 Min Offset = 10:12; von 10:00 aus 720 s
        assert plan.sleep_seconds(_now(10, 0), INTERVAL) == 720

    def test_sleep_seconds_respects_interval_ceiling(self):
        plan = self._plan(None, schedules=[], photo_times=[])
        assert plan.sleep_seconds(_now(10, 0), INTERVAL) == INTERVAL

    def test_plan_is_immutable(self):
        """Der Plan beschreibt einen Zustand; er wandelt sich unterwegs nicht."""
        plan = self._plan(None)
        with pytest.raises(Exception):
            plan.after_offset_minutes = 99

    def test_plan_ignores_later_changes_to_the_source_list(self):
        """Der Plan hält eine eigene Kopie — sonst wäre die Beständigkeit Fassade.

        Review-Befund: `frozen=True` verbietet nur die Attributzuweisung. Solange der Plan
        die übergebene Liste selbst hält, ändert eine spätere Mutation von außerhalb sein
        Verhalten — bei einem Objekt, dessen Docstring Beständigkeit zusagt, die
        heimtückischste Sorte Fehler.
        """
        schedules = [_schedule("10:00", 10)]
        plan = camera_schedule.PhotoPlan.unfiltered(schedules, [], OFFSET)
        now = _now(12, 0)
        vorher = len(plan.targets(now))

        schedules.append(_schedule("11:00", 10))

        assert len(plan.targets(now)) == vorher

    def test_plan_ignores_later_changes_to_photo_times(self):
        """Dasselbe gilt für die festen Fotozeiten."""
        photo_times = [_photo_time("08:00")]
        plan = camera_schedule.PhotoPlan.unfiltered([], photo_times, OFFSET)
        now = _now(12, 0)
        vorher = len(plan.targets(now))

        photo_times.append(_photo_time("09:00"))

        assert len(plan.targets(now)) == vorher

    def test_plan_is_hashable(self):
        """Ein eingefrorener Plan gehört in ein Dict legbar — etwa als Zwischenspeicher.

        Review-Befund: `frozen=True` legt Hashbarkeit nahe, das erzeugte __hash__ lief aber
        über die Listenfelder und warf TypeError.
        """
        plan = camera_schedule.PhotoPlan.unfiltered([_schedule("10:00", 10)], [], OFFSET)
        assert {plan: "geht"}[plan] == "geht"
