# Gemessene Regendaten und deterministischer Vergleich — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gefallenen Regen (`rain_last`) aus dem gemessenen Archiv-/ERA5-Produkt des Wetter-Dienstes beziehen statt aus dem Vorhersage-Modell; den Abweichungsvergleich über einen deterministischen Tagessnapshot stabilisieren; Skip-Logik und Chart-Caption über eine gemeinsame pure Funktion entscheiden lassen.

**Architecture:** Pure Entscheidungsfunktion `evaluate_rain_window()` in `core/watering_advice.py` (ADR-0021); `get_weather_data()` macht zwei Calls (Forecast + Archiv) und trägt eine Herkunfts-Markierung; aufruferspezifisches Ausfallverhalten (Skip degradiert, Bericht ehrlich); Snapshot in `system_metadata` (ADR-0012). Kein I/O in core, kein cross-adapter-Import. Siehe Feature-Doc `docs/features/0014-wetter-datenquelle-und-vergleich.md`.

**Tech Stack:** Python 3.11, SQLite via bestehende `database.py`-Patterns, `unittest` + `unittest.mock`, `urllib`.

**ADR-Deliverables (Task 7):** ADR 0024 (Datenquellen-Trennung + Ausfallverhalten + `current_idx`-Fix), ADR 0025 (deterministischer Tagessnapshot), Notiz an ADR 0021, Schärfungen in `CONTEXT.md`.

---

### Task 1: Core — `evaluate_rain_window()`

Reihenfolge zuerst, da ohne Abhängigkeiten. Dies legt das Modul an, das Feature 0009 später um `evaluate()` erweitert.

**Files:**
- Create: `src/daemon/core/watering_advice.py`
- Create: `tests/core/test_watering_advice.py`

- [ ] **Step 1: Failing test schreiben**

Erstelle `tests/core/test_watering_advice.py` (Referenzmuster: `tests/core/test_watering_controller.py`):

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import daemon.core.watering_advice as advice


class TestEvaluateRainWindow(unittest.TestCase):

    def test_below_threshold_does_not_skip(self):
        result = advice.evaluate_rain_window(0.5, 0.3, threshold_mm=2.0)
        self.assertFalse(result.skip)
        self.assertAlmostEqual(result.total_mm, 0.8)

    def test_exactly_at_threshold_skips(self):
        result = advice.evaluate_rain_window(1.0, 1.0, threshold_mm=2.0)
        self.assertTrue(result.skip)
        self.assertAlmostEqual(result.total_mm, 2.0)

    def test_above_threshold_skips(self):
        result = advice.evaluate_rain_window(6.1, 0.0, threshold_mm=2.0)
        self.assertTrue(result.skip)
        self.assertAlmostEqual(result.total_mm, 6.1)

    def test_total_is_sum_of_both_windows(self):
        result = advice.evaluate_rain_window(2.4, 1.1, threshold_mm=2.0)
        self.assertAlmostEqual(result.total_mm, 3.5)
```

- [ ] **Step 2: Test scheitern lassen**

```
python -m unittest tests.core.test_watering_advice -v
```

Erwartet: `ModuleNotFoundError: No module named 'daemon.core.watering_advice'`

- [ ] **Step 3: Modul implementieren**

Erstelle `src/daemon/core/watering_advice.py`:

```python
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
```

- [ ] **Step 4: Tests grün laufen lassen**

```
python -m unittest tests.core.test_watering_advice -v
```

Erwartet: 4 Tests, alle `OK`

- [ ] **Step 5: Commit**

```bash
git add src/daemon/core/watering_advice.py tests/core/test_watering_advice.py
git commit -m "feat: core.watering_advice.evaluate_rain_window() — pure Regen-Fenster-Entscheidung"
```

---

### Task 2: Persistenz — Herkunfts-Markierung `rain_last_source`

Trägt die Markierung durch Schema, `log_weather()`, Event und DB-Adapter. Default `"measured"`, damit Bestandsdaten und Aufrufer ohne explizite Angabe sich neutral verhalten.

**Files:**
- Modify: `src/daemon/adapters/database.py`
- Modify: `src/daemon/core/scheduler_events.py`
- Modify: `src/daemon/adapters/database_adapter.py`
- Test: `tests/adapters/test_database.py`, `tests/adapters/test_database_adapter.py`

- [ ] **Step 1: Failing test schreiben**

Ergänze in `tests/adapters/test_database.py` eine Prüfung, dass `log_weather()` die Herkunft speichert und `get_last_weather()` sie zurückgibt:

```python
class TestRainLastSource(unittest.TestCase):

    def setUp(self):
        self.db_path = _make_temp_db()
        self._patcher = patch.object(db, "DB_PATH", self.db_path)
        self._patcher.start()
        db.init_db()

    def tearDown(self):
        self._patcher.stop()
        import gc
        gc.collect()
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_log_weather_persists_source(self):
        db.log_weather(6.1, 0.0, rain_last_source="measured")
        row = db.get_last_weather()
        self.assertEqual(row["rain_last_source"], "measured")

    def test_log_weather_defaults_source_to_measured(self):
        db.log_weather(1.0, 0.0)
        row = db.get_last_weather()
        self.assertEqual(row["rain_last_source"], "measured")

    def test_log_weather_accepts_forecast_source(self):
        db.log_weather(1.0, 0.0, rain_last_source="forecast")
        row = db.get_last_weather()
        self.assertEqual(row["rain_last_source"], "forecast")
```

- [ ] **Step 2: Test scheitern lassen**

```
python -m unittest tests.adapters.test_database.TestRainLastSource -v
```

Erwartet: Fehler — Spalte/Parameter `rain_last_source` existiert nicht.

- [ ] **Step 3: Schema + Migration ergänzen**

In `src/daemon/adapters/database.py`, in der `CREATE TABLE IF NOT EXISTS weather_history`-Anweisung eine Spalte ergänzen (nach `rain_probability`):

```python
                rain_probability INTEGER DEFAULT 0,
                rain_last_source TEXT DEFAULT 'measured'
```

Und im Migrations-Block (bei den anderen `try/except sqlite3.OperationalError`-Prüfungen) ergänzen:

```python
        try:
            cursor.execute("SELECT rain_last_source FROM weather_history LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migriere Datenbank: Füge rain_last_source Spalte zu weather_history hinzu...")
            cursor.execute("ALTER TABLE weather_history ADD COLUMN rain_last_source TEXT DEFAULT 'measured'")
```

- [ ] **Step 4: `log_weather()` erweitern**

Signatur um `rain_last_source: str = "measured"` ergänzen und in das `INSERT` aufnehmen (Spaltenliste + Platzhalter + Wert).

- [ ] **Step 5: Tests grün (DB) laufen lassen**

```
python -m unittest tests.adapters.test_database.TestRainLastSource -v
```

Erwartet: 3 Tests `OK`.

- [ ] **Step 6: Event + Adapter erweitern (mit Test)**

Ergänze in `tests/adapters/test_database_adapter.py` einen Test, dass die Herkunft aus dem Event in die DB fließt (Referenz: bestehende `WeatherDataFetched`-Tests dort). Dann:

- `scheduler_events.WeatherDataFetched.__init__`: Parameter `rain_last_source: str = "measured"` ergänzen und als Attribut setzen.
- `database_adapter._on_weather_data_fetched`: `rain_last_source=event.rain_last_source` an `database.log_weather(...)` durchreichen.

- [ ] **Step 7: Tests grün laufen lassen**

```
python -m unittest tests.adapters.test_database tests.adapters.test_database_adapter -v
```

Erwartet: alle `OK`.

- [ ] **Step 8: Commit**

```bash
git add src/daemon/adapters/database.py src/daemon/core/scheduler_events.py src/daemon/adapters/database_adapter.py tests/adapters/test_database.py tests/adapters/test_database_adapter.py
git commit -m "feat: rain_last_source-Herkunftsmarkierung durch Schema, Event und DB-Adapter"
```

---

### Task 3: Wetter-Adapter — Archiv-Abruf, robuste Stunden-Zuordnung, gemeinsame Entscheidung

Kern des Features. `get_weather_data()` macht künftig zwei Calls; `rain_last` kommt aus dem Archiv; `_evaluate_skip` delegiert an `evaluate_rain_window`.

**Files:**
- Modify: `src/daemon/adapters/weather.py`
- Test: `tests/adapters/test_weather.py`

- [ ] **Step 1: Failing tests schreiben**

In `tests/adapters/test_weather.py` das Mock so erweitern, dass `urlopen` nach URL verzweigt. Hilfsfunktion ergänzen, die eine Archiv-Antwort baut (Felder `hourly.time`, `hourly.precipitation`), und ein `side_effect`, das anhand von `req.full_url` Forecast- vs. Archiv-JSON liefert. Neue Testklasse mit:

```python
# Skizze der Verzweigung:
def _branching_side_effect(forecast_bytes, archive_bytes):
    def _side_effect(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        payload = archive_bytes if "archive-api" in url else forecast_bytes
        cm = MagicMock()
        cm.__enter__.return_value = MagicMock(read=lambda: payload)
        return cm
    return _side_effect
```

Szenarien:
- **2-Call-Glücksfall:** Archiv liefert in den letzten 24h z.B. 6.1 mm, Forecast 0 mm → Event-`rain_last_24h == 6.1`, `rain_next_24h` aus Forecast, `rain_last_source == "measured"`.
- **Archiv-Ausfall, Forecast OK:** `side_effect` wirft `urllib.error.URLError` nur bei Archiv-URL → Event wird trotzdem publiziert, `rain_last_source == "forecast"`, `rain_next`/`rain_prob` intakt.
- **Forecast-Ausfall:** wirft bei Forecast-URL → `get_weather_data` gibt `None` zurück, kein Event.
- **Robuste Stunden-Zuordnung:** `times` enthält keinen Exakt-Match auf die volle aktuelle Stunde (z.B. Minuten-Offset im Format) → der gewählte Index entspricht der letzten Stunde ≤ jetzt, nicht Index 24.

- [ ] **Step 2: Tests scheitern lassen**

```
python -m unittest tests.adapters.test_weather -v
```

Erwartet: neue Tests `FAIL` (nur ein Call, keine Herkunft, kein Archiv).

- [ ] **Step 3: Robuste Index-Hilfsfunktion**

In `weather.py` ergänzen und in `get_weather_data()` den exakt-Match-Block samt `current_idx = 24`-Fallback ([weather.py:75-87]) ersetzen:

```python
def _find_current_index(times: list[str]) -> int:
    """Index des letzten Stunden-Zeitstempels <= jetzt (ISO sortiert lexikografisch).

    Ersetzt die frühere Exakt-Match-Logik mit hartem Fallback auf Index 24.
    Gibt -1 zurück, wenn alle Zeitstempel in der Zukunft liegen.
    """
    now_str = datetime.now().strftime("%Y-%m-%dT%H:00")
    idx = -1
    for i, t in enumerate(times):
        if t <= now_str:
            idx = i
        else:
            break
    return idx
```

- [ ] **Step 4: Archiv-Abruf für `rain_last`**

In `weather.py` eine Funktion ergänzen, die den gefallenen Regen gemessen abruft und bei Fehler signalisiert:

```python
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

def _fetch_measured_rain_last(lat: float, lon: float) -> float | None:
    """Gemessener Niederschlag der letzten 24h aus dem ERA5-Archiv.

    Gibt die Summe in mm zurück oder None bei Netzwerk-/Datenfehler.
    """
    start = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")
    url = (
        f"{ARCHIVE_URL}?latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}&hourly=precipitation&timezone=auto"
    )
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'GardenIrrigationDaemon/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        times = data.get("hourly", {}).get("time", [])
        precip = data.get("hourly", {}).get("precipitation", [])
        idx = _find_current_index(times)
        if idx < 1 or not precip:
            return None
        start_idx = max(0, idx - 24)
        return round(sum(p for p in precip[start_idx:idx] if p is not None), 2)
    except urllib.error.URLError as e:
        logger.warning(f"Archiv-Wetterabfrage nicht erreichbar: {e}")
    except Exception as e:
        logger.warning(f"Archiv-Wetterdaten nicht verwertbar: {e}")
    return None
```

- [ ] **Step 5: `get_weather_data()` umbauen**

- `current_idx = _find_current_index(times)` statt Exakt-Match/Fallback.
- `rain_last` **nicht mehr** aus der Forecast-Stundenscheibe berechnen. Stattdessen:

```python
        forecast_rain_last = round(sum(p for p in precip[max(0, current_idx - 24):current_idx] if p is not None), 2)
        measured = _fetch_measured_rain_last(lat, lon)
        if measured is not None:
            rain_last_24h = measured
            rain_last_source = "measured"
        else:
            rain_last_24h = forecast_rain_last
            rain_last_source = "forecast"
            logger.warning("Gemessener Regen nicht verfügbar — nutze Forecast-Wert (degradiert).")
```

- `rain_next_24h` weiterhin aus der Forecast-Scheibe `precip[current_idx:current_idx+24]`.
- `WeatherDataFetched(...)` um `rain_last_source=rain_last_source` ergänzen.
- Rückgabe-Tupel um die Herkunft als achtes Element erweitern: `return (rain_last_24h, rain_next_24h, current_temp, weather_code, temp_min, temp_max, rain_prob, rain_last_source)`. (Index-Zugriffe `[0]`/`[1]` in `should_skip_watering` bleiben gültig.)

- [ ] **Step 6: `_evaluate_skip` an core delegieren**

Oben in `weather.py`: `from ..core.watering_advice import evaluate_rain_window`. `_evaluate_skip` rechnet die Summe nicht mehr selbst, sondern:

```python
def _evaluate_skip(rain_last: float, rain_next: float) -> tuple[bool, str]:
    result = evaluate_rain_window(rain_last, rain_next, config.RAIN_THRESHOLD_MM)
    if result.skip:
        details = (
            f"Regenschwelle überschritten: Gesamt {result.total_mm}mm "
            f"(Gefallen: {rain_last}mm, Erwartet: {rain_next}mm, Grenzwert: {config.RAIN_THRESHOLD_MM}mm)"
        )
        logger.info(f"Bewässerung überspringen: {details}")
        return True, details
    details = (
        f"Regen liegt unter Grenzwert: Gesamt {result.total_mm}mm "
        f"(Gefallen: {rain_last}mm, Erwartet: {rain_next}mm, Grenzwert: {config.RAIN_THRESHOLD_MM}mm)"
    )
    logger.info(f"Bewässerung freigegeben: {details}")
    return False, details
```

`should_skip_watering()` bleibt unverändert — es liest `rain_last_24h_mm`/`rain_next_24h_mm` aus dem Cache und nutzt sie unabhängig von der Herkunft (degradiert automatisch). Bei Live-Nutzung greift es weiterhin per Index `[0]`/`[1]` auf das Tupel zu.

- [ ] **Step 7: Tests grün laufen lassen**

```
python -m unittest tests.adapters.test_weather -v
```

Erwartet: alle (inkl. Bestand) `OK`. Bestehende Tests bleiben grün, da bei ihnen die aktuelle Stunde exakt in `times` liegt und `_find_current_index` denselben Index liefert; sie müssen ggf. um eine Archiv-Antwort im `side_effect` ergänzt werden.

- [ ] **Step 8: Commit**

```bash
git add src/daemon/adapters/weather.py tests/adapters/test_weather.py
git commit -m "feat: gemessener rain_last aus Archiv/ERA5, robuste Stunden-Zuordnung, Skip via core.evaluate_rain_window"
```

---

### Task 4: Chart-Caption über `evaluate_rain_window`

Beseitigt die doppelte Schwellenwert-Logik und die Doppelzählung der Chart-Scheibe; die Caption nutzt dieselben Cache-Werte `rain_last` + `rain_next`.

**Files:**
- Modify: `src/daemon/adapters/chart.py`
- Test: `tests/adapters/test_chart.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/adapters/test_chart.py` prüfen, dass `_build_caption` für dieselben Eingaben dieselbe Ja/Nein-Aussage trifft wie `evaluate_rain_window` (z.B. `rain_last=6.1, rain_next=0.0` → „Kein Gießen nötig"; `rain_last=0.2, rain_next=0.1` → „Gießen empfohlen"). Signatur wird auf explizite `rain_next` umgestellt.

- [ ] **Step 2: Test scheitern lassen / Step 3: implementieren**

`chart.py`: `from ..core.watering_advice import evaluate_rain_window`. `_build_caption` auf `(rain_last_24h_mm, rain_next_24h_mm)` umstellen und entscheiden lassen:

```python
def _build_caption(rain_last_24h_mm: float, rain_next_24h_mm: float) -> str:
    result = evaluate_rain_window(rain_last_24h_mm, rain_next_24h_mm, config.RAIN_THRESHOLD_MM)
    if result.skip:
        return f"🌤 Wetterverlauf — nächste 24h\n☔ Kein Gießen nötig — Regen erwartet ({result.total_mm:.1f}mm)"
    return "🌤 Wetterverlauf — nächste 24h\n🌱 Gießen empfohlen — trocken bis morgen"
```

In `generate_weather_chart()` den Aufruf anpassen: `rain_next` aus `last_weather.get("rain_next_24h_mm", 0.0)` lesen und übergeben (statt `sum(precip_mm)`).

- [ ] **Step 4: Tests grün / Step 5: Commit**

```
python -m unittest tests.adapters.test_chart -v
```

```bash
git add src/daemon/adapters/chart.py tests/adapters/test_chart.py
git commit -m "refactor: Chart-Caption nutzt core.evaluate_rain_window (keine Doppel-Logik, keine Doppelzählung)"
```

---

### Task 5: Tagesbericht — Ehrlichkeit bei fehlender Messung + deterministischer Snapshot

**Files:**
- Modify: `src/daemon/adapters/database.py` (Snapshot-Helfer)
- Modify: `src/daemon/adapters/daily_report.py`
- Test: `tests/adapters/test_database.py`, `tests/adapters/test_daily_report.py`

- [ ] **Step 1: Failing tests (DB-Snapshot-Helfer)**

In `tests/adapters/test_database.py`: `set_daily_forecast_snapshot(date, rain_next_mm, window_start)` schreibt einen `system_metadata`-Eintrag; `get_daily_forecast_snapshot()` gibt das geparste Dict zurück; erneutes Setzen überschreibt.

- [ ] **Step 2/3: Snapshot-Helfer implementieren**

In `database.py` (nutzt bestehende `get_metadata`/`set_metadata`):

```python
import json as _json
_DAILY_FORECAST_SNAPSHOT_KEY = "daily_forecast_snapshot"

def set_daily_forecast_snapshot(date_str: str, rain_next_mm: float, window_start: str):
    set_metadata(_DAILY_FORECAST_SNAPSHOT_KEY, _json.dumps({
        "date": date_str, "rain_next_mm": rain_next_mm, "window_start": window_start,
    }))

def get_daily_forecast_snapshot() -> dict | None:
    raw = get_metadata(_DAILY_FORECAST_SNAPSHOT_KEY)
    if not raw:
        return None
    try:
        return _json.loads(raw)
    except (ValueError, TypeError):
        return None
```

- [ ] **Step 4: Failing tests (Bericht-Verhalten)**

In `tests/adapters/test_daily_report.py`:
- Bei `rain_last_source != "measured"` enthält der Wetter-Text **keine** „mm gefallen"-Zahl und **keinen** Abweichungssatz, sondern einen Hinweis „Gemessene Regendaten zurzeit nicht verfügbar".
- Bei vorhandenem Snapshot mit `date == gestern` erscheint der Abweichungssatz; bei fehlendem/falsch-datiertem Snapshot entfällt er.

- [ ] **Step 5: `generate_daily_report` + `_format_weather_section` umbauen**

- Rückgabe von `get_weather_data` um die Herkunft (8. Element) erweitert entpacken; `rain_last_source` an `_format_weather_section` durchreichen.
- Statt `get_weather_around_hours_ago(24)`: gestrigen Vergleichswert aus `database.get_daily_forecast_snapshot()` lesen, **Datums-Guard**: nur verwenden, wenn `snapshot["date"] == (heute − 1 Tag)`; sonst `yesterday_rain_next = None`.
- `_format_weather_section`: Parameter `rain_last_source` ergänzen. Ist er nicht `"measured"`, den gefallener-Regen-Teil und den Abweichungsvergleich überspringen und stattdessen den Hinweis anhängen.

- [ ] **Step 6: Snapshot-Schreiben nur im geplanten Pfad**

In `send_daily_report()` (nur vom Scheduler aufgerufen) nach `generate_daily_report(today_str)`: den heutigen `rain_next` aus `database.get_last_weather()` (die frische Zeile, die `generate_daily_report` gerade geschrieben hat) lesen und `database.set_daily_forecast_snapshot(today_str, rain_next, window_start)` aufrufen. Reihenfolge sicherstellen: erst generieren (liest gestrigen Snapshot), dann heutigen Snapshot schreiben. `generate_daily_report` (und damit manuelles `/report`) schreibt den Snapshot **nicht**.

- [ ] **Step 7: Tests grün laufen lassen**

```
python -m unittest tests.adapters.test_database tests.adapters.test_daily_report -v
```

- [ ] **Step 8: Commit**

```bash
git add src/daemon/adapters/database.py src/daemon/adapters/daily_report.py tests/adapters/test_database.py tests/adapters/test_daily_report.py
git commit -m "feat: deterministischer Vorhersage-Tagessnapshot + Bericht-Ehrlichkeit bei fehlender Messung"
```

---

### Task 6: `/report` — ein Abruf pro Bericht

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py`
- Test: `tests/ui/test_telegram_ui.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/ui/test_telegram_ui.py` (Referenz: bestehende `_process_message`-Tests, `/report`-Pfad): mocken, dass die frische Abfrage eine bestimmte `weather_history`-Zeile erzeugt, und prüfen, dass die Chart-Caption aus **derselben** Zeile gebaut wird (Caption-Aussage konsistent mit dem Berichtstext, nicht aus einer älteren Cache-Zeile).

- [ ] **Step 2/3: Reihenfolge im `/report`-Handler umstellen**

Im `/report`-Zweig ([telegram_ui.py:749-763]) zuerst den Berichtstext erzeugen (`_generate_daily_report` macht die frische Abfrage und schreibt die neue Zeile), **dann** `generate_weather_chart()` (liest jetzt diese frische Zeile). Sende-Reihenfolge (erst Foto, dann Text) kann erhalten bleiben — entscheidend ist, dass die Chart-Erzeugung nach der frischen Abfrage erfolgt.

- [ ] **Step 4: Tests grün / Step 5: Commit**

```
python -m unittest tests.ui.test_telegram_ui -v
```

```bash
git add src/daemon/ui/telegram_ui.py tests/ui/test_telegram_ui.py
git commit -m "fix: /report nutzt einen Abruf für Chart-Caption und Berichtstext"
```

---

### Task 7: Dokumentation + Abschluss-Testlauf

**Files:**
- Create: `docs/adr/0024-gemessene-vergangenheit-und-vorhersage-getrennt.md`
- Create: `docs/adr/0025-deterministischer-vorhersage-tagessnapshot.md`
- Modify: `docs/adr/0021-giess-empfehlung-als-pure-funktion-in-core.md`
- Modify: `CONTEXT.md`

- [ ] **Step 1: ADR 0024 schreiben**

Entscheidung: `rain_last` aus Archiv/ERA5 (gemessen), `rain_next`/`rain_prob` aus Forecast `best_match`; zwei Calls in `get_weather_data()`; aufruferspezifisches Ausfallverhalten (Skip degradiert, Bericht ehrlich); Herkunfts-Markierung `rain_last_source`. Konsequenzen inkl. `current_idx`-Robustifizierung und ERA5T-Revisions-Hinweis. Verfeinert ADR 0003, referenziert ADR 0020.

- [ ] **Step 2: ADR 0025 schreiben**

Entscheidung: deterministischer Vorhersage-Tagessnapshot in `system_metadata` statt unscharfer ±6h-Suche; schreiben nur im 08:00-Pfad, lesen im gemeinsamen Pfad mit Datums-Guard; `/report` read-only. Referenziert ADR 0012.

- [ ] **Step 3: Notiz an ADR 0021**

Ergänzen, dass `core/watering_advice.py` mit `evaluate_rain_window` realisiert wurde (Skip-/Caption-Scope) und das vollständige `evaluate()` (Feature 0009) diese Basis komponiert.

- [ ] **Step 4: CONTEXT.md schärfen**

„Regen-Fenster": gefallener Anteil = gemessene/Reanalyse-Daten (Archiv/ERA5) des Wetter-Dienstes, erwarteter Anteil = Forecast-Modell. „Wetter-Dienst": zwei Produkte (Vorhersage + gemessene Vergangenheit); _Avoid_ „Wetterstation/Wettersensoren" meint eigene Hardware, nicht die Reanalyse-API.

- [ ] **Step 5: Vollständiger Test-Run + Coverage**

```
python -m unittest discover tests
.\scripts\run_coverage.ps1
```

Erwartet: alle Tests `OK`, keine Regressions, Coverage nicht gefallen.

- [ ] **Step 6: Abschluss-Commit**

```bash
git add docs/adr/0024-gemessene-vergangenheit-und-vorhersage-getrennt.md docs/adr/0025-deterministischer-vorhersage-tagessnapshot.md docs/adr/0021-giess-empfehlung-als-pure-funktion-in-core.md CONTEXT.md
git commit -m "docs: ADR 0024/0025, Notiz an 0021, CONTEXT.md-Schärfungen für Feature 0014"
```

---

## Reihenfolge / Abhängigkeiten

1. **Task 1** (core) — keine Abhängigkeiten.
2. **Task 2** (Persistenz-Markierung) — keine Abhängigkeiten.
3. **Task 3** (Wetter-Adapter) — braucht Task 1 (core) + Task 2 (Event-Feld).
4. **Task 4** (Caption) — braucht Task 1.
5. **Task 5** (Bericht + Snapshot) — braucht Task 2 (Herkunft im Rückgabe-Tupel/Cache) + Task 3 (erweitertes Tupel).
6. **Task 6** (`/report`-Reihenfolge) — braucht Task 5.
7. **Task 7** (Doku + Abschluss) — zuletzt.
