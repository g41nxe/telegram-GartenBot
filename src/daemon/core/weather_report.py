"""Pure Entscheidungslogik für den Heute-Block des Tagesberichts (ADR 0042).

Kein I/O, kein Netz: der Adapter reicht Live-Resultat und Cache herein, diese
Funktion entscheidet, welche Quelle angezeigt wird (Live / Cache+Stand / nicht
verfügbar) und liefert die anzuzeigenden Werte zurück.
"""
from datetime import datetime
from typing import NamedTuple


# Einheitliche Nutzer-Nachricht bei fehlenden Wetterdaten (Tagesbericht-Heute-Block bei
# available=False sowie Gießcheck-Fehler in telegram_ui). Katalogisiert in
# telegram-nachrichten.html — an einer Stelle halten, damit Katalog und Code nicht driften.
WEATHER_UNAVAILABLE_MESSAGE = "❌ Keine Wetterdaten verfügbar. Bitte später erneut versuchen."


class HeuteWeather(NamedTuple):
    available: bool          # False → "nicht verfügbar"-Zeile statt Vorhersage
    temp_min: float
    temp_max: float
    weather_code: int
    rain_next: float
    rain_prob: int
    stand: str | None        # "HH:MM Uhr" nur im Cache-Rückfall, sonst None


def resolve_heute_weather(
    live: tuple | None,
    cached: dict | None,
    now: datetime,
    max_age_hours: float,
) -> HeuteWeather:
    """Wählt die Anzeigequelle für den Heute-Block.

    `live` ist das Tupel von weather.get_weather_data() oder None; `cached` die
    Zeile von database.get_last_weather() oder None.
    """
    if live is not None:
        # Layout: (rain_last, rain_next, temp, weather_code, temp_min, temp_max, rain_prob, source)
        return HeuteWeather(
            available=True,
            temp_min=live[4],
            temp_max=live[5],
            weather_code=live[3],
            rain_next=live[1],
            rain_prob=live[6],
            stand=None,
        )

    if cached is not None:
        cache_time = datetime.fromisoformat(cached["timestamp"])
        age_hours = (now - cache_time).total_seconds() / 3600
        if age_hours <= max_age_hours:
            return HeuteWeather(
                available=True,
                temp_min=cached["temp_min"],
                temp_max=cached["temp_max"],
                weather_code=cached["weather_code"],
                rain_next=cached["rain_next_24h_mm"],
                rain_prob=cached["rain_probability"],
                stand=cache_time.strftime("%H:%M Uhr"),
            )

    return HeuteWeather(
        available=False,
        temp_min=0.0, temp_max=0.0, weather_code=0, rain_next=0.0, rain_prob=0,
        stand=None,
    )
