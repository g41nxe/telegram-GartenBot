"""Reine Core-Funktionen für getimte Kamera-Aufnahmen.

Keine I/O. Eingaben kommen vom camera_receiver-Adapter (DB-Abfragen), Ausgaben sind
skalare Werte oder Tupel aus (Aufnahme-Zeitpunkt, Beschriftung, Label).

Die Ziel-Erzeugung deckt Vortag, heute und morgen ab: Ein Aufnahme-Zeitpunkt bleibt offen,
bis der naechste ihn abloest (ADR 0040) — ueber Mitternacht hinweg also auch der von gestern.

Zeitzonen (Ticket fok): Aufnahme-Zeitpunkte sind bewusst **lokale Wanduhrzeit** — „08:00" meint
08:00 Ortszeit, jeden Tag, unabhängig von Sommer-/Winterzeit. Anzeige, Ordnung und Verzug rechnen
in dieser Wanduhrzeit. Nur die *physische Schlafdauer* (compute_next_sleep_seconds) braucht die
tatsächlich verstrichene Zeit; sie wird über ``tz`` (ZoneInfo) DST-korrekt gerechnet, sonst würde
die Kamera an den beiden Umstellungstagen bis zu 60 min daneben aufwachen. Die im Frühjahr nicht
existierende Stunde (02:00–03:00) löst ZoneInfo auf den realen Moment danach auf; die im Herbst
doppelte Stunde wird als erstes Vorkommen gewertet (``fold=0``).
"""
import re
from datetime import datetime, timedelta


def _md_escape(text) -> str:
    """Neutralisiert die Markdown-Sonderzeichen (_ * ` [) der Telegram-Legacy-Markdown.

    Die Foto-Caption wird mit parse_mode=Markdown gesendet; ein Zeitplan-Name wie
    „Beet_1" würde sonst die Analyse brechen und das Foto mit HTTP 400 verwerfen.
    Spiegelt ui._md_escape — hier dupliziert, weil core/ nicht aus ui/ importieren darf.
    """
    if not text:
        return ""
    return re.sub(r"([_*`\[])", r"\\\1", str(text))


def _guss_targets(now: datetime, schedules: list, after_offset_minutes: int):
    """Liefert (target_dt, caption, label) für alle aktiven Guss-Zeitpläne — Vortag, heute, morgen.

    Nur Zeitpläne im Modus „watering" erzeugen ein Guss-Foto. Ein Nebel-Intervall (ADR 0033)
    liegt in derselben Tabelle, ist aber kein Guss: Es hat keine Guss-Dauer, und ein Foto
    „Nach dem Guss" wäre schlicht falsch.

    label = {"type": "guss", "name": <Zeitplan-Name>}
    """
    targets = []
    for s in schedules:
        if not s.get("is_active", 1):
            continue
        if (s.get("mode") or "watering") != "watering":
            continue
        h, m = map(int, s["time"].split(":"))
        duration = s["duration_minutes"]
        name = s.get("name") or ""
        caption = (
            f"\U0001f4f7 Nach dem Guss „{_md_escape(name)}“"
            if name else "\U0001f4f7 Nach dem Guss"
        )
        label = {"type": "guss", "name": name}
        for day_offset in (-1, 0, 1):
            base = now.replace(hour=h, minute=m, second=0, microsecond=0)
            base += timedelta(days=day_offset)
            target = base + timedelta(minutes=duration + after_offset_minutes)
            targets.append((target, caption, label))
    return targets


def _absolute_targets(now: datetime, photo_times: list):
    """Liefert (target_dt, caption, label) für alle festen Fotozeiten — Vortag, heute, morgen.

    label = {"type": "fix"}
    """
    targets = []
    for pt in photo_times:
        h, m = map(int, pt["time"].split(":"))
        caption = f"📷 Foto um {h:02d}:{m:02d}"
        label = {"type": "fix"}
        for day_offset in (-1, 0, 1):
            base = now.replace(hour=h, minute=m, second=0, microsecond=0)
            base += timedelta(days=day_offset)
            targets.append((base, caption, label))
    return targets


def daylight_filter(is_daylight, types):
    """Baut den Aufnahme-Filter ``(target_dt, label) -> bool`` oder None (= nicht filtern).

    Trennt die beiden Fragen sauber: `is_daylight` (aus `core/sun.py`) weiß, wann Licht ist;
    `types` weiß, welche Sorte Aufnahme-Zeitpunkt sich davon aufhalten lässt. Ein Guss-Foto
    entsteht als Nebenwirkung eines Zeitplans, den der Benutzer wegen der Bewässerung auf
    22:00 gelegt hat — eine feste Fotozeit hat er dagegen bewusst gesetzt. Welche davon der
    Dunkelheit weichen, entscheidet die Konfiguration, nicht dieses Modul.

    Ohne `is_daylight` (keine Koordinaten konfiguriert) oder ohne `types` gibt es keinen
    Filter — dann bleibt das Verhalten das vorherige.
    """
    if is_daylight is None or not types:
        return None

    erlaubte_typen = set(types)

    def photo_allowed(target_dt: datetime, label: dict) -> bool:
        if (label or {}).get("type") not in erlaubte_typen:
            return True
        return is_daylight(target_dt)

    return photo_allowed


def _all_targets(now, schedules, photo_times, after_offset_minutes, photo_allowed=None):
    """Alle Aufnahme-Zeitpunkte als (target_dt, caption, label) — bereits gefiltert.

    Der Filter greift hier und nur hier: Ein unterdrückter Zeitpunkt existiert damit für
    *jeden* Verbraucher nicht. Filterte stattdessen erst die Zustellung, bliebe der Zeitpunkt
    für den Watchdog bestehen und würde als verpasst gemeldet (ADR 0041) — das schwarze Foto
    wäre durch einen Fehlalarm ersetzt, und die Kamera wäre nachts trotzdem aufgewacht.
    """
    targets = (
        _guss_targets(now, schedules, after_offset_minutes)
        + _absolute_targets(now, photo_times)
    )
    if photo_allowed is None:
        return targets
    return [t for t in targets if photo_allowed(t[0], t[2])]


def _real_seconds(now: datetime, target: datetime, tz) -> float:
    """Tatsächlich verstrichene Sekunden von ``now`` bis ``target``.

    Beide sind naive lokale Wanduhrzeiten. Mit ``tz`` (ZoneInfo) werden sie in der Zeitzone
    verortet, sodass die Differenz die echte Dauer ist — an den Umstellungstagen ±1 h gegenüber
    der naiven Differenz (Ticket fok). Ohne ``tz`` die naive Differenz (auf Normaltagen gleich).

    Über ``.timestamp()`` (POSIX/UTC): das direkte Subtrahieren zweier aware-datetimes mit
    *demselben* tzinfo ignoriert in Python den Offset (naive Wanduhr-Differenz) — genau das,
    was hier vermieden werden muss.
    """
    if tz is None:
        return (target - now).total_seconds()
    return target.replace(tzinfo=tz).timestamp() - now.replace(tzinfo=tz).timestamp()


def compute_next_sleep_seconds(
    now: datetime,
    schedules: list,
    photo_times: list,
    interval_seconds: int,
    after_offset_minutes: int,
    tz=None,
    photo_allowed=None,
) -> int:
    """Berechnet die optimale Schlafdauer für die Kamera.

    Gibt Min(interval_seconds, Sekunden_bis_nächsten_Aufnahme_Zeitpunkt) zurück.
    Minimum 60 Sekunden (Kamera-Constraint). ``tz`` (ZoneInfo) macht die Schlafdauer an den
    Sommerzeit-Umstellungen DST-korrekt (Ticket fok).

    Reichweite und Dauer werden BEIDE in echter verstrichener Zeit gemessen — sonst würde am
    Frühjahrs-Übergang ein real erreichbares Ziel vom naiven Filter verworfen (Review-Befund).
    """
    best_seconds = interval_seconds

    all_targets = _all_targets(
        now, schedules, photo_times, after_offset_minutes, photo_allowed
    )

    for target_dt, _, _label in all_targets:
        secs = _real_seconds(now, target_dt, tz)
        if 0 <= secs <= interval_seconds and secs < best_seconds:
            best_seconds = int(secs)

    return max(60, best_seconds)


def faelliger_aufnahme_zeitpunkt(
    now: datetime,
    schedules: list,
    photo_times: list,
    after_offset_minutes: int,
    photo_allowed=None,
) -> tuple | None:
    """Gibt den jüngsten bereits fälligen Aufnahme-Zeitpunkt zurück: (target_dt, caption, label).

    Ein Aufnahme-Zeitpunkt wird vom ersten Bild erfüllt, das NACH ihm eintrifft (ADR 0040);
    er bleibt offen, bis der nächste ihn ablöst. Ein Upload vor dem Zeitpunkt erfüllt ihn
    nicht — die Kamera wacht bauartbedingt bis zu 60 s zu früh auf, und ein Bild vor dem
    Nach-Offset kann das Beet mitten im Guss zeigen.

    Gibt None zurück, wenn überhaupt kein Aufnahme-Zeitpunkt konfiguriert ist. Ist einer
    konfiguriert, liegt immer einer in der Vergangenheit — vor der ersten Fotozeit des Tages
    ist das der Zeitpunkt des Vortags, der bis dahin offen bleibt.
    """
    all_targets = _all_targets(
        now, schedules, photo_times, after_offset_minutes, photo_allowed
    )

    best = None
    for target_dt, caption, label in all_targets:
        if target_dt > now:
            continue
        if best is None or target_dt > best[0]:
            best = (target_dt, caption, label)

    return best


def verpasste_aufnahme_zeitpunkte(
    now: datetime,
    schedules: list,
    photo_times: list,
    after_offset_minutes: int,
    zuletzt_zugestellt: datetime | None,
    photo_allowed=None,
) -> list:
    """Aufnahme-Zeitpunkte, die abgelöst wurden, ohne je ein Bild erhalten zu haben (ADR 0041).

    Der jüngste fällige Zeitpunkt zählt nicht dazu: Er ist noch **offen** — das nächste Bild
    erfüllt ihn. Verpasst ist ein Zeitpunkt erst, wenn ein neuerer ihn abgelöst hat.

    Ohne bekannten Zustand (`zuletzt_zugestellt is None`) wird nichts gemeldet: Nach einem
    Daemon-Neustart soll keine Alarm-Flut für längst vergangene Zeitpunkte entstehen.
    """
    if zuletzt_zugestellt is None:
        return []

    faellige = sorted(
        target_dt
        for target_dt, _caption, _label in _all_targets(
            now, schedules, photo_times, after_offset_minutes, photo_allowed
        )
        if zuletzt_zugestellt < target_dt <= now
    )

    # Den jüngsten (noch offenen) Zeitpunkt ausnehmen.
    return faellige[:-1]


def beschriftung_mit_verzug(
    caption: str,
    target_dt: datetime,
    captured_at: datetime,
    hinweis_schwelle_minuten: int,
) -> str:
    """Ergänzt die Beschriftung um die echte Aufnahmezeit, sobald der Aufnahme-Verzug auffällt.

    Der Aufnahme-Zeitpunkt ist der Anlass, die Aufnahmezeit die Tatsache: Fallen sie zusammen,
    ist die Tatsache redundant; weichen sie ab, ist sie die wichtigste Information am Bild
    (ADR 0040). Liegt die Aufnahme an einem anderen Tag als der Aufnahme-Zeitpunkt, nennt der
    Hinweis auch das Datum — sonst sähe ein Bild vom Folgetag wie eines vom selben Morgen aus.

    `captured_at` ist die Empfangszeit des Uploads auf der Steuerzentrale, nicht der
    Auslösezeitpunkt der Kamera — die Kamera meldet ihn nicht. Die Differenz sind Sekunden
    (Aufnahme, JPEG-Kodierung, Übertragung) und damit klein gegen jeden Verzug, der hier zählt.
    """
    verzug = (captured_at - target_dt).total_seconds()
    if verzug < hinweis_schwelle_minuten * 60:
        return caption

    if captured_at.date() != target_dt.date():
        zeit = captured_at.strftime("%d.%m. um %H:%M")
    else:
        zeit = captured_at.strftime("%H:%M")
    return f"{caption} · aufgenommen {zeit}"


def next_photo_target(
    now: datetime,
    schedules: list,
    photo_times: list,
    after_offset_minutes: int,
    photo_allowed=None,
) -> tuple | None:
    """Gibt den nächsten zukünftigen Aufnahme-Zeitpunkt zurück: (target_dt, label) oder None.

    label = {"type": "guss", "name": str} | {"type": "fix"}
    """
    all_targets = _all_targets(
        now, schedules, photo_times, after_offset_minutes, photo_allowed
    )

    best_dt = None
    best_label = None

    for target_dt, _caption, label in all_targets:
        if target_dt <= now:
            continue
        if best_dt is None or target_dt < best_dt:
            best_dt = target_dt
            best_label = label

    if best_dt is None:
        return None
    return best_dt, best_label
