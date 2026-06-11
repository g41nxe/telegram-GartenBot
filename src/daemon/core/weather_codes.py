def get_wmo_description(code: int) -> str:
    """Übersetzt einen WMO-Wettercode in eine menschenlesbare deutsche Beschreibung."""
    mapping = {
        0: "☀️ Sonnig / Klar", 1: "🌤️ Leicht bewölkt", 2: "⛅ Teilweise bewölkt", 3: "☁️ Bedeckt / Bewölkt",
        45: "🌫️ Nebelig", 48: "🌫️ Raureifnebel", 51: "🌧️ Leichter Nieselregen", 53: "🌧️ Mäßiger Nieselregen",
        55: "🌧️ Starker Nieselregen", 56: "🌧️ Leichter gefrierender Nieselregen", 57: "🌧️ Dichter gefrierender Nieselregen",
        61: "🌧️ Leichter Regen", 63: "🌧️ Mäßiger Regen", 65: "🌧️ Starker Regen",
        66: "🌧️ Leichter gefrierender Regen", 67: "🌧️ Starker gefrierender Regen",
        71: "❄️ Leichter Schneefall", 73: "❄️ Mäßiger Schneefall", 75: "❄️ Starker Schneefall",
        77: "❄️ Schneegriesel", 80: "🌧️ Leichte Regenschauer", 81: "🌧️ Mäßige Regenschauer", 82: "🌧️ Starke Regenschauer",
        85: "❄️ Leichte Schneeschauer", 86: "❄️ Starke Schneeschauer", 95: "⚡ Gewitter",
        96: "⚡ Gewitter mit leichtem Hagel", 99: "⚡ Gewitter mit starkem Hagel"
    }
    return mapping.get(code, "🌡️ Unbekannt")
