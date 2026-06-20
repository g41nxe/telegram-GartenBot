# Gießcheck — Bewässerungs-Empfehlung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Neuen Telegram-Befehl `/giesscheck` implementieren, der eine Gieß-Empfehlung mit Begründung aus Regen-Fenster, Tagestemperatur und Hitzestrecke berechnet.

**Architecture:** Pure Bewertungslogik in `core/watering_advice.py` (ADR-0021); neue DB-Funktion `get_daily_max_temps()` in `adapters/database.py`; Handler + Keyboard-Update in `ui/telegram_ui.py`. Kein I/O in core, kein cross-adapter-Import.

**Tech Stack:** Python 3.11, SQLite via bestehende `database.py`-Patterns, `unittest` + `unittest.mock`.

---

### Task 1: Config-Variablen

**Files:**
- Modify: `src/daemon/config.py`
- Modify: `.env.template`

- [ ] **Step 1: Config-Variablen eintragen**

Füge am Ende von `src/daemon/config.py` nach dem `WATCHDOG`-Block ein:

```python
# --- Gießcheck-Empfehlung ---
try:
    GIESSCHECK_HOT_TEMP_C = float(os.getenv("GIESSCHECK_HOT_TEMP_C", "25.0"))
except ValueError:
    GIESSCHECK_HOT_TEMP_C = 25.0

try:
    GIESSCHECK_HOT_DAYS_COUNT = int(os.getenv("GIESSCHECK_HOT_DAYS_COUNT", "3"))
except ValueError:
    GIESSCHECK_HOT_DAYS_COUNT = 3
```

- [ ] **Step 2: .env.template erweitern**

Füge nach dem `WATCHDOG`-Block in `.env.template` ein:

```ini
# --- Gießcheck-Empfehlung ---
# Temperaturschwelle für einen "heißen Tag" in °C (DWD: warmer Tag >= 25°C)
GIESSCHECK_HOT_TEMP_C=25.0
# Mindestanzahl aufeinanderfolgender heißer Tage für "Dringend gießen"
GIESSCHECK_HOT_DAYS_COUNT=3
```

- [ ] **Step 3: Commit**

```bash
git add src/daemon/config.py .env.template
git commit -m "feat: Config-Variablen GIESSCHECK_HOT_TEMP_C und GIESSCHECK_HOT_DAYS_COUNT"
```

---

### Task 2: DB — `get_daily_max_temps()`

**Files:**
- Modify: `src/daemon/adapters/database.py`
- Test: `tests/adapters/test_database.py`

- [ ] **Step 1: Failing test schreiben**

Füge zunächst `timedelta` zur bestehenden Import-Zeile am Anfang von `tests/adapters/test_database.py` hinzu:

```python
# vorher:
from datetime import datetime
# nachher:
from datetime import datetime, timedelta
```

Dann füge am Ende der Datei diese Klasse hinzu:

```python
class TestGetDailyMaxTemps(unittest.TestCase):

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

    def _days_ago(self, n):
        return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")

    def _insert_weather(self, date_str, temp_max):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO weather_history (timestamp, rain_last_24h_mm, rain_next_24h_mm, "
            "current_temp, weather_code, temp_min, temp_max, rain_probability) "
            "VALUES (?, 0, 0, 20, 0, 15, ?, 0)",
            (f"{date_str}T12:00:00", temp_max),
        )
        conn.commit()
        conn.close()

    def test_returns_past_days_newest_first(self):
        self._insert_weather(self._days_ago(3), 28.0)
        self._insert_weather(self._days_ago(2), 30.0)
        self._insert_weather(self._days_ago(1), 26.0)
        result = db.get_daily_max_temps(5)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0][0], self._days_ago(1))
        self.assertAlmostEqual(result[0][1], 26.0)
        self.assertEqual(result[1][0], self._days_ago(2))
        self.assertAlmostEqual(result[1][1], 30.0)

    def test_excludes_today(self):
        today = datetime.now().strftime("%Y-%m-%d")
        self._insert_weather(today, 35.0)
        result = db.get_daily_max_temps(5)
        self.assertEqual(result, [])

    def test_returns_max_per_day_when_multiple_entries(self):
        self._insert_weather(self._days_ago(1), 25.0)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO weather_history (timestamp, rain_last_24h_mm, rain_next_24h_mm, "
            "current_temp, weather_code, temp_min, temp_max, rain_probability) "
            "VALUES (?, 0, 0, 20, 0, 15, ?, 0)",
            (f"{self._days_ago(1)}T18:00:00", 31.0),
        )
        conn.commit()
        conn.close()
        result = db.get_daily_max_temps(5)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0][1], 31.0)

    def test_empty_when_no_data(self):
        result = db.get_daily_max_temps(5)
        self.assertEqual(result, [])

    def test_respects_days_limit(self):
        for i in range(1, 8):
            self._insert_weather(self._days_ago(i), float(20 + i))
        result = db.get_daily_max_temps(3)
        self.assertEqual(len(result), 3)
```

- [ ] **Step 2: Test scheitern lassen**

```
python -m unittest tests.adapters.test_database.TestGetDailyMaxTemps -v
```

Erwartetes Ergebnis: `AttributeError: module 'daemon.adapters.database' has no attribute 'get_daily_max_temps'`

- [ ] **Step 3: Funktion implementieren**

Füge in `src/daemon/adapters/database.py` nach `get_last_weather()` ein:

```python
def get_daily_max_temps(days: int = 5) -> list[tuple[str, float]]:
    """Gibt (date_str, max_temp) pro abgeschlossenem Vortag zurück, neueste zuerst."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT date(timestamp) AS day, MAX(temp_max)
            FROM weather_history
            WHERE date(timestamp) < date('now')
            GROUP BY day
            ORDER BY day DESC
            LIMIT ?
            """,
            (days,),
        )
        return [(row[0], float(row[1])) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Fehler beim Laden der täglichen Temperatur-Maxima: {e}")
        return []
    finally:
        conn.close()
```

- [ ] **Step 4: Tests grün laufen lassen**

```
python -m unittest tests.adapters.test_database.TestGetDailyMaxTemps -v
```

Erwartetes Ergebnis: 5 Tests, alle `OK`

- [ ] **Step 5: Commit**

```bash
git add src/daemon/adapters/database.py tests/adapters/test_database.py
git commit -m "feat: database.get_daily_max_temps() für Hitzestrecken-Berechnung"
```

---

### Task 3: Core — `watering_advice.evaluate()`

**Files:**
- Create: `src/daemon/core/watering_advice.py`
- Create: `tests/core/test_watering_advice.py`

- [ ] **Step 1: Failing test schreiben**

Erstelle `tests/core/test_watering_advice.py`:

```python
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import daemon.core.watering_advice as advice


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _hot_days(n: int, temp: float = 28.0) -> list[tuple[str, float]]:
    """n aufeinanderfolgende heiße Vortage, neueste zuerst."""
    return [(_days_ago(i), temp) for i in range(1, n + 1)]


def _cold_days(n: int, temp: float = 15.0) -> list[tuple[str, float]]:
    return [(_days_ago(i), temp) for i in range(1, n + 1)]


DRY_RAIN = 0.5   # Gesamt unter RAIN_THRESHOLD_MM=3.0
WET_RAIN = 5.0   # Gesamt über Schwellenwert
HOT_TEMP = 28.0  # Über GIESSCHECK_HOT_TEMP_C=25.0
COLD_TEMP = 15.0


class TestEvaluate(unittest.TestCase):

    def _eval(
        self,
        rain_last: float = DRY_RAIN,
        rain_next: float = DRY_RAIN,
        temp_today: float = COLD_TEMP,
        past: list | None = None,
    ) -> tuple[str, list[str]]:
        return advice.evaluate(rain_last, rain_next, temp_today, past or [])

    # --- Verdict-Matrix (alle 5 Zeilen) ---

    def test_wet_always_returns_no_watering(self):
        verdict, _ = self._eval(rain_last=2.5, rain_next=1.5, temp_today=COLD_TEMP)
        self.assertIn("✅", verdict)

    def test_wet_hot_streak_still_returns_no_watering(self):
        verdict, _ = self._eval(rain_last=2.0, rain_next=2.0, temp_today=HOT_TEMP, past=_hot_days(4))
        self.assertIn("✅", verdict)

    def test_dry_cold_no_streak_returns_situational(self):
        verdict, _ = self._eval(temp_today=COLD_TEMP, past=_cold_days(3))
        self.assertIn("ℹ️", verdict)

    def test_dry_cold_today_with_streak_returns_recommended(self):
        verdict, _ = self._eval(temp_today=COLD_TEMP, past=_hot_days(3))
        self.assertIn("⚠️", verdict)

    def test_dry_hot_today_no_streak_returns_recommended(self):
        verdict, _ = self._eval(temp_today=HOT_TEMP, past=_cold_days(3))
        self.assertIn("⚠️", verdict)

    def test_dry_hot_with_streak_returns_urgent(self):
        verdict, _ = self._eval(temp_today=HOT_TEMP, past=_hot_days(3))
        self.assertIn("🔴", verdict)

    # --- Streak-Randfälle ---

    def test_streak_breaks_on_cool_day(self):
        past = [(_days_ago(1), 28.0), (_days_ago(2), 15.0), (_days_ago(3), 28.0)]
        verdict, _ = self._eval(temp_today=HOT_TEMP, past=past)
        # Streak = 1 (nur gestern), nicht >= 3 → ⚠️ statt 🔴
        self.assertIn("⚠️", verdict)

    def test_streak_breaks_on_date_gap(self):
        # Tag 2 fehlt (Steuerzentrale offline) → Streak abbricht nach Tag 1
        past = [(_days_ago(1), 28.0), (_days_ago(3), 28.0), (_days_ago(4), 28.0)]
        verdict, _ = self._eval(temp_today=HOT_TEMP, past=past)
        # Streak = 1, nicht >= 3 → ⚠️ statt 🔴
        self.assertIn("⚠️", verdict)

    def test_empty_past_no_crash(self):
        verdict, reasons = self._eval(temp_today=HOT_TEMP, past=[])
        self.assertIn("⚠️", verdict)
        self.assertIsInstance(reasons, list)
        self.assertGreater(len(reasons), 0)

    # --- Begründungszeilen ---

    def test_dry_reason_contains_total_mm(self):
        _, reasons = self._eval(rain_last=0.5, rain_next=0.3)
        self.assertTrue(any("0.8 mm" in r for r in reasons))

    def test_wet_reason_contains_total_mm(self):
        _, reasons = self._eval(rain_last=2.0, rain_next=2.0)
        self.assertTrue(any("4.0 mm" in r for r in reasons))

    def test_streak_reason_contains_count(self):
        _, reasons = self._eval(temp_today=HOT_TEMP, past=_hot_days(3))
        self.assertTrue(any("3" in r and "heiß" in r.lower() for r in reasons))
```

- [ ] **Step 2: Test scheitern lassen**

```
python -m unittest tests.core.test_watering_advice -v
```

Erwartetes Ergebnis: `ModuleNotFoundError: No module named 'daemon.core.watering_advice'`

- [ ] **Step 3: Modul implementieren**

Erstelle `src/daemon/core/watering_advice.py`:

```python
import datetime
from .. import config


def evaluate(
    rain_last_24h_mm: float,
    rain_next_24h_mm: float,
    temp_max_today: float,
    past_daily_temps: list[tuple[str, float]],
) -> tuple[str, list[str]]:
    """
    Berechnet eine Gieß-Empfehlung aus Regen-Fenster, Tagestemperatur und Hitzestrecke.

    past_daily_temps: [(date_str, temp_max), ...] abgeschlossene Vortage, neueste zuerst.
    Gibt (verdict, reasons) zurück — verdict ist ein Emoji + Label, reasons sind erklärende Sätze.
    """
    total_rain = rain_last_24h_mm + rain_next_24h_mm
    dry = total_rain < config.RAIN_THRESHOLD_MM
    hot_today = temp_max_today >= config.GIESSCHECK_HOT_TEMP_C

    # Datums-aware Streak (ADR-0022): Lücke = Steuerzentrale war offline → Streak bricht ab
    streak = 0
    prev_date = None
    for date_str, temp_max in past_daily_temps:
        try:
            day = datetime.date.fromisoformat(date_str)
        except ValueError:
            break
        if prev_date is not None and (prev_date - day).days != 1:
            break
        if temp_max >= config.GIESSCHECK_HOT_TEMP_C:
            streak += 1
            prev_date = day
        else:
            break

    hot_streak = streak >= config.GIESSCHECK_HOT_DAYS_COUNT

    # Begründungszeilen
    reasons: list[str] = []
    if dry:
        reasons.append(
            f"Kein nennenswerter Regen in den letzten/nächsten 48h ({total_rain:.1f} mm gesamt)."
        )
    else:
        reasons.append(f"Ausreichend Regen im 48h-Fenster ({total_rain:.1f} mm gesamt).")
    reasons.append(f"Temperatur heute: {temp_max_today:.0f}°C.")
    if hot_streak:
        reasons.append(
            f"Bereits {streak} heiße Tage in Folge (≥{config.GIESSCHECK_HOT_TEMP_C:.0f}°C)."
        )

    # Verdict
    if not dry:
        verdict = "✅ Kein Gießen nötig"
    elif not hot_today and not hot_streak:
        verdict = "ℹ️ Situationsabhängig"
    elif hot_today and hot_streak:
        verdict = "🔴 Dringend gießen"
    else:
        verdict = "⚠️ Gießen empfohlen"

    return verdict, reasons
```

- [ ] **Step 4: Tests grün laufen lassen**

```
python -m unittest tests.core.test_watering_advice -v
```

Erwartetes Ergebnis: 13 Tests, alle `OK`

- [ ] **Step 5: Commit**

```bash
git add src/daemon/core/watering_advice.py tests/core/test_watering_advice.py
git commit -m "feat: core.watering_advice.evaluate() — Gieß-Empfehlung pure Funktion"
```

---

### Task 4: UI — Keyboard + Handler

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py`
- Test: `tests/ui/test_telegram_ui.py`

- [ ] **Step 1: Failing test schreiben**

Füge am Ende von `tests/ui/test_telegram_ui.py` hinzu:

```python
class TestGiesscheckHandler(unittest.TestCase):

    def setUp(self):
        wizard_states.clear()
        manual_states.clear()

    def tearDown(self):
        wizard_states.clear()
        manual_states.clear()

    def _msg(self, text: str, chat_id: int = 1) -> dict:
        return {"chat": {"id": chat_id}, "text": text}

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_no_weather_data_sends_error_message(self, mock_client, mock_db):
        mock_db.get_last_weather.return_value = None
        _process_message(self._msg("💧 Gießcheck"))
        mock_client.send_message.assert_called_once()
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("Keine Wetterdaten", text)

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_button_sends_verdict_message(self, mock_client, mock_db):
        mock_db.get_last_weather.return_value = {
            "rain_last_24h_mm": 0.2,
            "rain_next_24h_mm": 0.1,
            "temp_max": 28.0,
        }
        mock_db.get_daily_max_temps.return_value = []
        _process_message(self._msg("💧 Gießcheck"))
        mock_client.send_message.assert_called_once()
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("💧 Gießcheck", text)
        self.assertIn("⚠️", text)

    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_slash_command_triggers_same_handler(self, mock_client, mock_db):
        mock_db.get_last_weather.return_value = {
            "rain_last_24h_mm": 2.0,
            "rain_next_24h_mm": 2.0,
            "temp_max": 15.0,
        }
        mock_db.get_daily_max_temps.return_value = []
        _process_message(self._msg("/giesscheck"))
        mock_client.send_message.assert_called_once()
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("✅", text)
```

- [ ] **Step 2: Test scheitern lassen**

```
python -m unittest tests.ui.test_telegram_ui.TestGiesscheckHandler -v
```

Erwartetes Ergebnis: 3 Tests `FAIL` — Handler nicht gefunden

- [ ] **Step 3: Import in telegram_ui.py ergänzen**

In `src/daemon/ui/telegram_ui.py`, nach der bestehenden Import-Zeile
`from ..core.watchdog_events import InactivityAlertTriggered, InactivityAlertResolved` einfügen:

```python
from ..core import watering_advice
```

- [ ] **Step 4: Handler-Funktion hinzufügen**

Füge in `src/daemon/ui/telegram_ui.py` nach der Funktion `handle_status()` ein:

```python
def handle_giesscheck(chat_id: int):
    weather = database.get_last_weather()
    if weather is None:
        telegram_client.send_message(
            chat_id,
            "⚠️ Keine Wetterdaten verfügbar. Bitte später erneut versuchen.",
            get_main_keyboard(),
        )
        return
    past = database.get_daily_max_temps(5)
    verdict, reasons = watering_advice.evaluate(
        weather["rain_last_24h_mm"],
        weather["rain_next_24h_mm"],
        weather["temp_max"],
        past,
    )
    reason_text = "\n".join(f"• {r}" for r in reasons)
    telegram_client.send_message(
        chat_id,
        f"💧 Gießcheck\n\n{verdict}\n\n{reason_text}",
        get_main_keyboard(),
    )
```

- [ ] **Step 5: elif-Branch in `_process_message()` eintragen**

Füge in `_process_message()` nach dem Branch für `📊 Status anzeigen` ein:

```python
elif text == "💧 Gießcheck" or text.startswith("/giesscheck"):
    handle_giesscheck(chat_id)
```

- [ ] **Step 6: Wizard-Abbruchlisten erweitern**

In `_process_message()` gibt es zwei Stellen mit einer `text in [...]`-Liste (für Wizard- und Manual-State-Abbruch). Ergänze `"💧 Gießcheck"` in **beiden** Listen:

```python
# Stelle 1 (wizard_states-Abbruch):
if text.startswith("/") or text in [
    "📊 Status anzeigen", "📅 Zeitsteuerung", "📅 Zeitpläne",
    "🟢 Bewässern starten", "🔴 Sofort Stopp", "💧 Gießcheck"
]:

# Stelle 2 (manual_states-Abbruch) — identische Änderung:
if text.startswith("/") or text in [
    "📊 Status anzeigen", "📅 Zeitsteuerung", "📅 Zeitpläne",
    "🟢 Bewässern starten", "🔴 Sofort Stopp", "💧 Gießcheck"
]:
```

- [ ] **Step 7: Hauptmenü umbauen**

Ersetze in `get_main_keyboard()` die `rows`-Liste:

```python
rows = [
    [{"text": "📊 Status anzeigen"}, {"text": "💧 Gießcheck"}],
    [{"text": "🟢 Bewässern starten"}, {"text": "🔴 Sofort Stopp"}],
    [{"text": "📅 Zeitpläne"}, {"text": "🔧 Ventil koppeln"}],
]
```

- [ ] **Step 8: Tests grün laufen lassen**

```
python -m unittest tests.ui.test_telegram_ui.TestGiesscheckHandler -v
```

Erwartetes Ergebnis: 3 Tests, alle `OK`

- [ ] **Step 9: Commit**

```bash
git add src/daemon/ui/telegram_ui.py tests/ui/test_telegram_ui.py
git commit -m "feat: /giesscheck Handler, Hauptmenü-Umbau, Wizard-Abbruchlisten"
```

---

### Task 5: Docs + Abschluss-Testlauf

**Files:**
- Modify: `docs/assets/bot_description.md`

- [ ] **Step 1: Bot-Beschreibung ergänzen**

Öffne `docs/assets/bot_description.md` und ergänze `/giesscheck` in der Befehlsliste:

```markdown
/giesscheck - Bewässerungs-Empfehlung für heute (Regen-Fenster, Temperatur, Hitzestrecke)
```

- [ ] **Step 2: Vollständigen Test-Run ausführen**

```
python -m pytest tests
```

Erwartetes Ergebnis: Alle Tests `OK`, keine Regressions.

- [ ] **Step 3: Abschluss-Commit**

```bash
git add docs/assets/bot_description.md
git commit -m "docs: /giesscheck in Bot-Beschreibung eingetragen"
```
