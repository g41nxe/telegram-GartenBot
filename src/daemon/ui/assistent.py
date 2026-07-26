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
from typing import NamedTuple


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
