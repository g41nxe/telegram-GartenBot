# Gießcheck — Bewässerungs-Empfehlung Implementation Plan (aktualisiert)

**Status:** Implementiert in Issue telegram-GartenBot-5fr

**Architektur-Referenzen:** ADR 0021 (pure Funktion), ADR 0022 (Hitzestrecke), ADR 0029 (Design-System), ADR 0031 (graduierte Gieß-Steuerung)

---

## Was implementiert wurde

### 1. Config (`src/daemon/config.py`, `config/garden.conf`)
- `RAIN_THRESHOLD_MM` von 2.0 auf **3.0** aktualisiert (3.0 mm ≈ 1/8″ wassersparend)
- Neue Variablen: `GIESSCHECK_HOT_TEMP_C=25.0`, `GIESSCHECK_HEAT_SENSITIVITY=0.5`, `GIESSCHECK_HOT_DAYS_COUNT=3`

### 2. Datenbank (`src/daemon/adapters/database.py`)
- `get_daily_max_temps(days: int) -> list[tuple[str, float]]`: gibt (date_str, max_temp) pro abgeschlossenem Vortag zurück, neueste zuerst, heutiger Tag ausgeschlossen.

### 3. Core — `evaluate_watering()` (`src/daemon/core/watering_advice.py`)
- `WateringDecision(factor, verdict, reasons, skip)` NamedTuple
- `_compute_heat_streak()`: datums-aware Hitzestrecken-Berechnung mit Lücken-Abbruch
- `evaluate_watering()`: pure Funktion, Modell A (linearer Regen-Quotient mit hitze-angepasster Schwelle)
  - Faktor 0–1.0 in 5%-Schritten (Totzonen: ≥0.9→1.0, ≤0.1→0.0)
  - Verdicts: 🌧 Kein Gießen nötig / 💧 Reduzierter Guss (X %) / 🚿 Voller Guss
  - Begründungssätze mit Quellenangabe

### 4. Events (`src/daemon/core/scheduler_events.py`)
- `WateringScaled` Event: schedule_name, factor, duration_original/scaled, volume_original/scaled, reasons

### 5. Wetter-Adapter (`src/daemon/adapters/weather.py`)
- `_compute_rain_next_eff()`: stundenweise Wahrscheinlichkeits-Gewichtung aus `hourly_forecast_json`
- `_watering_decision_from_cache()`: WateringDecision aus gecachtem Wettereintrag
- `evaluate_watering_factor()`: cache-first graduated decision (Fallback-Kette wie ADR 0020)
- `should_skip_watering()`: jetzt dünner Wrapper um `evaluate_watering_factor()` (ADR-konform)

### 6. Scheduler (`src/daemon/scheduler.py`)
- `_trigger_scheduled_watering()` ruft `evaluate_watering_factor()` statt `should_skip_watering()` auf
- Faktor=0 → WateringSkipped (wie bisher)
- 0 < Faktor < 1 → skalierte Limits (max(1, round(dur * f)) / round(vol * f)), WateringScaled publiziert
- Faktor=1 → unverändert

### 7. Telegram UI (`src/daemon/ui/telegram_ui.py`)
- `handle_giesscheck()`: ruft `evaluate_watering_factor()` auf, formatiert Verdict + Begründung
- `/giesscheck` und `💧 Gießcheck` Button im dispatch
- Hauptmenü umgebaut: 4 Zeilen, Gießcheck-Button in Zeile 1
- `_on_watering_scaled()`: Benachrichtigung bei skaliertem Guss (Prozent, skalierte Werte)
- WateringScaled im `subscribe_event_handlers()`
- Wizard-Abbruchlisten um `💧 Gießcheck` erweitert

---

## Tests
- `tests/core/test_watering_advice.py`: 23 Tests für RainWindow + evaluate_watering (Modell A)
- `tests/adapters/test_database.py`: 6 Tests für get_daily_max_temps
- `tests/test_irrigation.py`: test_15b (graduated scaling), test_15c (full factor no scaling)
- `tests/ui/test_telegram_ui.py`: 5 Tests für /giesscheck Handler, 2 für WateringScaled Notification

---

## Nicht implementiert (Out of Scope dieser Iteration)

- Chart-Update (48h-Fenster, Vergangenheit aus ERA5) — separates Folge-Feature
- ADR 0020 Cache-Re-Zentrierung zur Aufrufzeit (Teilweise: rain_next_eff wird zur Aufrufzeit aus hourly_forecast_json berechnet)
- telegram-nachrichten.html Update (Soll-/Ist-Sync)
