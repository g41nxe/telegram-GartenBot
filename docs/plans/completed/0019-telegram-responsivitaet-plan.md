# Telegram-Responsivität & Auffindbarkeit — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Typing-Indikator vor Wartezeiten, event-basiertes Warten statt `time.sleep`, und natives Telegram-Befehlsmenü via `setMyCommands`.

**Architecture:** Reine UI/Transport-Änderungen. Zwei neue Methoden in `telegram_client.py` (`send_chat_action`, `set_my_commands`). `handle_status` und `/report` ersetzen `time.sleep` durch `threading.Event` mit Timeout, der auf `ValveStatusReported` wartet. `main.py` registriert Befehle einmalig beim Start.

**Tech Stack:** Python 3.11, stdlib only (`threading`, `urllib`), Telegram Bot API.

---

### Task 1: Transport-Methoden in `telegram_client.py`

**Files:**
- Modify: `src/daemon/ui/telegram_client.py`
- Modify: `tests/ui/test_telegram_client.py`

- [ ] **Schritt 1: Failing-Tests schreiben**

In `tests/ui/test_telegram_client.py` hinzufügen:

```python
from unittest.mock import patch, MagicMock
import urllib.request

class TestSendChatAction(unittest.TestCase):
    def test_send_chat_action_posts_correct_payload(self):
        """send_chat_action sendet typing-Action an die Telegram-API."""
        with patch("daemon.config.TELEGRAM_BOT_TOKEN", "test_token"), \
             patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp

            from daemon.ui import telegram_client
            telegram_client.send_chat_action(12345, "typing")

            call_args = mock_open.call_args[0][0]
            import json
            payload = json.loads(call_args.data.decode())
            self.assertEqual(payload["chat_id"], 12345)
            self.assertEqual(payload["action"], "typing")
            self.assertIn("sendChatAction", call_args.full_url)

    def test_set_my_commands_posts_commands_list(self):
        """set_my_commands sendet die Befehlsliste an Telegram."""
        with patch("daemon.config.TELEGRAM_BOT_TOKEN", "test_token"), \
             patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp

            from daemon.ui import telegram_client
            commands = [{"command": "status", "description": "Systemstatus anzeigen"}]
            telegram_client.set_my_commands(commands)

            call_args = mock_open.call_args[0][0]
            import json
            payload = json.loads(call_args.data.decode())
            self.assertEqual(payload["commands"], commands)
            self.assertIn("setMyCommands", call_args.full_url)

    def test_send_chat_action_skips_without_token(self):
        """send_chat_action tut nichts wenn kein Token gesetzt."""
        with patch("daemon.config.TELEGRAM_BOT_TOKEN", ""), \
             patch("urllib.request.urlopen") as mock_open:
            from daemon.ui import telegram_client
            telegram_client.send_chat_action(12345, "typing")
            mock_open.assert_not_called()
```

- [ ] **Schritt 2: Tests ausführen — müssen FAIL**

```
python -m unittest tests.ui.test_telegram_client -v
```

Erwartet: `AttributeError: module 'telegram_client' has no attribute 'send_chat_action'`

- [ ] **Schritt 3: Implementation in `telegram_client.py`**

Nach der `answer_callback_query`-Funktion einfügen:

```python
def send_chat_action(chat_id: int, action: str) -> None:
    """Sendet eine Chat-Aktion (z.B. 'typing') an Telegram."""
    if not config.TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendChatAction"
    payload = {"chat_id": chat_id, "action": action}
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception as e:
        logger.debug(f"send_chat_action fehlgeschlagen: {e}")


def set_my_commands(commands: list) -> None:
    """Registriert die Bot-Befehle im Telegram-Befehlsmenü."""
    if not config.TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/setMyCommands"
    payload = {"commands": commands}
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
        logger.info("Telegram-Befehlsmenü registriert.")
    except Exception as e:
        logger.error(f"set_my_commands fehlgeschlagen: {e}")
```

- [ ] **Schritt 4: Tests grün**

```
python -m unittest tests.ui.test_telegram_client -v
```

Erwartet: alle Tests grün.

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/ui/telegram_client.py tests/ui/test_telegram_client.py
git commit -m "feat: send_chat_action und set_my_commands in telegram_client"
```

---

### Task 2: `handle_status` — Typing-Indikator + event-basiertes Warten

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py` (Funktion `handle_status`, ca. Zeile 596)
- Modify: `tests/ui/test_telegram_ui.py`

Hintergrund: `handle_status` ruft `mqtt_client.request_valve_status()` auf und wartet dann blind 1,5 s mit `time.sleep`. Stattdessen: Typing-Indikator senden, auf `ValveStatusReported`-Event warten (max. 3 s), dann fortfahren.

- [ ] **Schritt 1: Failing-Test schreiben**

In `tests/ui/test_telegram_ui.py` in die passende Klasse einfügen:

```python
def test_handle_status_sendet_typing_indikator(self):
    """handle_status sendet typing-Action bevor es auf Ventildaten wartet."""
    with patch("daemon.ui.telegram_client.send_chat_action") as mock_action, \
         patch("daemon.ui.telegram_client.send_message"), \
         patch("daemon.adapters.mqtt_client.request_valve_status"), \
         patch("daemon.adapters.database.get_all_valves", return_value=[]), \
         patch("daemon.adapters.database.get_all_cameras", return_value=[]), \
         patch("daemon.adapters.database.get_last_weather", return_value=None), \
         patch("daemon.adapters.database.get_schedules", return_value=[]):
        from daemon.ui.telegram_ui import handle_status
        handle_status(12345)
        mock_action.assert_called_once_with(12345, "typing")

def test_handle_status_wartet_nicht_voll_wenn_event_frueh_eintrifft(self):
    """handle_status wartet nicht die volle Timeout-Zeit wenn Ventil früh antwortet."""
    import time
    from daemon.core.valve_events import ValveStatusReported
    from daemon.adapters.mqtt_client import _global_bus

    def fire_event_quickly(*args, **kwargs):
        import threading
        def _fire():
            import time as _t; _t.sleep(0.05)
            _global_bus.publish(ValveStatusReported(
                mqtt_name="garden_valve", status="OFF",
                battery=80, battery_low=False, flow=0.0, volume=0.0
            ))
        threading.Thread(target=_fire, daemon=True).start()

    with patch("daemon.adapters.mqtt_client.request_valve_status", side_effect=fire_event_quickly), \
         patch("daemon.ui.telegram_client.send_chat_action"), \
         patch("daemon.ui.telegram_client.send_message"), \
         patch("daemon.adapters.database.get_all_valves", return_value=[]), \
         patch("daemon.adapters.database.get_all_cameras", return_value=[]), \
         patch("daemon.adapters.database.get_last_weather", return_value=None), \
         patch("daemon.adapters.database.get_schedules", return_value=[]):
        from daemon.ui.telegram_ui import handle_status
        start = time.monotonic()
        handle_status(12345)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.0, "handle_status wartete länger als 1 s obwohl Event sofort kam")
```

- [ ] **Schritt 2: Tests ausführen — müssen FAIL**

```
python -m unittest tests.ui.test_telegram_ui.TestTelegramUI.test_handle_status_sendet_typing_indikator -v
```

- [ ] **Schritt 3: `handle_status` umbauen**

```python
def handle_status(chat_id: int):
    import threading
    from ..adapters import mqtt_client
    from ..core.valve_events import ValveStatusReported
    from . import telegram_client as _tc

    _tc.send_chat_action(chat_id, "typing")

    _valve_event = threading.Event()

    def _on_valve_response(event):
        _valve_event.set()

    _global_bus.subscribe(ValveStatusReported, _on_valve_response)
    try:
        mqtt_client.request_valve_status()
        _valve_event.wait(timeout=3.0)
    finally:
        _global_bus.unsubscribe(ValveStatusReported, _on_valve_response)

    # Ab hier: bestehende Logik unverändert (broker_connected, bridge_online, ...)
    broker_connected = mqtt_client.is_broker_connected()
    # ... (Rest der Funktion unverändert)
```

- [ ] **Schritt 4: Tests grün**

```
python -m unittest tests.ui.test_telegram_ui -v
```

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/ui/telegram_ui.py tests/ui/test_telegram_ui.py
git commit -m "feat: handle_status — Typing-Indikator und event-basiertes Warten (0019)"
```

---

### Task 3: `/report`-Handler — Typing-Indikator + event-basiertes Warten

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py` (Report-Handler, ca. Zeile 1037)
- Modify: `tests/ui/test_telegram_ui.py`

- [ ] **Schritt 1: Failing-Test**

```python
def test_report_handler_sendet_typing_indikator(self):
    """Der /report-Handler sendet typing bevor er auf Ventildaten wartet."""
    with patch("daemon.ui.telegram_client.send_chat_action") as mock_action, \
         patch("daemon.ui.telegram_client.send_message"), \
         patch("daemon.ui.telegram_client.send_photo"), \
         patch("daemon.adapters.mqtt_client.request_valve_status"), \
         patch("daemon.adapters.database.get_all_valves", return_value=[]), \
         patch("daemon.adapters.database.get_watering_history", return_value=[]), \
         patch("daemon.adapters.database.get_last_weather", return_value=None), \
         patch("daemon.adapters.chart.generate_weather_chart", return_value=None):
        from daemon.ui.telegram_ui import on_telegram_update
        msg = {"chat": {"id": 12345}, "from": {"id": 12345}, "text": "/report", "message_id": 1}
        on_telegram_update(msg, None)
        self.assertTrue(
            any(call[0] == (12345, "typing") for call in mock_action.call_args_list),
            "send_chat_action('typing') wurde nicht aufgerufen"
        )
```

- [ ] **Schritt 2: Test ausführen — muss FAIL**

```
python -m unittest tests.ui.test_telegram_ui.TestTelegramUI.test_report_handler_sendet_typing_indikator -v
```

- [ ] **Schritt 3: Report-Handler umbauen**

Den Block in `on_telegram_update` bei `elif text.startswith("/report")` ersetzen:

```python
elif text.startswith("/report") or text.startswith("/statusbericht"):
    import threading
    from ..adapters import mqtt_client as _mc, chart as _chart
    from ..core.valve_events import ValveStatusReported

    telegram_client.send_chat_action(chat_id, "typing")

    _valve_event = threading.Event()
    def _on_valve_resp(ev):
        _valve_event.set()
    _global_bus.subscribe(ValveStatusReported, _on_valve_resp)
    try:
        _mc.request_valve_status()
        _valve_event.wait(timeout=5.0)
    finally:
        _global_bus.unsubscribe(ValveStatusReported, _on_valve_resp)

    today_str = datetime.now().strftime("%Y-%m-%d")
    report_text = _generate_daily_report(today_str)
    chart_result = _chart.generate_weather_chart()
    if chart_result:
        image_bytes, caption = chart_result
        telegram_client.send_photo(chat_id, image_bytes, caption=caption)
    telegram_client.send_message(chat_id, report_text, get_main_keyboard())
```

- [ ] **Schritt 4: Tests grün**

```
python -m unittest tests.ui.test_telegram_ui -v
```

- [ ] **Schritt 5: Gesamte Testsuite**

```
python -m unittest discover tests -v
```

- [ ] **Schritt 6: Commit**

```bash
git add src/daemon/ui/telegram_ui.py tests/ui/test_telegram_ui.py
git commit -m "feat: /report — Typing-Indikator und event-basiertes Warten (0019)"
```

---

### Task 4: Befehlsmenü via `setMyCommands` in `main.py`

**Files:**
- Modify: `src/daemon/main.py`
- Modify: `tests/ui/test_telegram_ui.py` (Wiring-Smoke-Test)

- [ ] **Schritt 1: Failing-Test**

```python
def test_set_my_commands_wird_beim_start_aufgerufen(self):
    """set_my_commands wird beim Bot-Start mit einer nicht-leeren Befehlsliste aufgerufen."""
    with patch("daemon.ui.telegram_client.set_my_commands") as mock_cmds, \
         patch("daemon.ui.telegram_client.start_polling"), \
         patch("daemon.adapters.mqtt_client.initialize"):
        from daemon.main import register_telegram_commands
        register_telegram_commands()
        mock_cmds.assert_called_once()
        commands = mock_cmds.call_args[0][0]
        self.assertIsInstance(commands, list)
        self.assertGreater(len(commands), 3)
        cmd_names = [c["command"] for c in commands]
        self.assertIn("status", cmd_names)
        self.assertIn("zeitplan", cmd_names)
        self.assertIn("stop", cmd_names)
```

- [ ] **Schritt 2: Test ausführen — muss FAIL**

```
python -m unittest tests.ui.test_telegram_ui.TestTelegramUI.test_set_my_commands_wird_beim_start_aufgerufen -v
```

- [ ] **Schritt 3: `register_telegram_commands` in `main.py` anlegen**

In `src/daemon/main.py` eine neue Funktion hinzufügen und im Start-Block aufrufen:

```python
def register_telegram_commands():
    """Registriert das native Telegram-Befehlsmenü (sichtbar im '/' Eingabefeld)."""
    from .ui import telegram_client
    commands = [
        {"command": "status",        "description": "Systemstatus anzeigen"},
        {"command": "zeitplan",      "description": "Zeitpläne verwalten"},
        {"command": "report",        "description": "Tagesbericht anzeigen"},
        {"command": "stop",          "description": "Bewässerung sofort stoppen"},
        {"command": "setup",         "description": "Ventil koppeln"},
        {"command": "photo",         "description": "Aktuelles Kamerabild"},
        {"command": "camera_setup",  "description": "Kamera koppeln"},
        {"command": "camera_clear",  "description": "Bild-Historie löschen"},
        {"command": "update",        "description": "Software-Update"},
    ]
    telegram_client.set_my_commands(commands)
```

Im Start-Block von `main.py` nach dem Token-Check:

```python
register_telegram_commands()
```

- [ ] **Schritt 4: Tests grün**

```
python -m unittest discover tests -v
```

- [ ] **Schritt 5: Commit**

```bash
git add src/daemon/main.py tests/ui/test_telegram_ui.py
git commit -m "feat: setMyCommands beim Daemon-Start — natives Telegram-Befehlsmenü (0019)"
```

---

### Task 5: Abschluss

- [ ] **Gesamte Testsuite**

```
python -m unittest discover tests -v
```

Alle Tests grün.

- [ ] **Feature-Doc verschieben**

```bash
git mv docs/features/0019-telegram-responsivitaet-und-auffindbarkeit.md docs/features/completed/
git mv docs/plans/0019-telegram-responsivitaet-plan.md docs/plans/completed/
git commit -m "docs: Feature 0019 abgeschlossen — Telegram-Responsivität & Auffindbarkeit"
```
