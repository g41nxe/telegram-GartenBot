# 📅 Leitfaden zur Verbesserten Wetterdaten-Anzeige der Gartenbewässerung

Der Bewässerungs-Daemon zeigt Wetterdaten bisher nur als aggregierte Tageswerte (Summe Niederschlag, Min/Max-Temperatur, Regenwahrscheinlichkeit). Dieses Feature ersetzt diese Ansicht durch zwei klar getrennte Darstellungen: `/status` zeigt den aktuellen Wetterzustand und die Vorhersage für die nächste Stunde; `/report` enthält einen stündlichen Wetterchart für die nächsten 24 Stunden.

---

## 1. Übersicht & Funktionsweise

### `/status` — Aktuelles Wetter & nächste Stunde

Der Wetter-Block im `/status`-Befehl wird auf zwei Zeilen umgestellt:

- **Jetzt**: Aktuelle Temperatur, aktueller Niederschlag (mm in der letzten Stunde) und WMO-Wettercode — bezogen aus dem `current=`-Endpunkt der Open-Meteo API.
- **Nächste Stunde**: Vorhergesagte Temperatur, Niederschlag (mm), Niederschlagswahrscheinlichkeit (%) und WMO-Wettercode für die kommende Stunde — aus dem `hourly=`-Array, Index `current_idx + 1`.

**Beispiel-Darstellung:**
```
🌡 Jetzt   ☁️ Bedeckt · 19°C · 💧 0.3mm
🔜 20:00  🌧 Regen · 18°C · 1.2mm · 60%
```

Die bisherigen Felder `temp_min/max`, `rain_probability`, `rain_last_24h` und `rain_next_24h` werden aus dem `/status`-Wetter-Block entfernt.

### `/report` — Stündlicher Wetterchart (nächste 24 Stunden)

Der Tagesbericht erhält einen stündlichen Wetterchart, der als PNG-Bild per Telegram gesendet wird. Der Chart zeigt vier Größen über 24 Stunden:

- Temperatur (°C) — Linie
- Niederschlag (mm) — Balken
- Niederschlagswahrscheinlichkeit (%) — Linie
- WMO-Wettercode — Linie

Das Bild wird von **QuickChart.io** generiert (siehe ADR-0019). Der Chart-Adapter (`adapters/chart.py`) baut die Chart.js-Konfiguration aus den gespeicherten Stundendaten auf und übermittelt sie per HTTP-POST. Bei Nichtverfügbarkeit von QuickChart.io wird stattdessen ein stündlicher Textbericht ausgegeben (24 Zeilen, je eine Zeile pro Stunde).

### Datenbeschaffung & Caching

Die stündlichen Wetterdaten werden im bestehenden Hintergrund-Wetter-Abruf (`scheduler.py`, alle 60 Minuten) mitgeliefert — kein zusätzlicher API-Call bei `/report`. Die Stundenarrays (Temperatur, Niederschlag, Wahrscheinlichkeit, WMO-Code) werden als JSON-Blob in der Spalte `hourly_forecast_json` der Tabelle `weather_history` gespeichert.

---

## 2. Parameter & Konfiguration

### System-Parameter (Datenbank / API)

*   **Stündliche Vorhersage** (`hourly_forecast_json`): JSON-Blob in `weather_history`, enthält Arrays für `times`, `temp`, `precip_mm`, `precip_prob`, `wmo` — je 24 Einträge ab der aktuellen Stunde.
*   **Aktueller Niederschlag** (`current_precipitation_mm`): Neue Spalte in `weather_history`, befüllt aus `current=precipitation` der Open-Meteo API.

### Umgebungsvariablen (`.env`)

*   **`WEATHER_REFRESH_INTERVAL_SECONDS`**: Standardwert `3600` (60 Minuten) — unverändert. Stellt sicher, dass die Stundendaten für `/report` und die `current`-Daten für `/status` stets aktuell sind.

---

## 3. Befehls-Syntax im Telegram-Bot

### A. Aktuellen Systemstatus abrufen

*   **Befehl**: `/status`
*   **Beschreibung**: Zeigt den Systemstatus inklusive des neuen Wetter-Blocks mit aktuellem Zustand und Einstunden-Vorschau.
*   **Beispiel**:
    ```
    🌡 Jetzt   ☀️ Sonnig · 22°C · 💧 0.0mm
    🔜 15:00  🌤 Leicht bewölkt · 21°C · 0.0mm · 5%
    ```

### B. Tagesbericht abrufen

*   **Befehl**: `/report` oder `/statusbericht`
*   **Beschreibung**: Sendet den vollständigen Tagesbericht. Der Wetterchart wird als PNG-Bild vorangestellt; bei Verbindungsproblemen mit QuickChart.io erscheint stattdessen ein stündlicher Textbericht.
*   **Beispiel (Textfallback)**:
    ```
    🌤 Wetterverlauf — nächste 24h

    14:00  22°C  💧 0.0mm   5%  ☀️ Sonnig
    15:00  21°C  💧 0.0mm  10%  🌤 Leicht bewölkt
    16:00  19°C  💧 0.8mm  55%  🌦 Wechselhaft
    ...
    ```

---

## 4. Technische Implementierung (für Entwickler)

*   **Module**:
    - `adapters/weather.py` — API-URL erweitert um `hourly=temperature_2m,weather_code` und `current=precipitation`; Stundenarrays werden extrahiert und im `WeatherDataFetched`-Event mitgegeben.
    - `core/scheduler_events.py` — `WeatherDataFetched` erhält zwei neue Felder: `current_precipitation: float` und `hourly_forecast_json: str`.
    - `adapters/database.py` — Migration: neue Spalten `current_precipitation_mm REAL` und `hourly_forecast_json TEXT` in `weather_history`; `log_weather_data()` und `get_last_weather()` entsprechend angepasst.
    - `adapters/database_adapter.py` — Neuen Felder aus dem Event an `log_weather_data()` weiterleiten.
    - `adapters/chart.py` — Neu: liest `hourly_forecast_json` aus der DB, baut Chart.js-Konfiguration, sendet POST an QuickChart.io, gibt `bytes | None` zurück (None = Textfallback).
    - `ui/telegram_client.py` — Neue Methode `send_photo(chat_id, image_bytes, caption)` via `sendPhoto`-Multipart-Upload.
    - `ui/telegram_ui.py` — `/status`: Wetter-Block auf Label-Stil umgestellt; `/report`: Chart-Adapter aufrufen, Bild oder Textfallback senden.

*   **Datenbank**:
    - Tabelle `weather_history`: neue Spalten `current_precipitation_mm` und `hourly_forecast_json`.
    - Migration erfolgt nach dem bestehenden `ALTER TABLE … ADD COLUMN`-Muster (try/except OperationalError).

*   **Schnittstellen**:
    - **Open-Meteo API**: `current=temperature_2m,precipitation,weather_code` und `hourly=temperature_2m,precipitation,precipitation_probability,weather_code`.
    - **QuickChart.io**: `POST https://quickchart.io/chart` mit Chart.js-JSON-Body; Antwort ist PNG als `bytes`.
    - **Telegram Bot API**: `sendPhoto` mit Multipart-Upload (neu in `telegram_client.py`).

---

## 5. Fehlersuche & Verhalten im Fehlerfall

*   **QuickChart.io nicht erreichbar**: `adapters/chart.py` gibt `None` zurück; `telegram_ui.py` sendet stattdessen den 24-Zeilen-Textbericht. Der Benutzer erhält in jedem Fall eine Wetterübersicht.
*   **Open-Meteo gibt keine Stundendaten zurück**: `hourly_forecast_json` bleibt `NULL` in der DB; `chart.py` gibt `None` zurück, Textfallback greift. Log-Meldung: `"Keine Stundendaten für Chart verfügbar"`.
*   **`/status` zeigt veraltete Wetterdaten**: Das Aktualisierungsintervall beträgt 60 Minuten. Der Zeitstempel `(Stand: HH:MM Uhr)` bleibt im Status sichtbar (ADR-0006), sodass der Benutzer die Aktualität beurteilen kann.
*   **Typische Log-Meldungen**:
    - `"Chart-Generierung fehlgeschlagen: <Fehler>. Nutze Textfallback."` — QuickChart.io-Verbindungsproblem.
    - `"Stundendaten erfolgreich in weather_history gespeichert (24 Einträge)."` — Normalbetrieb.
