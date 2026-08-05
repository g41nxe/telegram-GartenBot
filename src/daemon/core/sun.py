"""Sonnenauf- und -untergang für einen Ort — reine Rechnung, keine I/O.

Warum gerechnet und nicht abgefragt: Sonnenstand ist eine Funktion von Datum und Koordinaten,
keine Beobachtung. Open-Meteo könnte `daily=sunrise,sunset` liefern, aber das hieße: Zeiten
persistieren, bis in `camera_schedule` durchreichen — und bei API-Ausfall stünde die
Kamera-Planung ohne Grundlage da. Die Rechnung braucht nur `math` und ist immer verfügbar.

Verfahren: die übliche Sonnenaufgangsgleichung (NOAA/Meeus, gekürzte Reihe). Genauigkeit ~2 min
in mittleren Breiten — belanglos gegen den Puffer, mit dem der Aufrufer ohnehin arbeitet
(zwischen Sonnenaufgang und brauchbarem Licht fürs Beet-Foto liegt mehr als eine Fehlerminute).

Zeiten sind **naive lokale Wanduhrzeit**, passend zu `camera_schedule` (Ticket fok): Die Rechnung
läuft in UTC und wird über ``tz`` (ZoneInfo) in Ortszeit gelegt; ohne ``tz`` bleibt es UTC.
"""
import math
from datetime import date, datetime, timedelta, timezone

# Julianisches Datum des 01.01.2000, 12:00 UT — Bezugspunkt der Reihenentwicklung.
_JD_2000 = 2451545.0

# Schiefe der Ekliptik (Grad).
_OBLIQUITY = 23.4397

# Sonnenhöhe, die als Auf-/Untergang gilt (Grad): halber Sonnendurchmesser plus
# atmosphärische Refraktion. Der Zeitpunkt, zu dem der obere Rand den Horizont berührt.
_SUN_DISC_ALTITUDE = -0.833

# Zustand des Tages: Regelfall mit Auf- und Untergang, oder die Sonne kreuzt den Horizont
# an diesem Tag gar nicht.
NORMAL = "normal"
POLAR_DAY = "polar_day"
POLAR_NIGHT = "polar_night"


def _day_number(day: date, tz) -> int:
    """Tageszahl seit dem 01.01.2000 — verankert am **lokalen Mittag**, nicht an 00:00 UT.

    Der lokale Mittag ist der richtige Anker, weil die Reihenentwicklung um den wahren Mittag
    herum rechnet. Ein Anker auf 00:00 UT wäre stillschweigend an die UT-Kalenderdatei
    gebunden: Bei großem Zeitzonen-Versatz weichen lokales und UT-Datum voneinander ab, und
    die Rechnung lieferte den Bogen des Nachbartags. In Berlin fällt das nie auf — deshalb
    hier explizit.

    ``toordinal()`` zählt Tage ab 01.01.0001; der Versatz 1721425.0 verschiebt auf die
    julianische Zählung für 12:00 UT (Probe: 01.01.2000 12:00 → 2451545.0).
    """
    noon_local = datetime(day.year, day.month, day.day, 12)
    noon_utc = noon_local.replace(tzinfo=tz or timezone.utc).astimezone(timezone.utc)

    jd = (
        noon_utc.date().toordinal()
        + 1721425.0
        + (noon_utc - noon_utc.replace(hour=12, minute=0, second=0, microsecond=0)).total_seconds()
        / 86400.0
    )
    return round(jd - _JD_2000 + 0.0008)


def _from_julian(jd: float) -> datetime:
    """Julianisches Datum → aware UTC-Zeitpunkt."""
    return datetime(2000, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=jd - _JD_2000)


def _localize(moment: datetime, tz) -> datetime:
    """Aware UTC-Zeitpunkt → naive Wanduhrzeit in ``tz`` (ohne ``tz``: UTC)."""
    if tz is not None:
        moment = moment.astimezone(tz)
    return moment.replace(tzinfo=None)


def _sun_window(day: date, latitude: float, longitude: float, tz):
    """Kern der Rechnung: ``(NORMAL, (aufgang, untergang))`` oder ``(POLAR_DAY|POLAR_NIGHT, None)``.

    Immer dasselbe Paar (Zustand, Zeiten) — so unterscheiden beide Aufrufer den Sonderfall auf
    demselben Weg, und die Umrechnung in Ortszeit steht an einer Stelle.

    Der Stundenwinkel ``omega`` ist der halbe Tagbogen. Existiert er nicht — weil die Sonne den
    Horizont an diesem Tag nicht kreuzt —, liegt ``cos_omega`` außerhalb [-1, 1]; das Vorzeichen
    unterscheidet Polartag von Polarnacht und wird deshalb unterschieden statt verworfen.
    """
    n = _day_number(day, tz)

    # Mittlere Sonnenzeit am Ort.
    j_star = n - longitude / 360.0

    # Mittlere Anomalie der Sonne.
    mean_anomaly = math.radians((357.5291 + 0.98560028 * j_star) % 360.0)

    # Mittelpunktsgleichung (Bahnexzentrizität).
    center = (
        1.9148 * math.sin(mean_anomaly)
        + 0.0200 * math.sin(2 * mean_anomaly)
        + 0.0003 * math.sin(3 * mean_anomaly)
    )

    # Ekliptikale Länge der Sonne (Grad → Bogenmaß).
    ecliptic_longitude = math.radians(
        (math.degrees(mean_anomaly) + center + 180.0 + 102.9372) % 360.0
    )

    # Sonnenhöchststand (wahrer Mittag) als julianisches Datum.
    j_transit = (
        _JD_2000
        + j_star
        + 0.0053 * math.sin(mean_anomaly)
        - 0.0069 * math.sin(2 * ecliptic_longitude)
    )

    # Deklination der Sonne.
    sin_declination = math.sin(ecliptic_longitude) * math.sin(math.radians(_OBLIQUITY))
    cos_declination = math.sqrt(max(0.0, 1.0 - sin_declination ** 2))

    phi = math.radians(latitude)
    denominator = math.cos(phi) * cos_declination
    if abs(denominator) < 1e-12:
        # Exakt am Pol: kein sinnvoller Tagbogen. Über das Vorzeichen der Deklination
        # entscheidet sich, welche Halbkugel gerade Sommer hat.
        return (POLAR_DAY if sin_declination * latitude > 0 else POLAR_NIGHT), None

    cos_omega = (
        math.sin(math.radians(_SUN_DISC_ALTITUDE)) - math.sin(phi) * sin_declination
    ) / denominator

    if cos_omega < -1.0:
        return POLAR_DAY, None      # Sonne bleibt über dem Horizont.
    if cos_omega > 1.0:
        return POLAR_NIGHT, None    # Sonne bleibt darunter.

    omega = math.degrees(math.acos(cos_omega)) / 360.0
    return NORMAL, (
        _localize(_from_julian(j_transit - omega), tz),
        _localize(_from_julian(j_transit + omega), tz),
    )


def sun_times(day: date, latitude: float, longitude: float, tz=None) -> tuple | None:
    """(Sonnenaufgang, Sonnenuntergang) als naive lokale Wanduhrzeit — oder None.

    None bedeutet: Die Sonne kreuzt an diesem Tag den Horizont nicht (Polartag oder Polarnacht).
    Wer die beiden Fälle unterscheiden muss, nutzt `daylight_predicate`.
    """
    _zustand, zeiten = _sun_window(day, latitude, longitude, tz)
    return zeiten


def daylight_predicate(latitude: float, longitude: float, margin_minutes: int = 0, tz=None):
    """Baut die Prüffunktion ``(datetime) -> bool``: Ist zu diesem Zeitpunkt Tageslicht?

    Nach ADR 0017 wird dem Kern die kleinstmögliche Signatur gereicht — hier ein einzelnes
    Prädikat statt Koordinaten, Puffer und Zeitzone durch jede Ebene zu schleifen.

    ``margin_minutes`` schiebt beide Grenzen nach innen: Zwischen dem Moment des Sonnenaufgangs
    und dem Licht, bei dem ein Beet auf einem Foto erkennbar ist, liegt eine gute halbe Stunde.
    Zehrt der Puffer den ganzen Tag auf (kurzer Wintertag, großzügiger Puffer), gilt der Tag als
    dunkel — die Grenzen dürfen nicht kippen und aus „zu wenig Licht" ein „immer hell" machen.
    """
    margin = timedelta(minutes=max(0, margin_minutes))

    def is_daylight(moment: datetime) -> bool:
        zustand, zeiten = _sun_window(moment.date(), latitude, longitude, tz)
        if zustand is not NORMAL:
            return zustand == POLAR_DAY

        aufgang, untergang = zeiten
        start, end = aufgang + margin, untergang - margin
        if start >= end:
            return False
        return start <= moment <= end

    return is_daylight
