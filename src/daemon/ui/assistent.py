"""Assistent — reine Zustandsmaschine mehrstufiger Bot-Dialoge (Ticket cy1).

Ein Assistent besitzt seinen Zustand (``step`` / ``data`` / ``prompt_msg_id``) und die
Übergänge. ``advance(value)`` nimmt die (bereits normalisierte) Nutzer-Eingabe entgegen und
liefert eine **reine Absicht** zurück — ohne I/O, ohne Telegram-Aufruf:

* ``Prompt(view, keyboard)`` — nächster Schritt: ``view`` benennt den zu rendernden Schritt,
  ``keyboard`` den Tastatur-Typ. Der Live-Renderer formt daraus Text + Inline-Keyboard.
* ``Reject(message)`` — Validierungsfehler: kurze Meldung, **kein** Schritt-Wechsel (ADR 0039).
* ``Done(data)`` — Abschluss: die gesammelten Daten; der Aufrufer führt die DB-Schreibung aus.

Der Kern trägt **keine** Präsentations-Texte oder Keyboards — nur die symbolischen ``view``-
und ``keyboard``-Namen. Damit bleibt die Zustandsmaschine rein testbar; die lebende Prompt-
Nachricht (ADR 0039) und die deutschen Texte leben im Live-Adapter (telegram_ui).
"""
import re
from typing import NamedTuple

_CAMERA_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


def _as_int(value) -> "int | None":
    """Robustes int-Parsen für getippte Eingaben: None statt Ausnahme bei Unsinn."""
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


class Prompt(NamedTuple):
    view: str          # welcher Schritt gerendert wird (== step)
    keyboard: str      # Tastatur-Typ, den der Renderer aufbaut


class Reject(NamedTuple):
    message: str


class Done(NamedTuple):
    data: dict


class Assistent:
    """Basis: besitzt den Dialog-Zustand. Konkrete Assistenten implementieren start()/advance()."""

    def __init__(self):
        self.step = None
        self.data = {}
        self.prompt_msg_id = None

    def start(self) -> Prompt:
        raise NotImplementedError

    def advance(self, value) -> "Prompt | Reject | Done":
        raise NotImplementedError


class ScheduleAssistent(Assistent):
    """Zeitplan-anlegen-Assistent (Wässern- und Nebel-Pfad). Ventile werden beim Start
    hereingereicht, damit die Ventil-Verzweigung rein bleibt (kein DB-Zugriff im Kern).

    Beide Modi teilen Name/Stunde/Minute und ab der Ventil-Auswahl auch Wochentage +
    Bestätigung. Nach der Minute zweigt ``mode="nebel"`` in Fensterende → Nebelstoß →
    Pause ab (statt Dauer → Volumen im Wässern-Pfad).
    """

    def __init__(self, mode: str = "watering", valves=None):
        super().__init__()
        self.data["mode"] = mode
        self.valves = list(valves or [])

    def start(self) -> Prompt:
        self.step = "name"
        return Prompt("name", "cancel")

    def advance(self, value) -> "Prompt | Reject | Done":
        step = self.step

        if step == "name":
            name = (value or "").strip()
            if not name:
                return Reject("❌ Der Name darf nicht leer sein. Bitte gib einen Namen ein:")
            self.data["name"] = name
            self.step = "hour"
            return Prompt("hour", "hour")

        if step == "hour":
            self.data["hour"] = int(value)
            self.step = "minute"
            return Prompt("minute", "minute")

        if step == "minute":
            self.data["minute"] = int(value)
            if self.data["mode"] == "nebel":
                self.step = "end_hour"
                return Prompt("end_hour", "nebel_end_hour")
            self.step = "duration"
            return Prompt("duration", "duration")

        # --- Nebel-Zweig: Fensterende → Stoß → Pause ------------------------------------
        if step == "end_hour":
            self.data["end_hour"] = int(value)
            self.step = "end_minute"
            return Prompt("end_minute", "nebel_end_minute")

        if step == "end_minute":
            end_minute = int(value)
            # Fensterende muss NACH dem Start liegen — sonst matcht der Scheduler nie
            # (start <= jetzt < end). Zurück zur Endstunde, ohne die Startzeit zu verlieren.
            if (self.data["end_hour"], end_minute) <= (self.data["hour"], self.data["minute"]):
                self.step = "end_hour"
                return Prompt("end_hour_retry", "nebel_end_hour")
            self.data["end_minute"] = end_minute
            self.step = "nebel_on"
            return Prompt("nebel_on", "nebel_on")

        if step == "nebel_on":
            self.data["on_seconds"] = int(value)
            self.step = "nebel_pause"
            return Prompt("nebel_pause", "nebel_pause")

        if step == "nebel_pause":
            self.data["pause_minutes"] = int(value)
            return self._branch_valve_or_days()

        if step == "duration":
            if value == "custom":
                self.step = "duration_custom"
                return Prompt("duration_custom", "cancel")
            self.data["duration"] = int(value)
            self.step = "volume"
            return Prompt("volume", "volume")

        if step == "duration_custom":
            v = _as_int(value)
            if v is None or not 1 <= v <= 25:
                return Reject("❌ Ungültige Eingabe. Bitte eine Zahl zwischen 1 und 25:")
            self.data["duration"] = v
            self.step = "volume"
            return Prompt("volume", "volume")

        if step == "volume":
            if value == "custom":
                self.step = "volume_custom"
                return Prompt("volume_custom", "cancel")
            self.data["volume"] = int(value)
            return self._branch_valve_or_days()

        if step == "volume_custom":
            v = _as_int(value)
            if v is None or v <= 0:
                return Reject("❌ Ungültige Eingabe. Bitte eine Zahl größer als 0:")
            self.data["volume"] = v
            return self._branch_valve_or_days()

        if step == "valve":
            self.data["valve_id"] = int(value)
            return self._to_days()

        if step == "days":
            return self._advance_days(value)

        if step == "confirm":
            if value == "confirm":
                return Done(dict(self.data))

        raise ValueError(f"Unerwartete Eingabe '{value}' im Schritt '{step}'")

    # --- Verzweigungen ---------------------------------------------------------------------

    def _branch_valve_or_days(self) -> Prompt:
        """Nach den Detail-Schritten (Volumen bzw. Nebel-Pause): bei mehreren Ventilen fragen,
        bei genau einem auto-zuweisen, bei keinem ohne valve_id weiter zu den Wochentagen."""
        if len(self.valves) > 1:
            self.step = "valve"
            return Prompt("valve", "valve")
        if self.valves:
            self.data["valve_id"] = self.valves[0]["id"]
        return self._to_days()

    def _to_days(self) -> Prompt:
        self.step = "days"
        self.data["days"] = []
        return Prompt("days", "days")

    def _advance_days(self, value) -> "Prompt | Reject":
        days = self.data["days"]
        if value == "save":
            if not days:
                return Reject("⚠️ Wähle mindestens einen Tag!")
            self.step = "confirm"
            return Prompt("confirm", "confirm")

        if value == "everyday":
            self.data["days"] = ["everyday"]
        else:
            days = [d for d in days if d != "everyday"]   # einzelner Tag hebt "täglich" auf
            days = [d for d in days if d != value] if value in days else days + [value]
            self.data["days"] = days
        return Prompt("days", "days")


class GussAssistent(Assistent):
    """Sofort-Guss (manueller Start): Dauer → Volumen → Aktion. Das Ventil ist bereits vor
    dem Assistenten gewählt und wird als ``mqtt_name`` durchgereicht; ``Done`` liefert
    ``duration``/``volume``/``mqtt_name``. Die eigentliche Guss-Auslösung inklusive
    Kontext-Rückfrage (Feature 0020) liegt im Live-Adapter, nicht im Kern.
    """

    def __init__(self, mqtt_name: str = "garden_valve"):
        super().__init__()
        self.data["mqtt_name"] = mqtt_name

    def start(self) -> Prompt:
        self.step = "duration"
        return Prompt("duration", "man_duration")

    def advance(self, value) -> "Prompt | Reject | Done":
        step = self.step

        if step == "duration":
            if value == "custom":
                self.step = "duration_custom"
                return Prompt("duration_custom", "man_cancel")
            self.data["duration"] = int(value)
            self.step = "volume"
            return Prompt("volume", "man_volume")

        if step == "duration_custom":
            v = _as_int(value)
            if v is None or not 1 <= v <= 25:
                return Reject("❌ Ungültige Eingabe. Bitte eine Zahl zwischen 1 und 25:")
            self.data["duration"] = v
            self.step = "volume"
            return Prompt("volume", "man_volume")

        if step == "volume":
            if value == "custom":
                self.step = "volume_custom"
                return Prompt("volume_custom", "man_cancel")
            self.data["volume"] = int(value)
            return Done(dict(self.data))

        if step == "volume_custom":
            v = _as_int(value)
            if v is None or v <= 0:
                return Reject("❌ Ungültige Eingabe. Bitte eine Zahl größer als 0:")
            self.data["volume"] = v
            return Done(dict(self.data))

        raise ValueError(f"Unerwartete Eingabe '{value}' im Schritt '{step}'")


class SofortNebelAssistent(Assistent):
    """Sofort-Nebel (manueller Start): Stoß-Dauer → Pause → Laufzeit → Aktion. Das Ventil
    (ganzer Datensatz, für mqtt_name + wish_name) ist vorgewählt und liegt außerhalb der
    ``data``. ``Done`` liefert on_seconds/pause_minutes/minutes; die Auslösung (Deckelung auf
    NEBEL_MANUAL_MAX_MINUTES) übernimmt der Live-Adapter. Rein Button-getrieben.
    """

    def __init__(self, valve: dict):
        super().__init__()
        self.valve = valve

    def start(self) -> Prompt:
        self.step = "on"
        return Prompt("on", "nebel_now_on")

    def advance(self, value) -> "Prompt | Done":
        step = self.step

        if step == "on":
            self.data["on_seconds"] = int(value)
            self.step = "pause"
            return Prompt("pause", "nebel_now_pause")

        if step == "pause":
            self.data["pause_minutes"] = int(value)
            self.step = "runtime"
            return Prompt("runtime", "nebel_now_runtime")

        if step == "runtime":
            self.data["minutes"] = int(value)
            return Done(dict(self.data))

        raise ValueError(f"Unerwartete Eingabe '{value}' im Schritt '{step}'")


class CameraPairAssistent(Assistent):
    """Kamera-Kopplung: Name → Intervall → Auflösung → Qualität → Aktion. ``Done`` liefert
    wish_name/sleep_seconds/resolution/quality; das eigentliche start_pairing (inkl. Qualitäts-
    Mapping Label→Zahl) liegt im Live-Adapter. Name- und Intervall-Schritte sind getippt.
    """

    def start(self) -> Prompt:
        self.step = "wish_name"
        return Prompt("wish_name", None)

    def advance(self, value) -> "Prompt | Reject | Done":
        step = self.step

        if step == "wish_name":
            name = (value or "").strip()
            if not _CAMERA_NAME_RE.match(name):
                return Reject("❌ Ungültiger Name. Erlaubt: a-z, A-Z, 0-9, -, _ (Max 32 Zeichen). Bitte erneut eingeben:")
            self.data["wish_name"] = name
            self.step = "interval"
            return Prompt("interval", None)

        if step == "interval":
            m = _as_int(value)
            if m is None or not 1 <= m <= 1440:
                return Reject("❌ Ungültige Eingabe. Bitte eine Zahl zwischen 1 und 1440 eingeben:")
            self.data["sleep_seconds"] = m * 60
            self.step = "resolution"
            return Prompt("resolution", "cam_resolution")

        if step == "resolution":
            self.data["resolution"] = value          # VGA / XGA / UXGA (Button)
            self.step = "quality"
            return Prompt("quality", "cam_quality")

        if step == "quality":
            self.data["quality"] = value             # high / medium / low (Button, Mapping im Adapter)
            return Done(dict(self.data))

        raise ValueError(f"Unerwartete Eingabe '{value}' im Schritt '{step}'")


class PairingNameAssistent(Assistent):
    """Ventil-Kopplung: einziger Schritt ist der Wunschname. ``Done`` liefert den Namen;
    das eigentliche Pairing (Mittelweg-Dienst) startet der Live-Adapter."""

    def start(self) -> Prompt:
        self.step = "wish_name"
        return Prompt("wish_name", None)

    def advance(self, value) -> "Reject | Done":
        if self.step == "wish_name":
            name = (value or "").strip()
            if not name:
                return Reject("❌ Der Name darf nicht leer sein. Bitte gib einen Namen ein:")
            self.data["wish_name"] = name
            return Done(dict(self.data))

        raise ValueError(f"Unerwartete Eingabe '{value}' im Schritt '{self.step}'")


class CameraSettingsAssistent(Assistent):
    """Kamera-Einstellung: nur das Sendeintervall ändern. Kamera (mac + wish_name) ist
    vorgewählt; ``Done`` liefert mac/wish_name/sleep_seconds, das DB-Update liegt im Adapter."""

    def __init__(self, mac: str, wish_name: str):
        super().__init__()
        self.data["mac"] = mac
        self.data["wish_name"] = wish_name

    def start(self) -> Prompt:
        self.step = "interval"
        return Prompt("interval", None)

    def advance(self, value) -> "Prompt | Reject | Done":
        if self.step == "interval":
            m = _as_int(value)
            if m is None or not 1 <= m <= 1440:
                return Reject("❌ Ungültige Eingabe. Bitte eine Zahl zwischen 1 und 1440 eingeben:")
            self.data["sleep_seconds"] = m * 60
            return Done(dict(self.data))

        raise ValueError(f"Unerwartete Eingabe '{value}' im Schritt '{self.step}'")
