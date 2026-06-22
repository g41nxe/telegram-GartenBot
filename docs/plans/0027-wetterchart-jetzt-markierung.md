# Morgen-Bericht Redesign & Status-Schärfung — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/report` wird ein kontextsensitiver Morgen-Bericht (3–4 Zeilen wenn grün, expandiert bei Problemen); `/status` bekommt „Nächster Guss" und wird von Rauschen bereinigt.

**Architecture:** `daily_report.py` erhält neue reine Hilfsfunktionen (`_is_report_green`, `_format_watering_morning`, `_format_weather_morning`, `_format_morning_report_short`, `_format_morning_report_problem`); `generate_daily_report()` wird in zwei Pfade aufgeteilt. In `telegram_ui.py` ergänzt `_get_next_schedule()` die `handle_status()`-Funktion; Dienste-Status wird auf Nicht-Grün beschränkt; History-Einträge erhalten Volumen und deutsche Quell-Labels. Alle Nachrichten-Änderungen werden synchron in `telegram-nachrichten.html` nachgezogen.

**Tech Stack:** Python 3.11, SQLite via `database.py`, `unittest` + `unittest.mock`, Telegram Bot API (via `telegram_client.py`)

---

## Datei-Übersicht

| Datei | Was ändert sich |
|---|---|
| `src/daemon/adapters/database.py` | Neue Funktion `get_watering_skip_count_last_24h()` |
| `src/daemon/adapters/daily_report.py` | 5 neue Hilfsfunktionen; `generate_daily_report()` refaktoriert |
| `src/daemon/ui/telegram_ui.py` | Neue Funktion `_get_next_schedule()`; `handle_status()` bereinigt |
| `docs/reference/telegram-nachrichten.html` | IST-Stand für `/status` und `/report` aktualisiert |
| `docs/reference/telegram-design-system.html` | Morgen-Bericht-Muster dokumentiert |
| `tests/adapters/test_database.py` | Test für `get_watering_skip_count_last_24h()` |
| `tests/adapters/test_daily_report.py` | 4 neue Testklassen |
| `tests/ui/test_telegram_ui.py` | Tests für `_get_next_schedule()` |

---

## Task 1: `get_watering_skip_count_last_24h()` in database.py

**Files:**
- Modify: `src/daemon/adapters/database.py`
- Test: `tests/adapters/test_database.py`

- [ ] **Schritt 1: Failing Test schreiben**

Füge in `tests/adapters/test_database.py` die neue Testklasse am Ende hinzu (vor `if __name__ == "__main__":`):

```python
class TestGetWateringSkipCountLast24h(unittest.TestCase):

    def setUp(self):
        import daemon.adapters.database as db_module
        self._orig_path = db_module.DB_PATH
        db_module.DB_PATH = Path(tempfile.mkdtemp()) / "test_skip.db"
        db_module.init_db()

    def tearDown(self):
        import daemon.adapters.database as db_module
        db_module.DB_PATH.unlink(missing_ok=True)
        db_module.DB_PATH = self._orig_path

    def _insert_history(self, status: str, minutes_ago: int = 60):
        import daemon.adapters.database as db_module
        from datetime import timedelta
        ts = (datetime.now() - timedelta(minutes=minutes_ago)).isoformat()
        conn = db_module.get_connection()
        conn.execute(
            "INSERT INTO watering_history (timestamp, duration_minutes, source, status) VALUES (?, ?, ?, ?)",
            (ts, 0, "schedule", status)
        )
        conn.commit()
        conn.close()

    def test_no_entries_returns_zero(self):
        import daemon.adapters.database as db_module
        self.assertEqual(db_module.get_watering_skip_count_last_24h(), 0)

    def test_one_skip_returns_one(self):
        import daemon.adapters.database as db_module
        self._insert_history("skipped")
        self.assertEqual(db_module.get_watering_skip_count_last_24h(), 1)

    def test_completed_not_counted(self):
        import daemon.adapters.database as db_module
        self._insert_history("completed")
        self.assertEqual(db_module.get_watering_skip_count_last_24h(), 0)

    def test_old_skip_beyond_24h_not_counted(self):
        import daemon.adapters.database as db_module
        self._insert_history("skipped", minutes_ago=25 * 60)
        self.assertEqual(db_module.get_watering_skip_count_last_24h(), 0)
```

- [ ] **Schritt 2: Test auf Rot prüfen**

```
python -m unittest tests.adapters.test_database.TestGetWateringSkipCountLast24h -v
```

Erwartetes Ergebnis: `AttributeError: module 'daemon.adapters.database' has no attribute 'get_watering_skip_count_last_24h'`

- [ ] **Schritt 3: Implementierung schreiben**

Füge in `src/daemon/adapters/database.py` nach `get_watering_stats_last_24h()` ein:

```python
def get_watering_skip_count_last_24h() -> int:
    """Gibt die Anzahl übersprungener Bewässerungszyklen in den letzten 24h zurück."""
    conn = get_connection()
    try:
        from datetime import timedelta
        time_limit = (datetime.now() - timedelta(hours=24)).isoformat()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM watering_history WHERE status = 'skipped' AND timestamp >= ?",
            (time_limit,)
        )
        return cursor.fetchone()[0] or 0
    except Exception as e:
        logger.error(f"Fehler beim Laden der Übersprungen-Statistik: {e}")
        return 0
    finally:
        conn.close()
```

- [ ] **Schritt 4: Test auf Grün prüfen**

```
python -m unittest tests.adapters.test_database.TestGetWateringSkipCountLast24h -v
```

Erwartetes Ergebnis: `4 tests, 0 failures`

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/adapters/database.py tests/adapters/test_database.py
git commit -m "feat(db): add get_watering_skip_count_last_24h()"
```

---

## Task 2: `_is_report_green()` in daily_report.py

**Files:**
- Modify: `src/daemon/adapters/daily_report.py`
- Test: `tests/adapters/test_daily_report.py`

- [ ] **Schritt 1: Failing Test schreiben**

Füge in `tests/adapters/test_daily_report.py` nach den bestehenden Klassen hinzu:

```python
class TestIsReportGreen(unittest.TestCase):

    def _valve(self, battery=100, abnormal_state="normal", valve_id=1):
        return {"id": valve_id, "battery": battery, "valve_abnormal_state": abnormal_state, "wish_name": "Terrasse"}

    def test_all_healthy_services_ok_returns_true(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config.get_setting", return_value=20):
            mock_db.get_metadata.return_value = None
            result = dr._is_report_green([self._valve()], services_ok=True)
        self.assertTrue(result)

    def test_services_not_ok_returns_false(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config.get_setting", return_value=20):
            mock_db.get_metadata.return_value = None
            result = dr._is_report_green([self._valve()], services_ok=False)
        self.assertFalse(result)

    def test_low_battery_returns_false(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config.get_setting", return_value=20):
            mock_db.get_metadata.return_value = None
            result = dr._is_report_green([self._valve(battery=15)], services_ok=True)
        self.assertFalse(result)

    def test_battery_exactly_at_threshold_returns_false(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config.get_setting", return_value=20):
            mock_db.get_metadata.return_value = None
            result = dr._is_report_green([self._valve(battery=20)], services_ok=True)
        self.assertFalse(result)

    def test_abnormal_state_returns_false(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config.get_setting", return_value=20):
            mock_db.get_metadata.return_value = None
            result = dr._is_report_green([self._valve(abnormal_state="stuck_open")], services_ok=True)
        self.assertFalse(result)

    def test_watchdog_alert_active_returns_false(self):
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.config.get_setting", return_value=20):
            mock_db.get_metadata.return_value = "1"
            result = dr._is_report_green([self._valve()], services_ok=True)
        self.assertFalse(result)

    def test_no_valves_services_ok_returns_true(self):
        result = dr._is_report_green([], services_ok=True)
        self.assertTrue(result)
```

- [ ] **Schritt 2: Test auf Rot prüfen**

```
python -m unittest tests.adapters.test_daily_report.TestIsReportGreen -v
```

Erwartetes Ergebnis: `AttributeError: module 'daemon.adapters.daily_report' has no attribute '_is_report_green'`

- [ ] **Schritt 3: Implementierung schreiben**

Füge in `src/daemon/adapters/daily_report.py` nach `_valve_warnings()` ein:

```python
def _is_report_green(valves: list, services_ok: bool) -> bool:
    """True wenn System und alle Ventile im Normalzustand — Kurzform wird verwendet."""
    if not services_ok:
        return False
    threshold = config.get_setting("BATTERY_WARNING_THRESHOLD", 20)
    for valve in valves:
        battery = valve.get("battery")
        if battery is not None and int(battery) <= threshold:
            return False
        if (valve.get("valve_abnormal_state") or "normal") != "normal":
            return False
        flag_key = f"watchdog_alert_active_valve_{valve['id']}"
        if database.get_metadata(flag_key) == "1":
            return False
    return True
```

- [ ] **Schritt 4: Test auf Grün prüfen**

```
python -m unittest tests.adapters.test_daily_report.TestIsReportGreen -v
```

Erwartetes Ergebnis: `7 tests, 0 failures`

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/adapters/daily_report.py tests/adapters/test_daily_report.py
git commit -m "feat(report): add _is_report_green() predicate"
```

---

## Task 3: `_format_watering_morning()` in daily_report.py

**Files:**
- Modify: `src/daemon/adapters/daily_report.py`
- Test: `tests/adapters/test_daily_report.py`

- [ ] **Schritt 1: Failing Test schreiben**

```python
class TestFormatWateringMorning(unittest.TestCase):

    def test_no_activity_returns_nicht_bewaessert(self):
        result = dr._format_watering_morning(0, 0, 0.0, skip_count=0)
        self.assertIn("nicht bewässert", result)
        self.assertTrue(result.startswith("💧"))

    def test_one_cycle_shows_volume(self):
        result = dr._format_watering_morning(1, 0, 45.0, skip_count=0)
        self.assertIn("1×", result)
        self.assertIn("45", result)
        self.assertTrue(result.startswith("💧"))

    def test_multiple_cycles_shows_gesamt(self):
        result = dr._format_watering_morning(3, 0, 90.0, skip_count=0)
        self.assertIn("3×", result)
        self.assertIn("gesamt", result)

    def test_skip_with_no_success_shows_uebersprungen(self):
        result = dr._format_watering_morning(0, 0, 0.0, skip_count=1, rain_last=2.5)
        self.assertIn("übersprungen", result)
        self.assertIn("2.5", result)
        self.assertTrue(result.startswith("🌧"))

    def test_failed_cycle_noted_but_no_lqi(self):
        result = dr._format_watering_morning(0, 2, 0.0, skip_count=0)
        self.assertIn("Fehler", result)
        self.assertNotIn("LQI", result)

    def test_no_double_asterisk(self):
        result = dr._format_watering_morning(1, 0, 30.0, skip_count=0)
        self.assertNotIn("**", result)
```

- [ ] **Schritt 2: Test auf Rot prüfen**

```
python -m unittest tests.adapters.test_daily_report.TestFormatWateringMorning -v
```

- [ ] **Schritt 3: Implementierung schreiben**

```python
def _format_watering_morning(
    success_count: int,
    failed_count: int,
    total_volume: float,
    skip_count: int = 0,
    rain_last: float = 0.0,
) -> str:
    """Bewässerungs-Zusammenfassung für den Morgen-Bericht (eine Zeile)."""
    if skip_count > 0 and success_count == 0 and failed_count == 0:
        return f"🌧 Guss übersprungen · {rain_last} mm gefallen"
    if success_count == 0 and failed_count == 0:
        return "💧 Gestern nicht bewässert"
    if success_count == 1:
        line = f"💧 Gestern 1× bewässert · {total_volume:.0f} L"
    else:
        line = f"💧 Gestern {success_count}× bewässert · {total_volume:.0f} L gesamt"
    if failed_count == 1:
        line += " · 1 Fehler"
    elif failed_count > 1:
        line += f" · {failed_count} Fehler"
    return line
```

- [ ] **Schritt 4: Test auf Grün prüfen**

```
python -m unittest tests.adapters.test_daily_report.TestFormatWateringMorning -v
```

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/adapters/daily_report.py tests/adapters/test_daily_report.py
git commit -m "feat(report): add _format_watering_morning()"
```

---

## Task 4: `_format_weather_morning()` in daily_report.py

**Files:**
- Modify: `src/daemon/adapters/daily_report.py`
- Test: `tests/adapters/test_daily_report.py`

- [ ] **Schritt 1: Failing Test schreiben**

```python
class TestFormatWeatherMorning(unittest.TestCase):

    def test_dry_day_returns_sunny_emoji(self):
        main, extra = dr._format_weather_morning(14.0, 24.0, "Sonnig", rain_next=0.0, rain_prob=5)
        self.assertIn("☀️", main)
        self.assertIn("14", main)
        self.assertIn("24", main)
        self.assertIsNone(extra)

    def test_light_rain_returns_partly_cloudy_emoji_and_extra_line(self):
        main, extra = dr._format_weather_morning(12.0, 18.0, "Bewölkt", rain_next=0.8, rain_prob=40)
        self.assertIn("🌦", main)
        self.assertIsNotNone(extra)
        self.assertIn("0.8", extra)

    def test_heavy_rain_returns_rain_emoji(self):
        main, extra = dr._format_weather_morning(10.0, 15.0, "Regen", rain_next=8.0, rain_prob=85)
        self.assertIn("🌧", main)
        self.assertIsNotNone(extra)
        self.assertIn("8.0", extra)

    def test_below_threshold_no_extra_line(self):
        main, extra = dr._format_weather_morning(14.0, 22.0, "Leicht bewölkt", rain_next=0.3, rain_prob=10)
        self.assertIsNone(extra)

    def test_no_double_asterisk(self):
        main, extra = dr._format_weather_morning(14.0, 24.0, "Sonnig", rain_next=0.0, rain_prob=5)
        self.assertNotIn("**", main)
```

- [ ] **Schritt 2: Test auf Rot prüfen**

```
python -m unittest tests.adapters.test_daily_report.TestFormatWeatherMorning -v
```

- [ ] **Schritt 3: Implementierung schreiben**

```python
def _format_weather_morning(
    temp_min: float,
    temp_max: float,
    weather_desc: str,
    rain_next: float,
    rain_prob: int,
) -> tuple[str, str | None]:
    """Wetter-Zusammenfassung für den Morgen-Bericht.

    Gibt (Hauptzeile, optionale Regenzeile) zurück.
    """
    if rain_next >= 2.0:
        emoji = "🌧"
    elif rain_next >= 0.5:
        emoji = "🌦"
    else:
        emoji = "☀️"

    main = f"{emoji} Heute {temp_min:.0f}–{temp_max:.0f} °C · {weather_desc} ({rain_prob} % ☂)"

    extra = None
    if rain_next >= 0.5:
        extra = f"🌧 {rain_next} mm erwartet"

    return main, extra
```

- [ ] **Schritt 4: Test auf Grün prüfen**

```
python -m unittest tests.adapters.test_daily_report.TestFormatWeatherMorning -v
```

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/adapters/daily_report.py tests/adapters/test_daily_report.py
git commit -m "feat(report): add _format_weather_morning()"
```

---

## Task 5: Kurzform und Problemfall zusammensetzen

**Files:**
- Modify: `src/daemon/adapters/daily_report.py`
- Test: `tests/adapters/test_daily_report.py`

- [ ] **Schritt 1: Failing Test schreiben**

```python
class TestMorningReportAssembly(unittest.TestCase):

    def test_short_form_starts_with_guten_morgen(self):
        result = dr._format_morning_report_short(
            date_display="Do 19.06.",
            watering_line="💧 Gestern 1× bewässert · 45 L",
            weather_line="☀️ Heute 14–24 °C · Sonnig (5 % ☂)",
            rain_extra_line=None,
        )
        self.assertIn("Guten Morgen", result)
        self.assertIn("✅ System: alles in Ordnung", result)
        self.assertNotIn("LQI", result)

    def test_short_form_includes_rain_extra_when_present(self):
        result = dr._format_morning_report_short(
            date_display="Do 19.06.",
            watering_line="💧 Gestern 1× bewässert · 45 L",
            weather_line="🌦 Heute 12–18 °C · Bewölkt (40 % ☂)",
            rain_extra_line="🌧 0.8 mm erwartet",
        )
        self.assertIn("0.8 mm", result)

    def test_problem_form_shows_issue_first(self):
        result = dr._format_morning_report_problem(
            date_display="Do 19.06.",
            issues=["🟡 Terrasse: Batterie schwach (15%)"],
            watering_line="💧 Gestern 1× bewässert · 45 L",
            weather_line="☀️ Heute 14–24 °C · Sonnig (5 % ☂)",
            rain_extra_line=None,
        )
        self.assertIn("Guten Morgen", result)
        self.assertIn("Batterie schwach", result)
        # Issue muss vor watering line stehen
        self.assertLess(result.index("Batterie"), result.index("bewässert"))

    def test_problem_form_no_double_asterisk(self):
        result = dr._format_morning_report_problem(
            date_display="Do 19.06.",
            issues=["🔴 MQTT-Broker nicht erreichbar"],
            watering_line="💧 Gestern nicht bewässert",
            weather_line="☀️ Heute 14–24 °C · Sonnig (5 % ☂)",
            rain_extra_line=None,
        )
        self.assertNotIn("**", result)
```

- [ ] **Schritt 2: Test auf Rot prüfen**

```
python -m unittest tests.adapters.test_daily_report.TestMorningReportAssembly -v
```

- [ ] **Schritt 3: Implementierung schreiben**

```python
def _format_morning_report_short(
    date_display: str,
    watering_line: str,
    weather_line: str,
    rain_extra_line: str | None,
) -> str:
    parts = [f"🌿 *Guten Morgen, {date_display}!*", ""]
    parts.append(weather_line)
    if rain_extra_line:
        parts.append(rain_extra_line)
    parts.append(watering_line)
    parts.append("✅ System: alles in Ordnung")
    return "\n".join(parts)


def _format_morning_report_problem(
    date_display: str,
    issues: list[str],
    watering_line: str,
    weather_line: str,
    rain_extra_line: str | None,
) -> str:
    parts = [f"🌿 *Guten Morgen, {date_display}!*", ""]
    parts.extend(issues)
    parts.append("")
    parts.append(weather_line)
    if rain_extra_line:
        parts.append(rain_extra_line)
    parts.append(watering_line)
    return "\n".join(parts)
```

- [ ] **Schritt 4: Test auf Grün prüfen**

```
python -m unittest tests.adapters.test_daily_report.TestMorningReportAssembly -v
```

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/adapters/daily_report.py tests/adapters/test_daily_report.py
git commit -m "feat(report): add morning report assembly functions"
```

---

## Task 6: `generate_daily_report()` refaktorieren

**Files:**
- Modify: `src/daemon/adapters/daily_report.py`
- Test: `tests/adapters/test_daily_report.py`

- [ ] **Schritt 1: Failing Tests schreiben**

```python
class TestGenerateDailyReportIntegration(unittest.TestCase):
    """Integrationstests für generate_daily_report() — testet die finale Ausgabe."""

    def _patches(self, **overrides):
        defaults = {
            "success": 1, "failed": 0, "volume": 45.0, "skip_count": 0,
            "valves": [],
            "weather": (0.5, 0.0, 20.0, 0, 14.0, 24.0, 5, "measured"),
            "has_paho": False,
        }
        defaults.update(overrides)
        return defaults

    def _generate(self, **overrides):
        p = self._patches(**overrides)
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.weather") as mock_weather, \
             patch("daemon.adapters.daily_report.mqtt_client") as mock_mqtt:
            mock_db.get_watering_stats_last_24h.return_value = (p["success"], p["failed"], p["volume"])
            mock_db.get_watering_skip_count_last_24h.return_value = p["skip_count"]
            mock_db.get_all_valves.return_value = p["valves"]
            mock_db.get_metadata.return_value = None
            mock_db.get_daily_forecast_snapshot.return_value = None
            mock_weather.get_weather_data.return_value = p["weather"]
            mock_mqtt.HAS_PAHO = p["has_paho"]
            return generate_daily_report("2026-06-19")

    def test_green_case_starts_with_guten_morgen(self):
        from daemon.adapters.daily_report import generate_daily_report
        result = self._generate()
        self.assertIn("Guten Morgen", result)

    def test_green_case_has_system_ok_line(self):
        from daemon.adapters.daily_report import generate_daily_report
        result = self._generate()
        self.assertIn("alles in Ordnung", result)

    def test_green_case_no_lqi_number(self):
        from daemon.adapters.daily_report import generate_daily_report
        result = self._generate()
        self.assertNotIn("LQI", result)
        self.assertNotIn("Meldungen", result)

    def test_green_case_no_old_header(self):
        from daemon.adapters.daily_report import generate_daily_report
        result = self._generate()
        self.assertNotIn("Täglicher Statusbericht", result)

    def test_problem_case_battery_shows_warning(self):
        from daemon.adapters.daily_report import generate_daily_report
        valve = {"id": 1, "wish_name": "Terrasse", "mqtt_name": "garden_valve",
                 "battery": 15, "valve_abnormal_state": "normal", "last_update": None}
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.weather") as mock_weather, \
             patch("daemon.adapters.daily_report.mqtt_client") as mock_mqtt, \
             patch("daemon.adapters.daily_report.config.get_setting", return_value=20):
            mock_db.get_watering_stats_last_24h.return_value = (1, 0, 30.0)
            mock_db.get_watering_skip_count_last_24h.return_value = 0
            mock_db.get_all_valves.return_value = [valve]
            mock_db.get_metadata.return_value = None
            mock_db.get_daily_forecast_snapshot.return_value = None
            mock_weather.get_weather_data.return_value = (0.0, 0.0, 20.0, 0, 14.0, 24.0, 5, "measured")
            mock_mqtt.HAS_PAHO = False
            result = generate_daily_report("2026-06-19")
        self.assertIn("Batterie", result)
        self.assertIn("15", result)
        self.assertNotIn("alles in Ordnung", result)

    def test_problem_case_no_lqi_number(self):
        from daemon.adapters.daily_report import generate_daily_report
        valve = {"id": 1, "wish_name": "Terrasse", "mqtt_name": "garden_valve",
                 "battery": 15, "valve_abnormal_state": "normal", "last_update": None}
        with patch("daemon.adapters.daily_report.database") as mock_db, \
             patch("daemon.adapters.daily_report.weather") as mock_weather, \
             patch("daemon.adapters.daily_report.mqtt_client") as mock_mqtt, \
             patch("daemon.adapters.daily_report.config.get_setting", return_value=20):
            mock_db.get_watering_stats_last_24h.return_value = (0, 0, 0.0)
            mock_db.get_watering_skip_count_last_24h.return_value = 0
            mock_db.get_all_valves.return_value = [valve]
            mock_db.get_metadata.return_value = None
            mock_db.get_daily_forecast_snapshot.return_value = None
            mock_weather.get_weather_data.return_value = (0.0, 0.0, 20.0, 0, 14.0, 24.0, 5, "measured")
            mock_mqtt.HAS_PAHO = False
            result = generate_daily_report("2026-06-19")
        self.assertNotIn("LQI", result)
        self.assertNotIn("Meldungen", result)

    def test_no_double_asterisk_in_any_case(self):
        from daemon.adapters.daily_report import generate_daily_report
        result = self._generate()
        self.assertNotIn("**", result)
```

- [ ] **Schritt 2: Test auf Rot prüfen**

```
python -m unittest tests.adapters.test_daily_report.TestGenerateDailyReportIntegration -v
```

Erwartetes Ergebnis: Tests schlagen fehl, weil `generate_daily_report()` noch den alten Header ausgibt.

- [ ] **Schritt 3: `generate_daily_report()` refaktorieren**

Ersetze die Funktion `generate_daily_report()` in `src/daemon/adapters/daily_report.py` vollständig durch:

```python
def generate_daily_report(today_str: str) -> str:
    """Generiert den Morgen-Bericht (Kurzform wenn grün, Problemfall sonst)."""
    # 1. Guss-Statistiken
    success_count, failed_count, total_volume = database.get_watering_stats_last_24h()
    skip_count = database.get_watering_skip_count_last_24h()

    # 2. Wetterdaten (Live-Abfrage)
    weather_result = None
    try:
        weather_result = weather.get_weather_data(config.LATITUDE, config.LONGITUDE)
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Wetterdaten für Morgen-Bericht: {e}")
    if weather_result is not None:
        rain_last, rain_next, temp, weather_code, temp_min, temp_max, rain_prob, rain_last_source = weather_result
        weather_desc = get_wmo_description(weather_code)
    else:
        rain_last, rain_next, temp, weather_code, temp_min, temp_max, rain_prob, rain_last_source = 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0, "forecast"
        weather_desc = "Unbekannt"

    # 3. Systemzustand
    if mqtt_client.HAS_PAHO:
        broker_ok = mqtt_client.is_broker_connected()
        bridge_ok = mqtt_client.get_bridge_status() == "online"
        services_ok = broker_ok and bridge_ok
    else:
        services_ok = True

    # 4. Ventile
    valves = database.get_all_valves()

    # 5. Datum
    try:
        date_obj = datetime.strptime(today_str, "%Y-%m-%d")
        _days_de = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
        date_display = f"{_days_de[date_obj.weekday()]} {date_obj.strftime('%d.%m.')}"
    except Exception:
        date_display = today_str

    # 6. Gemeinsame Bausteine
    watering_line = _format_watering_morning(success_count, failed_count, total_volume, skip_count, rain_last)
    weather_line, rain_extra = _format_weather_morning(temp_min, temp_max, weather_desc, rain_next, rain_prob)

    # 7. Grün-Prüfung → Pfad wählen
    if _is_report_green(valves, services_ok):
        return _format_morning_report_short(date_display, watering_line, weather_line, rain_extra)

    # Problem-Pfad: Issues aufsammeln
    threshold = config.get_setting("BATTERY_WARNING_THRESHOLD", 20)
    issues = []

    if not services_ok:
        if mqtt_client.HAS_PAHO and not mqtt_client.is_broker_connected():
            issues.append("🔴 MQTT-Broker nicht erreichbar")
        else:
            issues.append("🔴 Mittelweg-Dienst (Zigbee2MQTT) offline")

    for valve in valves:
        wish_name = valve["wish_name"]
        abnormal = (valve.get("valve_abnormal_state") or "normal")
        battery = valve.get("battery")
        flag_key = f"watchdog_alert_active_valve_{valve['id']}"
        has_watchdog = database.get_metadata(flag_key) == "1"

        if abnormal != "normal":
            issues.append(f"🚨 {wish_name}: Anomalie erkannt ({abnormal})")
        elif battery is not None and int(battery) <= threshold:
            issues.append(f"🟡 {wish_name}: Batterie schwach ({battery}%)")
        if has_watchdog:
            issues.append(f"⚠️ {wish_name}: kein Signal (Watchdog aktiv)")

    return _format_morning_report_problem(date_display, issues, watering_line, weather_line, rain_extra)
```

- [ ] **Schritt 4: Test auf Grün prüfen**

```
python -m unittest tests.adapters.test_daily_report -v
```

Alle bestehenden Tests müssen weiterhin bestehen. Erwartetes Ergebnis: 0 failures.

- [ ] **Schritt 5: Vollständige Suite prüfen**

```
python -m unittest discover -v tests
```

- [ ] **Schritt 6: Commit**

```bash
git add src/daemon/adapters/daily_report.py tests/adapters/test_daily_report.py
git commit -m "feat(report): refactor generate_daily_report() into green/problem morning briefing"
```

---

## Task 7: `_get_next_schedule()` in telegram_ui.py

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py`
- Test: `tests/ui/test_telegram_ui.py`

- [ ] **Schritt 1: Failing Tests schreiben**

Füge in `tests/ui/test_telegram_ui.py` eine neue Klasse hinzu:

```python
class TestGetNextSchedule(unittest.TestCase):

    def _sched(self, name, time_str, days, is_active=1):
        return {"id": 1, "name": name, "time": time_str, "days": days,
                "duration_minutes": 15, "target_volume_liters": 30, "is_active": is_active}

    def test_no_schedules_returns_none(self):
        from daemon.ui.telegram_ui import _get_next_schedule
        now = datetime(2026, 6, 19, 14, 0)  # Donnerstag 14:00
        self.assertIsNone(_get_next_schedule([], now))

    def test_inactive_schedule_ignored(self):
        from daemon.ui.telegram_ui import _get_next_schedule
        now = datetime(2026, 6, 19, 14, 0)
        s = self._sched("Rasen", "20:00", "everyday", is_active=0)
        self.assertIsNone(_get_next_schedule([s], now))

    def test_future_schedule_today_returned(self):
        from daemon.ui.telegram_ui import _get_next_schedule
        now = datetime(2026, 6, 19, 14, 0)  # Donnerstag 14:00
        s = self._sched("Rasen", "20:15", "everyday")
        result = _get_next_schedule([s], now)
        self.assertIsNotNone(result)
        self.assertEqual(result["_next_dt"].hour, 20)
        self.assertEqual(result["_next_dt"].minute, 15)
        self.assertEqual(result["_next_dt"].date(), now.date())

    def test_past_schedule_today_rolls_to_tomorrow(self):
        from daemon.ui.telegram_ui import _get_next_schedule
        now = datetime(2026, 6, 19, 21, 0)  # Donnerstag 21:00
        s = self._sched("Rasen", "06:00", "everyday")
        result = _get_next_schedule([s], now)
        self.assertIsNotNone(result)
        self.assertEqual(result["_next_dt"].day, 20)  # Freitag

    def test_wrong_weekday_skips_to_correct_day(self):
        from daemon.ui.telegram_ui import _get_next_schedule
        now = datetime(2026, 6, 19, 14, 0)  # Donnerstag
        s = self._sched("Hochbeet", "06:00", "Mon,Wed,Fri")  # Mo, Mi, Fr
        result = _get_next_schedule([s], now)
        self.assertIsNotNone(result)
        # Nächster passender Tag ist Freitag (20.06.)
        self.assertEqual(result["_next_dt"].weekday(), 4)  # 4 = Freitag

    def test_earliest_of_two_schedules_returned(self):
        from daemon.ui.telegram_ui import _get_next_schedule
        now = datetime(2026, 6, 19, 14, 0)
        s1 = self._sched("Spät", "22:00", "everyday")
        s2 = dict(self._sched("Früh", "16:00", "everyday"))
        s2["id"] = 2
        result = _get_next_schedule([s1, s2], now)
        self.assertEqual(result["name"], "Früh")
```

- [ ] **Schritt 2: Test auf Rot prüfen**

```
python -m unittest tests.ui.test_telegram_ui.TestGetNextSchedule -v
```

- [ ] **Schritt 3: Implementierung schreiben**

Füge in `src/daemon/ui/telegram_ui.py` direkt vor `handle_status()` (Zeile ~615) ein:

```python
_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _get_next_schedule(schedules: list, now: datetime) -> dict | None:
    """Gibt den nächsten aktiven Zeitplan zurück, der nach `now` feuert (inkl. _next_dt)."""
    best = None
    best_delta = None

    for s in schedules:
        if not s.get("is_active"):
            continue
        try:
            h, m = map(int, s["time"].split(":"))
        except (ValueError, KeyError):
            continue
        days_raw = s.get("days", "")
        days = [d.strip() for d in days_raw.split(",")] if days_raw else []

        for offset in range(7):
            candidate = (now + timedelta(days=offset)).replace(
                hour=h, minute=m, second=0, microsecond=0
            )
            if candidate <= now:
                continue
            day_name = _WEEKDAY_NAMES[candidate.weekday()]
            if "everyday" in days or day_name in days:
                delta = (candidate - now).total_seconds()
                if best_delta is None or delta < best_delta:
                    best_delta = delta
                    best = dict(s)
                    best["_next_dt"] = candidate
                break

    return best
```

- [ ] **Schritt 4: Test auf Grün prüfen**

```
python -m unittest tests.ui.test_telegram_ui.TestGetNextSchedule -v
```

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/ui/telegram_ui.py tests/ui/test_telegram_ui.py
git commit -m "feat(status): add _get_next_schedule() for next watering display"
```

---

## Task 8: `handle_status()` bereinigen

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py`

Diese Aufgabe hat keinen isolierbaren Unit-Test (sie montiert viele Mocks). Stattdessen: Änderungen durch Augenschein prüfen und dann Vollständige Suite laufen lassen.

- [ ] **Schritt 1: Dienste-Block auf Nicht-Grün beschränken**

Finde in `handle_status()` die Zeile:
```python
    msg = (
        f"🌱 *Dein Garten auf einen Blick*\n"
        ...
        f"🔌 Dienste: {services_status}\n"
        ...
    )
```

Füge vor dem `msg`-Block ein:
```python
    services_block = f"🔌 Dienste: {services_status}\n" if level != "green" else ""
```

Ersetze `f"🔌 Dienste: {services_status}\n"` im `msg`-String durch `f"{services_block}"`.

- [ ] **Schritt 2: Versionszeile entfernen**

Entferne:
```python
    version_line = f"\n\n_v{_read_local_version()}_"
```
Und entferne `f"{version_line}"` aus dem `msg`-String.

- [ ] **Schritt 3: History-Einträge: Volumen + deutsche Quell-Labels**

Finde den History-Block:
```python
    history_lines = []
    for h in history:
        time_obj = datetime.fromisoformat(h['timestamp'])
        time_str = time_obj.strftime("%d.%m. %H:%M")
        status_char = "✅" if h['status'] == "completed" else "🌧" if h['status'] == "skipped" else "❌"
        history_lines.append(f"{status_char} {time_str} ({h['duration_minutes']} Min, {h['source']})")
```

Ersetze durch:
```python
    _SOURCE_LABELS = {"schedule": "Zeitplan", "manual": "Manuell"}
    history_lines = []
    for h in history:
        time_obj = datetime.fromisoformat(h['timestamp'])
        time_str = time_obj.strftime("%d.%m. %H:%M")
        status_char = "✅" if h['status'] == "completed" else "🌧" if h['status'] == "skipped" else "❌"
        volume = h.get("watered_volume") or 0.0
        source_label = _SOURCE_LABELS.get(h.get("source", ""), h.get("source", ""))
        vol_str = f" · {volume:.0f} L" if volume > 0 else ""
        history_lines.append(
            f"{status_char} {time_str} · {h['duration_minutes']} Min{vol_str} · {source_label}"
        )
```

- [ ] **Schritt 4: Sektion „Nächster Guss" einfügen**

Füge nach dem Valves-Block (nach `valves_text = ...`) und vor dem Cameras-Block ein:

```python
    all_schedules = database.get_schedules()
    active_schedules = [s for s in all_schedules if s.get("is_active")]
    nxt = _get_next_schedule(active_schedules, now)
    next_sched_text = ""
    if nxt:
        nxt_dt = nxt["_next_dt"]
        day_label = "heute" if nxt_dt.date() == now.date() else "morgen"
        next_sched_text = (
            f"\n⏰ *Nächster Guss:* {day_label} {nxt_dt.strftime('%H:%M')} Uhr"
            f" · {nxt['name']} · {nxt['duration_minutes']} Min\n"
        )
```

Füge `f"{next_sched_text}"` im `msg`-String zwischen `📡 Ventile`-Block und `🌡 Wetter`-Block ein.

- [ ] **Schritt 5: Vollständige Suite laufen lassen**

```
python -m unittest discover -v tests
```

Erwartetes Ergebnis: Alle Tests grün. Falls Tests in `test_telegram_ui.py` die `handle_status()`-Ausgabe testen und jetzt scheitern, diese Tests aktualisieren.

- [ ] **Schritt 6: Commit**

```bash
git add src/daemon/ui/telegram_ui.py
git commit -m "feat(status): add next schedule, volume in history, remove version/dienste noise"
```

---

## Task 9: `telegram-nachrichten.html` aktualisieren (IST-Stand)

**Files:**
- Modify: `docs/reference/telegram-nachrichten.html`

- [ ] **Schritt 1: `/status`-Karte aktualisieren**

Finde den Block mit `handle_status() · /status · „📊 Status anzeigen"`.

Ersetze das Bubble-Inhalt so, dass:
- Keine Versionszeile (`v1.2.1`) mehr enthalten ist
- `🔌 Dienste: 🟢 Aktiv` aus der Grün-Variante entfernt ist
- Die Zuletzt-Einträge Volumen und deutsche Labels zeigen: `✅ 17.06. 06:00 · 12 Min · 30 L · Zeitplan`
- Eine neue Zeile `⏰ *Nächster Guss:* heute 20:15 Uhr · Rasen abends · 15 Min` zwischen Ventile und Wetter erscheint

Grün-Bubble Beispiel (ersetze altes):
```html
<div class="bubble">🌱 <b>Dein Garten auf einen Blick</b>
Do, 19.06. · 14:32 Uhr

🟢 Alles im grünen Bereich

📡 <b>Ventile</b>
Terrasse · 🟢 aktiv · 🔋 Voll · 📶 gut

⏰ <b>Nächster Guss:</b> heute 20:15 Uhr · Rasen abends · 15 Min

🌡 <b>Wetter</b>
   <b>Jetzt</b>  Leicht bewölkt · 22.4 °C · 💧 0.0 mm
   <b>15:00</b>  Bedeckt · 22.1 °C · 0.2 mm · 15 %
   <i>(Stand: 14:30 Uhr)</i>

📜 <b>Zuletzt</b>
✅ 17.06. 06:00 · 12 Min · 30 L · Zeitplan
🌧 16.06. 06:00 · 0 Min · Zeitplan
✅ 15.06. 20:15 · 15 Min · 45 L · Manuell</div>
```

Nicht-grüne Variante: Dienste-Zeile bleibt, Versionszeile entfällt.

- [ ] **Schritt 2: `/report`-Karte aktualisieren**

Finde den Block mit `/report · /statusbericht`.

Ersetze die Note und füge zwei Bubble-Beispiele ein — Kurzform (alles grün) und Problemfall:

```html
<div class="phone">
  <div class="src">/report · /statusbericht — Kurzform (alles grün)</div>
  <div class="bubble" style="padding:0; overflow:hidden">
    <div class="photo-ph">📈 [ Wetter-Chart QuickChart.io ]</div>
    <div style="padding:8px 12px">🌦 Wettervorhersage &amp; Niederschlag (nächste 24h)</div>
  </div>
  <div class="bubble">🌿 <b>Guten Morgen, Do 19.06.!</b>

☀️ Heute 14–24 °C · Leicht bewölkt (15 % ☂)
💧 Gestern 1× bewässert · 45 L
✅ System: alles in Ordnung</div>
  <div class="note">Problemfall-Variante (mind. eine Warnung):</div>
  <div class="bubble">🌿 <b>Guten Morgen, Do 19.06.!</b>

🟡 Terrasse: Batterie schwach (15%)

☀️ Heute 14–24 °C · Leicht bewölkt (15 % ☂)
💧 Gestern 1× bewässert · 45 L</div>
  <ul class="variants">
    <li>Kurzform nur wenn: Dienste OK, kein Watchdog, keine Anomalie, alle Batterien über Schwellenwert</li>
    <li>Problem-Reihenfolge: 🔴 Systemausfall → 🚨 Anomalie → 🟡 Batterie → ⚠️ Watchdog</li>
    <li>LQI-Zahlenwerte und Meldungsanzahlen erscheinen nie im Bericht</li>
    <li>Regen-Extrazeile: <code>🌧 0.8 mm erwartet</code> (nur wenn rain_next ≥ 0.5 mm)</li>
  </ul>
</div>
```

- [ ] **Schritt 3: Metadaten im Header aktualisieren**

Aktualisiere das `Stand:`-Datum im `<div class="meta">` auf `2026-06-19` und ergänze „Feature 0025 integriert."

- [ ] **Schritt 4: Commit**

```bash
git add docs/reference/telegram-nachrichten.html
git commit -m "docs(nachrichten): update /status and /report reference for Feature 0025"
```

---

## Task 10: `telegram-design-system.html` ergänzen

**Files:**
- Modify: `docs/reference/telegram-design-system.html`

- [ ] **Schritt 1: Morgen-Bericht-Muster ergänzen**

Finde den Abschnitt zu „Progressive Disclosure" oder dem Tagesbericht (suche nach „Tagesbericht" oder „report"). Füge ein neues Unterkapitel ein:

**Inhalt des neuen Abschnitts (als HTML):**
```html
<h3>Morgen-Bericht (Kurzform / Problemfall)</h3>
<p>Der tägliche Bericht (<code>/report</code>, automatisch 08:00 Uhr) verwendet zwei Modi:</p>
<ul>
  <li><strong>Kurzform</strong> (alles grün, 3–4 Zeilen): Header „🌿 <em>Guten Morgen, {Tag} {Datum}!</em>" + Wetter-Zeile + Bewässerungs-Zeile + „✅ System: alles in Ordnung". Keine technischen Metriken.</li>
  <li><strong>Problemfall</strong>: Gleicher Header, dann Problem-Block (sortiert nach Schwere: 🔴 → 🚨 → 🟡 → ⚠️), dann Wetter + Bewässerung. Nur betroffene Ventile erscheinen — keine LQI-Zahlen, keine Meldungsanzahlen.</li>
</ul>
<p><strong>Nie im Bericht:</strong> LQI-Zahlenwerte, Meldungsanzahl, <code>mqtt_name</code>, „Täglicher Statusbericht"-Header.</p>
```

- [ ] **Schritt 2: Commit**

```bash
git add docs/reference/telegram-design-system.html
git commit -m "docs(design-system): add morning report pattern (Feature 0025)"
```

---

## Task 11: Vollständige Suite & Abschluss

- [ ] **Schritt 1: Alle Tests laufen lassen**

```
python -m unittest discover -v tests
```

Erwartetes Ergebnis: Alle Tests grün, Anzahl Tests gestiegen (neue Klassen aus Tasks 1–7).

- [ ] **Schritt 2: Coverage prüfen**

```powershell
.\scripts\run_coverage.ps1
```

Coverage darf gegenüber `master` nicht gesunken sein. Ziel: `daily_report.py` ≥ 85 %, `telegram_ui.py` ≥ 70 %.

- [ ] **Schritt 3: Feature-Doc als abgeschlossen markieren**

```bash
mv docs/features/0025-morgen-bericht-redesign.md docs/features/completed/0025-morgen-bericht-redesign.md
git add docs/features/completed/0025-morgen-bericht-redesign.md docs/features/0025-morgen-bericht-redesign.md
git commit -m "chore: move Feature 0025 to completed"
```

---

## Selbst-Review

**Spec-Abdeckung:**
| Anforderung | Task |
|---|---|
| Grün-Bedingung (4 Kriterien) | Task 2 |
| Kurzform (3–4 Zeilen) | Task 5, 6 |
| Problemfall mit sortierten Issues | Task 5, 6 |
| LQI-Zahlen dauerhaft entfernt | Task 6 (generate_daily_report) + Tests |
| „Guten Morgen"-Header | Task 5, 6 |
| Regen-Extrazeile ab 0.5 mm | Task 4 |
| `get_watering_skip_count_last_24h` | Task 1 |
| Nächster Guss in /status | Task 7, 8 |
| Dienste-Status nur bei Nicht-Grün | Task 8 |
| Versionszeile entfernt | Task 8 |
| Deutsche Quell-Labels | Task 8 |
| Volumen in History | Task 8 |
| telegram-nachrichten.html sync | Task 9 |
| telegram-design-system.html ergänzt | Task 10 |

**Typ-Konsistenz:** `_get_next_schedule()` gibt `dict | None` zurück mit Key `_next_dt: datetime` — konsistent in Task 7 (Impl.) und Task 8 (Nutzung). `_format_weather_morning()` gibt `tuple[str, str | None]` zurück — konsistent in Task 4 und Task 6.

**Keine Platzhalter gefunden.**
