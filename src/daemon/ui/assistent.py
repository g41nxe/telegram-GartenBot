"""Assistent — reine Zustandsmaschine mehrstufiger Bot-Dialoge (Ticket cy1).

Ein Assistent besitzt seinen Zustand (``step`` / ``data`` / ``prompt_msg_id``) und die
Übergänge. ``advance(value)`` nimmt die (bereits normalisierte) Nutzer-Eingabe entgegen und
liefert eine **reine Absicht** zurück — ohne I/O, ohne Telegram-Aufruf:

* ``Prompt`` — nächster Schritt: Text + Keyboard-Tag, den der Live-Adapter rendert.
* ``Reject`` — Validierungsfehler: kurze Meldung, **kein** Schritt-Wechsel (ADR 0039).
* ``Done``   — Abschluss: die gesammelten Daten; der Aufrufer führt die DB-Schreibung aus.

Die lebende-Prompt-Nachricht (ADR 0039) und das eigentliche Rendering liegen im späteren
Live-Adapter, der die ``Prompt``/``Reject``/``Done`` in Telegram-Aktionen übersetzt und
dabei ``prompt_msg_id`` pflegt. Das Keyboard ist hier nur ein **Tag** (z. B. ``"hour"`` oder
``("days", [...])``) — so bleibt der Kern frei von den konkreten Keyboard-Buildern.
"""
from typing import Any, NamedTuple


def _as_int(value) -> "int | None":
    """Robustes int-Parsen für getippte Eingaben: None statt Ausnahme bei Unsinn."""
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


class Prompt(NamedTuple):
    text: str
    keyboard: Any = None   # symbolischer Tag; der Live-Adapter mappt ihn auf ein Inline-Keyboard


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
    """Zeitplan-anlegen-Assistent (Wässern-Pfad). Ventile werden beim Start hereingereicht,
    damit die Ventil-Verzweigung rein bleibt (kein DB-Zugriff im Kern).

    Der Nebel-Modus teilt die frühen Schritte, zweigt aber nach der Minute ab — die
    Nebel-Kette folgt als eigener Migrationsschritt und ist hier noch nicht abgebildet.
    """

    def __init__(self, mode: str = "watering", valves=None):
        super().__init__()
        self.data["mode"] = mode
        self._valves = list(valves or [])

    def start(self) -> Prompt:
        self.step = "name"
        return Prompt("🆕 *Neuen Zeitplan anlegen — Name*\n\nBitte gib einen *Namen* ein:", "cancel")

    def advance(self, value) -> "Prompt | Reject | Done":
        step = self.step

        if step == "name":
            name = (value or "").strip()
            if not name:
                return Reject("❌ Der Name darf nicht leer sein. Bitte gib einen Namen ein:")
            self.data["name"] = name
            self.step = "hour"
            return Prompt(f"Zeitplan '{name}' — zu welcher *Stunde* soll gestartet werden?", "hour")

        if step == "hour":
            self.data["hour"] = int(value)
            self.step = "minute"
            return Prompt("Zu welcher *Minute*?", "minute")

        if step == "minute":
            self.data["minute"] = int(value)
            if self.data["mode"] != "watering":
                # Nebel zweigt hier ab; die Nebel-Kette folgt als eigener Migrationsschritt.
                raise NotImplementedError("Nebel-Zweig ist noch nicht migriert")
            self.step = "duration"
            return Prompt("Wie lange soll *maximal* bewässert werden? (Zeitlimit)", "duration")

        if step == "duration":
            if value == "custom":
                self.step = "duration_custom"
                return Prompt("Bitte gib die *Dauer* in Minuten ein (1–25):", "cancel")
            self.data["duration"] = int(value)
            self.step = "volume"
            return Prompt("Wie viel Wasser soll *maximal* fließen? (Volumenlimit)", "volume")

        if step == "duration_custom":
            v = _as_int(value)
            if v is None or not 1 <= v <= 25:
                return Reject("❌ Ungültige Eingabe. Bitte eine Zahl zwischen 1 und 25:")
            self.data["duration"] = v
            self.step = "volume"
            return Prompt("Wie viel Wasser soll *maximal* fließen? (Volumenlimit)", "volume")

        if step == "volume":
            if value == "custom":
                self.step = "volume_custom"
                return Prompt("Bitte gib die *Wassermenge* in Litern ein (> 0):", "cancel")
            self.data["volume"] = int(value)
            return self._after_volume()

        if step == "volume_custom":
            v = _as_int(value)
            if v is None or v <= 0:
                return Reject("❌ Ungültige Eingabe. Bitte eine Zahl größer als 0:")
            self.data["volume"] = v
            return self._after_volume()

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

    def _after_volume(self) -> Prompt:
        """Nach dem Volumen: bei mehreren Ventilen fragen, bei genau einem auto-zuweisen,
        bei keinem ohne valve_id weiter zu den Wochentagen."""
        if len(self._valves) > 1:
            self.step = "valve"
            return Prompt("Welches *Ventil* soll dieser Zeitplan schalten?", ("valve", self._valves))
        if self._valves:
            self.data["valve_id"] = self._valves[0]["id"]
        return self._to_days()

    def _to_days(self) -> Prompt:
        self.step = "days"
        self.data["days"] = []
        return Prompt("An welchen *Wochentagen* soll der Zeitplan laufen?", ("days", []))

    def _advance_days(self, value) -> "Prompt | Reject":
        days = self.data["days"]
        if value == "save":
            if not days:
                return Reject("⚠️ Wähle mindestens einen Tag!")
            self.step = "confirm"
            return Prompt(self._summary(), "confirm")

        if value == "everyday":
            self.data["days"] = ["everyday"]
        else:
            days = [d for d in days if d != "everyday"]   # einzelner Tag hebt "täglich" auf
            days = [d for d in days if d != value] if value in days else days + [value]
            self.data["days"] = days
        return Prompt("An welchen *Wochentagen* soll der Zeitplan laufen?", ("days", self.data["days"]))

    def _summary(self) -> str:
        d = self.data
        return (
            "🆕 *Zeitplan bestätigen*\n\n"
            f"Name: {d['name']}\n"
            f"Start: {d['hour']:02d}:{d['minute']:02d}\n"
            f"Dauer: {d['duration']} Min\n"
            f"Menge: {d['volume']} l\n"
            f"Tage: {', '.join(d['days'])}"
        )
