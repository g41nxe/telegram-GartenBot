"""Ableitung der Inaktivitäts-Schwelle aus dem Melde-Verhalten eines Geräts (Ticket 8zj).

Wie lange darf ein Gerät schweigen, bevor das Schweigen eine Störung ist? Eine feste
Stundenzahl kann das nicht beantworten: Sie bedeutet für ein Ventil, das alle fünf
Minuten funkt, etwas völlig anderes als für eines im Stundentakt. Bei 24 Stunden
Schwelle und 5-Minuten-Takt verstreichen 288 ausgebliebene Meldungen, bevor jemand
etwas merkt.

Die Schwelle wird deshalb aus dem *beobachteten* Intervall abgeleitet — dieselbe Regel,
die der Watchdog für Kameras längst anwendet (`max(3 × sleep_duration, 1 h)`), nur dass
das Intervall bei Ventilen nicht konfiguriert, sondern gemessen ist.

Kein I/O: Die Messung ist Sache des Adapters, hier steht allein die Rechnung.
"""
from __future__ import annotations


def valve_timeout_seconds(
    interval_seconds: float | None,
    min_seconds: float,
    max_seconds: float,
    factor: float,
) -> float:
    """Liefert die Schweige-Schwelle in Sekunden.

    - `interval_seconds` unbekannt oder unbrauchbar (≤ 0) → `max_seconds`. Ohne Messung
      wird nicht geraten: Es bleibt beim bisherigen, konservativen Fixwert, statt eine
      erfundene Schwelle zu setzen, die Fehlalarme auslöst.
    - sonst `factor × interval_seconds`, begrenzt auf `[min_seconds, max_seconds]`.

    Die Untergrenze fängt geschwätzige Geräte ab (ein 6-Sekunden-Takt ergäbe 18 Sekunden
    — jeder Funk-Aussetzer wäre ein Alarm). Die Obergrenze bleibt der ausdrücklich
    konfigurierte Deckel und gewinnt bei widersprüchlicher Konfiguration gegen die
    Untergrenze: Sie ist die Zusage „spätestens dann meldet es sich".
    """
    if interval_seconds is None or interval_seconds <= 0:
        return max_seconds
    return min(max(factor * interval_seconds, min_seconds), max_seconds)
