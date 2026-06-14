# Verbaler Tagesbericht Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Täglichen Statusbericht und `/report` auf verbale Beschreibungen umstellen und beide auf exakt denselben Codepfad konsolidieren.

**Architecture:** `generate_daily_report()` in `daily_report.py` bekommt verbale Texterzeugungsfunktionen. Eine neue DB-Abfrage liefert die gestrige Regenvorhersage für den Abweichungsvergleich. Der `/report`-Handler in `telegram_ui.py` wird auf `send_daily_report()` + `broadcast_photo` umgestellt, damit Chart und Text über denselben Pfad laufen wie beim automatischen 8:00-Report — ausgenommen der Zustellung: `/report` sendet nur an den anfragenden Chat.

**Tech Stack:** Python 3.11, SQLite, unittest, unittest.mock

---

## Dateien

| Datei | Änderung |
|---|---|
| `src/daemon/adapters/database.py` | Neue Funktion `get_weather_around_hours_ago()` |
| `src/daemon/adapters/daily_report.py` | Verbale Texterzeugung in `generate_daily_report()` |
| `src/daemon/ui/telegram_ui.py` | `/report`-Handler vereinfachen |
| `tests/adapters/test_database.py` | Test für `get_weather_around_hours_ago()` |
| `tests/adapters/test_daily_report.py` | Neue Testdatei für verbale Texterzeugung |

---

## Task 1: DB-Abfrage für gestrige Regenvorhersage

**Zweck:** Vergleich "Regen gestern erwartet" vs. "tatsächlich gefallen" benötigt den `rain_next_24h_mm`-Wert von vor ~24h.

**Files:**
- Modify: `src/daemon/adapters/database.py`
- Test: `tests/adapters/test_database.py`

- [ ] **Schritt 1: Failing test schreiben**

In `tests/adapters/test_database.py`, neue Testklasse `TestGetWeatherAroundHoursAgo` hinzufügen:

```python
class TestGetWeatherAroundHoursAgo(unittest.TestCase):

    def setUp(self):
        self.db_path = _make_temp_db()
        self._patcher = patch.object(db, "DB_PATH", self.db_path)
        self._patcher.start()
        db.init_db()

    def tearDown(self):
        self._patcher.stop()
        import gc; gc.collect()
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def _insert_weather(self, hours_ago: float, rain_next: float):
        from datetime import datetime, timedelta
        ts = (datetime.now() - timedelta(hours=hours_ago)).isoformat()
        conn = db.get_connection()
        conn.execute(
            "INSERT INTO weather_history (timestamp, rain_last_24h_mm, rain_next_24h_mm, current_temp, weather_code, temp_min, temp_max, rain_probability) VALUES (?,?,?,?,?,?,?,?)",
            (ts, 0.0, rain_next, 20.0, 0, 15.0, 25.0, 10)
        )
        conn.commit()
        conn.close()

    def test_returns_record_closest_to_24h_ago(self):
        self._insert_weather(23.0, 3.0)   # am nächsten zu 24h
        self._insert_weather(25.0, 7.0)   # weiter weg
        self._insert_weather(1.0, 0.5)    # zu frisch
        result = db.get_weather_around_hours_ago(24)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["rain_next_24h_mm"], 3.0)

    def test_returns_none_when_no_records(self):
        result = db.get_weather_around_hours_ago(24)
        self.assertIsNone(result)

    def test_returns_none_when_closest_is_too_old(self):
        self._insert_weather(50.0, 5.0)
        result = db.get_weather_around_hours_ago(24, max_offset_hours=12)
        self.assertIsNone(result)
```

- [ ] **Schritt 2: Test ausführen — muss FAIL sein**

```powershell
python -m unittest tests.adapters.test_database.TestGetWeatherAroundHoursAgo -v
```

Erwartet: `AttributeError: module ... has no attribute 'get_weather_around_hours_ago'`

- [ ] **Schritt 3: Funktion in `database.py` implementieren**

Nach `get_last_weather()` (Zeile ~328) einfügen:

```python
def get_weather_around_hours_ago(hours: int, max_offset_hours: int = 6) -> dict | None:
    """Gibt den Wettereintrag zurück, dessen Zeitstempel am nächsten an `hours` Stunden zurückliegt.
    Gibt None zurück, wenn kein Eintrag innerhalb von max_offset_hours existiert."""
    from datetime import timedelta
    target = datetime.now() - timedelta(hours=hours)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM weather_history ORDER BY ABS(JULIANDAY(timestamp) - JULIANDAY(?)) LIMIT 1",
            (target.isoformat(),)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        record_time = datetime.fromisoformat(row["timestamp"])
        if abs((record_time - target).total_seconds()) > max_offset_hours * 3600:
            return None
        return dict(row)
    except Exception as e:
        logger.error(f"Fehler beim Laden des Wettereintrags vor {hours}h: {e}")
        return None
    finally:
        conn.close()
```

- [ ] **Schritt 4: Tests ausführen — müssen PASS sein**

```powershell
python -m unittest tests.adapters.test_database.TestGetWeatherAroundHoursAgo -v
```

Erwartet: 3 Tests PASS

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/adapters/database.py tests/adapters/test_database.py
git commit -m "feat: get_weather_around_hours_ago für Regenvorhersage-Abweichung"
```

---

## Task 2: Verbale Texterzeugung in `daily_report.py`

**Zweck:** Die drei Abschnitte (Bewässerung, Wetter, Ventile) in `generate_daily_report()` werden durch verbale Beschreibungen ersetzt.

**Files:**
- Modify: `src/daemon/adapters/daily_report.py`
- Create: `tests/adapters/test_daily_report.py`

### Schritt 2a: Neue Testdatei anlegen

- [ ] **Schritt 1: Testdatei mit failing tests erstellen**

Neue Datei `tests/adapters/test_daily_report.py`:

```python
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import daemon.adapters.database as db
import daemon.adapters.daily_report as dr


class TestVerbalWateringSection(unittest.TestCase):

    def test_zero_cycles(self):
        result = dr._format_watering_section(0, 0, 0.0)
        self.assertIn("nicht bewässert", result)

    def test_one_cycle(self):
        result = dr._format_watering_section(1, 0, 6.0)
        self.assertIn("1×", result)
        self.assertIn("6", result)
        self.assertNotIn("fehlgeschlagen", result)

    def test_multiple_cycles_with_failure(self):
        result = dr._format_watering_section(2, 1, 12.0)
        self.assertIn("2×", result)
        self.assertIn("1 Zyklus fehlgeschlagen", result)

    def test_multiple_failures(self):
        result = dr._format_watering_section(0, 3, 0.0)
        self.assertIn("3 Zyklen fehlgeschlagen", result)


class TestVerbalWeatherSection(unittest.TestCase):

    def test_no_rain_no_forecast(self):
        result = dr._format_weather_section(
            temp=22.0, temp_min=15.0, temp_max=26.0,
            weather_desc="Leicht bewölkt",
            rain_last=0.0, rain_next=0.5, rain_prob=10,
            yesterday_rain_next=None,
        )
        self.assertIn("Leicht bewölkt", result)
        self.assertIn("15", result)
        self.assertIn("26", result)
        self.assertNotIn("erwartet", result.split("wenig erwartet")[0] if "wenig erwartet" in result else result)

    def test_significant_less_rain_than_forecast(self):
        result = dr._format_weather_section(
            temp=18.0, temp_min=12.0, temp_max=22.0,
            weather_desc="Bewölkt",
            rain_last=0.3, rain_next=1.0, rain_prob=20,
            yesterday_rain_next=6.0,
        )
        self.assertIn("weniger Regen", result)
        self.assertIn("0.3", result)
        self.assertIn("6.0", result)

    def test_significant_more_rain_than_forecast(self):
        result = dr._format_weather_section(
            temp=14.0, temp_min=10.0, temp_max=18.0,
            weather_desc="Regnerisch",
            rain_last=9.0, rain_next=2.0, rain_prob=40,
            yesterday_rain_next=1.0,
        )
        self.assertIn("mehr Regen", result)
        self.assertIn("9.0", result)
        self.assertIn("1.0", result)

    def test_insignificant_deviation_not_shown(self):
        result = dr._format_weather_section(
            temp=20.0, temp_min=14.0, temp_max=24.0,
            weather_desc="Sonnig",
            rain_last=1.5, rain_next=0.0, rain_prob=5,
            yesterday_rain_next=2.0,  # Abweichung 0.5mm — unter Schwellenwert
        )
        self.assertNotIn("erwartet:", result)

    def test_heavy_rain_forecast(self):
        result = dr._format_weather_section(
            temp=15.0, temp_min=10.0, temp_max=18.0,
            weather_desc="Gewitter",
            rain_last=0.0, rain_next=15.0, rain_prob=80,
            yesterday_rain_next=None,
        )
        self.assertIn("starker Regen", result)

    def test_moderate_rain_forecast(self):
        result = dr._format_weather_section(
            temp=17.0, temp_min=12.0, temp_max=21.0,
            weather_desc="Bewölkt",
            rain_last=0.0, rain_next=5.0, rain_prob=55,
            yesterday_rain_next=None,
        )
        self.assertIn("mäßiger Regen", result)


class TestVerbalValveSection(unittest.TestCase):

    def test_good_signal(self):
        result = dr._format_valve_line(
            wish_name="Vorgarten", mqtt_name="garden_valve",
            count=48, avg_lqi=145.0, max_gap_hours=1.5,
            has_watchdog_alert=False, battery=100, abnormal_state="normal",
        )
        self.assertIn("Vorgarten", result)
        self.assertIn("gutes Signal", result)

    def test_very_good_signal(self):
        result = dr._format_valve_line(
            wish_name="Vorgarten", mqtt_name="garden_valve",
            count=48, avg_lqi=185.0, max_gap_hours=0.5,
            has_watchdog_alert=False, battery=100, abnormal_state="normal",
        )
        self.assertIn("sehr gutes Signal", result)

    def test_no_connection(self):
        result = dr._format_valve_line(
            wish_name="Vorgarten", mqtt_name="garden_valve",
            count=0, avg_lqi=0.0, max_gap_hours=0.0,
            has_watchdog_alert=False, battery=100, abnormal_state="normal",
        )
        self.assertIn("Keine Verbindung", result)
        self.assertIn("⚠️", result)

    def test_watchdog_alert(self):
        result = dr._format_valve_line(
            wish_name="Vorgarten", mqtt_name="garden_valve",
            count=5, avg_lqi=80.0, max_gap_hours=15.0,
            has_watchdog_alert=True, battery=100, abnormal_state="normal",
        )
        self.assertIn("⚠️", result)

    def test_low_battery(self):
        result = dr._format_valve_line(
            wish_name="Vorgarten", mqtt_name="garden_valve",
            count=20, avg_lqi=130.0, max_gap_hours=2.0,
            has_watchdog_alert=False, battery=15, abnormal_state="normal",
        )
        self.assertIn("🪫", result)

    def test_abnormal_state(self):
        result = dr._format_valve_line(
            wish_name="Vorgarten", mqtt_name="garden_valve",
            count=20, avg_lqi=130.0, max_gap_hours=2.0,
            has_watchdog_alert=False, battery=100, abnormal_state="stuck_open",
        )
        self.assertIn("🚨", result)
```

- [ ] **Schritt 2: Tests ausführen — müssen FAIL sein**

```powershell
python -m unittest tests.adapters.test_daily_report -v
```

Erwartet: `AttributeError: module ... has no attribute '_format_watering_section'`

### Schritt 2b: Hilfsfunktionen implementieren

- [ ] **Schritt 3: Drei Hilfsfunktionen in `daily_report.py` implementieren**

Die folgenden Funktionen **vor** `generate_daily_report()` einfügen (nach `_valve_warnings()`):

```python
_RAIN_DEVIATION_THRESHOLD_MM = 2.0  # DWD-Schwellenwert für signifikante Abweichung


def _format_watering_section(success_count: int, failed_count: int, total_volume: float) -> str:
    if success_count == 0 and failed_count == 0:
        return "💧 In den letzten 24h wurde nicht bewässert."
    if success_count == 1:
        base = f"💧 In den letzten 24h wurde 1× bewässert — {total_volume} Liter gesamt."
    else:
        base = f"💧 In den letzten 24h wurde {success_count}× bewässert — {total_volume} Liter gesamt."
    if failed_count == 1:
        base += " 1 Zyklus fehlgeschlagen."
    elif failed_count > 1:
        base += f" {failed_count} Zyklen fehlgeschlagen."
    return base


def _format_weather_section(
    temp: float, temp_min: float, temp_max: float,
    weather_desc: str,
    rain_last: float, rain_next: float, rain_prob: int,
    yesterday_rain_next: float | None,
) -> str:
    parts = [f"🌤️ {weather_desc}, heute {temp_min}–{temp_max} °C."]

    # Regenabweichung (nur bei signifikanter Differenz)
    if yesterday_rain_next is not None:
        deviation = rain_last - yesterday_rain_next
        if deviation > _RAIN_DEVIATION_THRESHOLD_MM:
            parts.append(
                f"Mehr Regen als erwartet: {rain_last} mm gefallen (Vorhersage gestern: {yesterday_rain_next} mm)."
            )
        elif deviation < -_RAIN_DEVIATION_THRESHOLD_MM:
            parts.append(
                f"Weniger Regen als erwartet: {rain_last} mm gefallen (Vorhersage gestern: {yesterday_rain_next} mm)."
            )
        elif rain_last > 0:
            parts.append(f"{rain_last} mm Regen gefallen.")
    elif rain_last > 0:
        parts.append(f"{rain_last} mm Regen gefallen.")

    # Vorhersage
    if rain_next > 10.0:
        parts.append(f"Heute starker Regen erwartet ({rain_next} mm, {rain_prob}%).")
    elif rain_next >= 2.0:
        parts.append(f"Heute mäßiger Regen erwartet ({rain_next} mm, {rain_prob}%).")
    elif rain_next > 0:
        parts.append(f"Heute wenig Regen erwartet ({rain_next} mm, {rain_prob}%).")
    else:
        parts.append(f"Heute trocken ({rain_prob}% Regenwahrscheinlichkeit).")

    return " ".join(parts)


def _format_valve_line(
    wish_name: str, mqtt_name: str,
    count: int, avg_lqi: float, max_gap_hours: float,
    has_watchdog_alert: bool, battery: int, abnormal_state: str,
) -> str:
    warnings = []
    if battery <= config.BATTERY_WARNING_THRESHOLD:
        warnings.append(f"🪫 Batterie {battery}%")
    if abnormal_state != "normal":
        warnings.append(f"🚨 Anomalie: {abnormal_state}")

    if count == 0:
        signal_text = "Keine Verbindung ⚠️"
    else:
        if avg_lqi >= 180:
            quality = "sehr gutes Signal"
        elif avg_lqi >= 120:
            quality = "gutes Signal"
        elif avg_lqi >= 60:
            quality = "ausreichendes Signal"
        else:
            quality = "schwaches Signal"
        gap_text = f", max. {max_gap_hours:.0f}h Funkstille" if max_gap_hours >= 1 else ""
        watchdog_text = " ⚠️" if has_watchdog_alert else ""
        signal_text = f"{quality} (Ø {avg_lqi:.0f} LQI, {count} Meldungen{gap_text}){watchdog_text}"

    line = f"📡 **{wish_name}** — {signal_text}"
    if warnings:
        line += " | " + ", ".join(warnings)
    return line
```

- [ ] **Schritt 4: Tests ausführen — müssen PASS sein**

```powershell
python -m unittest tests.adapters.test_daily_report -v
```

Erwartet: alle Tests PASS

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/adapters/daily_report.py tests/adapters/test_daily_report.py
git commit -m "feat: verbale Hilfsfunktionen für Tagesbericht"
```

### Schritt 2c: `generate_daily_report()` auf verbale Ausgabe umstellen

- [ ] **Schritt 6: `generate_daily_report()` in `daily_report.py` umschreiben**

Die Funktion `generate_daily_report()` vollständig ersetzen:

```python
def generate_daily_report(today_str: str) -> str:
    """Generiert den Text für den täglichen Statusbericht."""
    # 1. Guss-Statistiken der letzten 24h
    success_count, failed_count, total_volume = database.get_watering_stats_last_24h()

    # 2. Wetterdaten (Live-Abfrage)
    weather_result = None
    try:
        weather_result = weather.get_weather_data(config.LATITUDE, config.LONGITUDE)
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Wetterdaten für Statusbericht: {e}")
    if weather_result is not None:
        rain_last, rain_next, temp, weather_code, temp_min, temp_max, rain_prob = weather_result
        weather_desc = get_wmo_description(weather_code)
    else:
        rain_last, rain_next, temp, weather_code, temp_min, temp_max, rain_prob = 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0
        weather_desc = "Unbekannt"

    # 3. Gestrige Regenvorhersage für Abweichungsvergleich
    yesterday_weather = database.get_weather_around_hours_ago(24)
    yesterday_rain_next = yesterday_weather["rain_next_24h_mm"] if yesterday_weather else None

    # 4. System-Warnungen
    warnings = []
    if mqtt_client.HAS_PAHO:
        if not mqtt_client.is_broker_connected():
            warnings.append("🚨 **System-Dienst gestört:** MQTT-Broker ist offline")
        elif mqtt_client.get_bridge_status() != "online":
            warnings.append("🚨 **System-Dienst gestört:** Mittelweg-Dienst (Zigbee2MQTT) ist offline")

    # 5. Pro-Ventil-Status
    valves = database.get_all_valves()
    valve_lines = []
    for valve in valves:
        mqtt_name = valve["mqtt_name"]
        wish_name = valve["wish_name"]
        conn_stats = database.get_device_status_stats_last_24h(mqtt_name)
        flag_key = f"watchdog_alert_active_valve_{valve['id']}"
        has_watchdog_alert = database.get_metadata(flag_key) == "1"
        battery = valve.get("battery") or 100
        abnormal_state = valve.get("valve_abnormal_state") or "normal"

        valve_lines.append(_format_valve_line(
            wish_name=wish_name,
            mqtt_name=mqtt_name,
            count=conn_stats["count"],
            avg_lqi=conn_stats["avg_lqi"],
            max_gap_hours=conn_stats["max_gap_hours"],
            has_watchdog_alert=has_watchdog_alert,
            battery=battery,
            abnormal_state=abnormal_state,
        ))

    try:
        date_obj = datetime.strptime(today_str, "%Y-%m-%d")
        display_date = date_obj.strftime("%d.%m.%Y")
    except Exception:
        display_date = today_str

    watering_text = _format_watering_section(success_count, failed_count, total_volume)
    weather_text = _format_weather_section(
        temp=temp, temp_min=temp_min, temp_max=temp_max,
        weather_desc=weather_desc,
        rain_last=rain_last, rain_next=rain_next, rain_prob=rain_prob,
        yesterday_rain_next=yesterday_rain_next,
    )
    valve_text = "\n".join(valve_lines) if valve_lines else "Keine Ventile registriert."

    warning_text = ""
    if warnings:
        warning_text = "\n\n⚠️ **System-Warnungen:**\n" + "\n".join([f"- {w}" for w in warnings])

    return (
        f"📊 **Täglicher Statusbericht vom {display_date}**\n\n"
        f"{watering_text}\n"
        f"{weather_text}\n"
        f"{valve_text}"
        f"{warning_text}"
    )
```

- [ ] **Schritt 7: Alle Tests ausführen**

```powershell
python -m unittest discover tests -v
```

Erwartet: alle Tests PASS (keine Regression)

- [ ] **Schritt 8: Commit**

```bash
git add src/daemon/adapters/daily_report.py
git commit -m "feat: generate_daily_report nutzt verbale Beschreibungen"
```

---

## Task 3: `/report`-Handler vereinfachen

**Zweck:** Der `/report`-Handler in `telegram_ui.py` soll denselben Codepfad wie der automatische Report nutzen — Chart-Generierung und Text-Erstellung laufen identisch.

**Unterschied zur Broadcast-Variante:** `/report` sendet nur an den anfragenden `chat_id`, nicht an alle Nutzer. Deshalb wird `send_daily_report()` *nicht* direkt aufgerufen (der publiziert ein Event das an alle broadcastet). Stattdessen wird der Chart-Block aus `_on_daily_report` wiederverwendet.

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py`
- Test: `tests/ui/test_telegram_ui.py`

- [ ] **Schritt 1: Failing test schreiben**

In `tests/ui/test_telegram_ui.py` neue Testklasse hinzufügen:

```python
class TestReportCommand(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.scheduler")
    @patch("daemon.ui.telegram_ui.database")
    def test_report_requests_valve_status_before_report(self, mock_db, mock_scheduler, mock_tc):
        mock_scheduler.generate_daily_report.return_value = "Bericht"
        from daemon.adapters import mqtt_client as mc
        with patch.object(mc, "request_valve_status") as mock_req:
            _process_message({"chat": {"id": 1}, "text": "/report"})
            mock_req.assert_called_once()

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui.scheduler")
    @patch("daemon.ui.telegram_ui.database")
    def test_report_sends_text_to_requesting_chat_only(self, mock_db, mock_scheduler, mock_tc):
        mock_scheduler.generate_daily_report.return_value = "Bericht"
        _process_message({"chat": {"id": 42}, "text": "/report"})
        calls = [str(c) for c in mock_tc.send_message.call_args_list]
        # Alle send_message-Aufrufe müssen chat_id=42 haben
        for call in mock_tc.send_message.call_args_list:
            self.assertEqual(call.args[0], 42)
```

- [ ] **Schritt 2: Tests ausführen — müssen FAIL oder PASS sein**

```powershell
python -m unittest tests.ui.test_telegram_ui.TestReportCommand -v
```

Prüfe ob Tests bereits grün sind. Falls ja, weiter zu Schritt 5.

- [ ] **Schritt 3: `/report`-Handler in `telegram_ui.py` vereinfachen**

Den Block ab `elif text.startswith("/report")` (Zeile ~665) ersetzen:

```python
elif text.startswith("/report") or text.startswith("/statusbericht"):
    from ..adapters import mqtt_client as _mc, chart as _chart
    import time as _time

    _mc.request_valve_status()
    _time.sleep(5.0)

    image_bytes = _chart.generate_weather_chart()
    if image_bytes:
        telegram_client.send_photo(chat_id, image_bytes, caption="🌤 Wetterverlauf — nächste 24h")

    today_str = datetime.now().strftime("%Y-%m-%d")
    report_text = scheduler.generate_daily_report(today_str)
    telegram_client.send_message(chat_id, report_text, get_main_keyboard())
```

Änderungen gegenüber vorher:
- Sleep von 1,5s auf 5s erhöht (gleich wie `send_daily_report()`)
- Stündlicher Text-Fallback für Chart entfernt (war doppelte Logik — Chart sendet bei Fehler selbst kein Fallback, das ist Verantwortung des Chart-Adapters)

- [ ] **Schritt 4: Alle Tests ausführen**

```powershell
python -m unittest discover tests -v
```

Erwartet: alle Tests PASS

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/ui/telegram_ui.py tests/ui/test_telegram_ui.py
git commit -m "refactor: /report-Handler vereinfacht, Sleep auf 5s angeglichen"
```

---

## Abschluss-Check

- [ ] Vollständige Test-Suite grün:

```powershell
python -m unittest discover tests -v
```

- [ ] Coverage prüfen:

```powershell
.\scripts\run_coverage.ps1
```

Coverage darf nicht gesunken sein.
