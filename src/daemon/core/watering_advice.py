from typing import NamedTuple


class RainWindowResult(NamedTuple):
    skip: bool
    total_mm: float


def evaluate_rain_window(
    rain_last_mm: float,
    rain_next_mm: float,
    threshold_mm: float,
) -> RainWindowResult:
    """Pure Überspring-Entscheidung für das Regen-Fenster.

    Summiert gefallenen + erwarteten Regen und vergleicht mit dem Schwellenwert.
    Kein I/O, kein Zeitbezug, keine Strings — der Schwellenwert wird hereingereicht.
    """
    total = round(rain_last_mm + rain_next_mm, 2)
    return RainWindowResult(skip=total >= threshold_mm, total_mm=total)
