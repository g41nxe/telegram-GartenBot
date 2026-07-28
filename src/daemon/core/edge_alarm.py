"""Pure edge detection for flag-guarded, edge-triggered alarms (Ticket 6r2).

Watchdog alarms fire once when a fault begins and clear once when it ends — the raise/clear
event must be emitted only on the *transition*, never while the state is stable. That edge
logic was duplicated across every alarm class and path in the watchdog. It lives here as one
pure decision: given the current fault condition and the last reported state, return the new
reported state plus the event to publish (or ``None`` on no transition).

No I/O — the flag read/write and the publish are the adapter's job (see ``watchdog._check_edge``).
The event factories are injected as callables (ADR 0017) so the core stays ignorant of the
concrete alarm event types.
"""
from __future__ import annotations


def evaluate(faulted: bool, reported: bool, on_raise, on_clear):
    """Return ``(new_reported, event | None)``. The event is produced only on an edge.

    - rising edge  (faulted, not yet reported) -> report it, emit ``on_raise()``
    - falling edge (no longer faulted, was reported) -> clear it, emit ``on_clear()``
    - stable state (no change) -> keep ``reported``, emit nothing (no factory call)
    """
    if faulted and not reported:
        return True, on_raise()
    if not faulted and reported:
        return False, on_clear()
    return reported, None
