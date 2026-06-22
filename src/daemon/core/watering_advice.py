import datetime
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


class WateringDecision(NamedTuple):
    factor: float
    verdict: str
    reasons: list[str]
    skip: bool


class ScheduledRunPlan(NamedTuple):
    """Reines Ergebnis der Zeitplan-Auswertung: ob und wie ein Guss ausgeführt wird.

    Trennt die Entscheidung (rein, testbar) von der Ausführung (Scheduler-I/O).
    """
    skip: bool
    skip_reason: str            # Begründung wenn skip=True, sonst ""
    duration: int               # auszuführende Dauer (ggf. skaliert); bei skip=True nur nominal, nicht ausführen
    volume: int                 # auszuführendes Volumen (ggf. skaliert); bei skip=True nur nominal, nicht ausführen
    scaled: bool                # True wenn 0 < factor < 1 angewandt wurde
    factor: float               # angewandter Faktor (1.0 wenn keine Skalierung)
    duration_original: int
    volume_original: int
    reasons: list[str]          # Begründungs-Reasons der Entscheidung; [] wenn kein Entscheidungs-Kontext


def plan_scheduled_run(duration: int, volume: int, decision: "WateringDecision | None") -> ScheduledRunPlan:
    """Berechnet rein (ohne I/O) aus Dauer, Volumen und Wetter-Entscheidung den auszuführenden Guss.

    - decision None (Wetter-Check fehlgeschlagen) -> voller Guss (fail-safe Richtung Gießen).
    - decision.skip -> übersprungen, Begründung als ' | '-verkettete Reasons.
    - 0 < factor < 1 -> Dauer/Volumen skaliert (Dauer mindestens 1 Minute).
    - factor >= 1 -> voller Guss unverändert.

    Hinweis: Nur die Dauer hat einen Mindestwert (1 Minute). Das Volumen darf bewusst
    auf 0 runden (= kein Volumenlimit, rein zeitbasiert) — dies entspricht dem
    bestehenden Scheduler-Verhalten vor der Extraktion.
    """
    if decision is None:
        return ScheduledRunPlan(
            skip=False, skip_reason="", duration=duration, volume=volume,
            scaled=False, factor=1.0,
            duration_original=duration, volume_original=volume, reasons=[],
        )
    if decision.skip:
        return ScheduledRunPlan(
            skip=True, skip_reason=" | ".join(decision.reasons),
            duration=duration, volume=volume, scaled=False, factor=decision.factor,
            duration_original=duration, volume_original=volume,
            reasons=list(decision.reasons),
        )
    if 0.0 < decision.factor < 1.0:
        return ScheduledRunPlan(
            skip=False, skip_reason="",
            duration=max(1, round(duration * decision.factor)),
            volume=round(volume * decision.factor),
            scaled=True, factor=decision.factor,
            duration_original=duration, volume_original=volume,
            reasons=list(decision.reasons),
        )
    return ScheduledRunPlan(
        skip=False, skip_reason="", duration=duration, volume=volume,
        scaled=False, factor=decision.factor,
        duration_original=duration, volume_original=volume, reasons=list(decision.reasons),
    )


def _compute_heat_streak(
    past_daily_temps: list[tuple[str, float]],
    hot_temp_c: float,
) -> int:
    """Datums-aware Hitzestrecke: aufeinanderfolgende heiße Vortage, neueste zuerst.

    Bricht bei Datumslücke oder kühlem Tag ab (ADR 0022).
    """
    streak = 0
    prev_date = None
    for date_str, temp_max in past_daily_temps:
        try:
            day = datetime.date.fromisoformat(date_str)
        except ValueError:
            break
        if prev_date is not None and (prev_date - day).days != 1:
            break
        if temp_max >= hot_temp_c:
            streak += 1
            prev_date = day
        else:
            break
    return streak


def evaluate_watering(
    rain_last_mm: float,
    rain_next_eff_mm: float,
    temp_max_today: float,
    past_daily_temps: list[tuple[str, float]],
    rain_last_source: str = "measured",
    threshold_mm: float = 3.0,
    hot_temp_c: float = 25.0,
    heat_sensitivity: float = 0.5,
    hot_days_cap: int = 3,
) -> WateringDecision:
    """Graduierte Gieß-Empfehlung (Modell A, ADR 0031).

    Gibt einen stufenlosen Faktor 0–100 % zurück: 0 = kein Guss, 100 = voller Guss.
    Berücksichtigt Regen-Fenster (gewichtet), Tagestemperatur und Hitzestrecke.
    Alle Config-Werte werden hereingereicht — kein I/O, kein Zustand.
    """
    hot_today = temp_max_today >= hot_temp_c
    streak = _compute_heat_streak(past_daily_temps, hot_temp_c)

    B_today = heat_sensitivity
    B_streak = heat_sensitivity / 2.0
    hitze_faktor = 1.0
    if hot_today:
        hitze_faktor += B_today
    hitze_faktor += min(streak, hot_days_cap) * B_streak

    R_eff = rain_last_mm + rain_next_eff_mm
    T_eff = threshold_mm * hitze_faktor if hitze_faktor > 0 else threshold_mm

    if T_eff <= 0:
        faktor_roh = 1.0
    else:
        faktor_roh = max(0.0, min(1.0, 1.0 - R_eff / T_eff))

    # Dead zones (code constants, not config)
    if faktor_roh >= 0.9:
        factor = 1.0
    elif faktor_roh <= 0.1:
        factor = 0.0
    else:
        factor = round(faktor_roh * 20) / 20.0  # round to nearest 5 %

    skip = factor == 0.0

    # Verdict (3 levels, water emojis per ADR 0029)
    if factor == 0.0:
        verdict = "🌧 Kein Gießen nötig"
    elif factor < 1.0:
        verdict = f"💧 Reduzierter Guss ({int(round(factor * 100))} %)"
    else:
        verdict = "🚿 Voller Guss"

    # Reasons
    source_label = {
        "sensor": "lokal gemessen",
        "measured": "ERA5-Reanalyse",
        "forecast": "Vorhersage (Fallback)",
    }.get(rain_last_source, rain_last_source)
    reasons: list[str] = [
        f"Regen 48h-Fenster: {R_eff:.1f} mm (gefallen {rain_last_mm:.1f} mm [{source_label}], "
        f"erwartet {rain_next_eff_mm:.1f} mm), Schwelle {T_eff:.1f} mm."
    ]
    if hot_today:
        reasons.append(f"Heißer Tag heute ({temp_max_today:.0f} °C ≥ {hot_temp_c:.0f} °C).")
    if streak > 0:
        reasons.append(
            f"{streak} heiße{'r' if streak == 1 else ''} Tag{'e' if streak > 1 else ''} in Folge — "
            f"Schwelle auf {T_eff:.1f} mm angehoben."
        )

    return WateringDecision(factor=factor, verdict=verdict, reasons=reasons, skip=skip)
