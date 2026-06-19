# Kamera-Akkustand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den Akkustand der Garten-Kamera im `/status` anzeigen, in die Garten-Ampel einbeziehen und im Tagesbericht warnen — übertragen via `X-Battery-Level` HTTP-Header beim Upload.

**Architecture:** Die Kamera hängt bei jedem `/upload`-POST den Header `X-Battery-Level: <0–100>` an. `camera_receiver.py` liest diesen Header und speichert ihn via `database.update_camera_on_upload()` (umbenannt aus `update_camera_last_seen`). Die bestehende `_get_battery_description()`-Funktion und der `BATTERY_WARNING_THRESHOLD` werden unverändert wiederverwendet.

**Tech Stack:** Python 3.11, SQLite (ALTER TABLE Migration), stdlib HTTPServer, unittest + pytest.

---

### Task 1: DB-Migration + `update_camera_on_upload`

**Files:**
- Modify: `src/daemon/adapters/database.py` (Funktion `update_camera_last_seen` + `init_db`)
- Test: `tests/adapters/test_camera_receiver.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/adapters/test_camera_receiver.py` am Ende ergänzen:

```python
def test_upload_speichert_akkustand(running_server):
    """X-Battery-Level Header wird beim Upload in der DB gespeichert."""
    database.add_camera("BA:BB:CC:DD:EE:FF", "AkkuCam")
    url = f"http://127.0.0.1:{running_server}/upload"
    payload = b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00'
    req = urllib.request.Request(
        url,
        headers={"X-Camera-MAC": "BA:BB:CC:DD:EE:FF", "X-Battery-Level": "78"},
        data=payload,
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200

    cam = database.get_camera("BA:BB:CC:DD:EE:FF")
    assert cam["battery"] == 78


def test_upload_ohne_akkuheader_behaelt_wert(running_server):
    """Fehlt X-Battery-Level, bleibt der gespeicherte Wert unverändert."""
    database.add_camera("CA:BB:CC:DD:EE:FF", "NoBatCam")
    # Direkter DB-Aufruf um Initialwert zu setzen
    database.update_camera_on_upload("CA:BB:CC:DD:EE:FF", battery=55)

    url = f"http://127.0.0.1:{running_server}/upload"
    payload = b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00'
    req = urllib.request.Request(
        url,
        headers={"X-Camera-MAC": "CA:BB:CC:DD:EE:FF"},
        data=payload,
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200

    cam = database.get_camera("CA:BB:CC:DD:EE:FF")
    assert cam["battery"] == 55
```

- [ ] **Step 2: Test ausführen — muss fehlschlagen**

```powershell
python -m pytest tests/adapters/test_camera_receiver.py::test_upload_speichert_akkustand -v
```
Erwartet: `FAILED` — `KeyError: 'battery'` oder `AttributeError`

- [ ] **Step 3: DB-Migration in `init_db()` ergänzen**

In `src/daemon/adapters/database.py`, nach der letzten `try: cursor.execute("SELECT ... LIMIT 1")` Migration, folgendes einfügen:

```python
try:
    cursor.execute("SELECT battery FROM cameras LIMIT 1")
except sqlite3.OperationalError:
    logger.info("Migriere Datenbank: Füge battery Spalte zu cameras hinzu...")
    cursor.execute("ALTER TABLE cameras ADD COLUMN battery INTEGER")
```

- [ ] **Step 4: `update_camera_last_seen` umbenennen und erweitern**

In `src/daemon/adapters/database.py` die Funktion ersetzen:

```python
def update_camera_on_upload(mac_address: str, battery: int | None = None):
    """Aktualisiert last_seen und optional den Akkustand nach einem Bild-Upload."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        from datetime import datetime
        timestamp = datetime.now().isoformat()
        if battery is not None:
            cursor.execute(
                "UPDATE cameras SET last_seen = ?, battery = ? WHERE mac_address = ?",
                (timestamp, battery, mac_address)
            )
        else:
            cursor.execute(
                "UPDATE cameras SET last_seen = ? WHERE mac_address = ?",
                (timestamp, mac_address)
            )
        conn.commit()
    except Exception as e:
        logger.error(f"Fehler beim Aktualisieren des Status für Kamera '{mac_address}': {e}")
    finally:
        conn.close()
```

- [ ] **Step 5: Tests ausführen — müssen grün sein**

```powershell
python -m pytest tests/adapters/test_camera_receiver.py -v
```
Erwartet: alle Tests grün.

- [ ] **Step 6: Commit**

```powershell
git add src/daemon/adapters/database.py tests/adapters/test_camera_receiver.py
git commit -m "feat: cameras.battery Spalte + update_camera_on_upload"
```

---

### Task 2: Camera Receiver — Header auslesen

**Files:**
- Modify: `src/daemon/adapters/camera_receiver.py` (Funktion `handle_upload`)

- [ ] **Step 1: `handle_upload` anpassen**

In `src/daemon/adapters/camera_receiver.py`, in `handle_upload()` den Aufruf von `update_camera_last_seen` ersetzen:

```python
# Alt:
database.update_camera_last_seen(mac)

# Neu:
battery_header = self.headers.get("X-Battery-Level")
battery = None
if battery_header is not None:
    try:
        battery = int(battery_header)
        if not (0 <= battery <= 100):
            battery = None
    except ValueError:
        battery = None
database.update_camera_on_upload(mac, battery=battery)
```

- [ ] **Step 2: Vollständigen Test-Run ausführen**

```powershell
python -m unittest discover tests
```
Erwartet: alle 331 Tests grün (skipped=4).

- [ ] **Step 3: Commit**

```powershell
git add src/daemon/adapters/camera_receiver.py
git commit -m "feat: X-Battery-Level Header beim Upload auslesen und speichern"
```

---

### Task 3: `/status` — Akkustand anzeigen + Garten-Ampel

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py` (Kamera-Abschnitt in `handle_status`, `_garden_ampel_level`)
- Test: `tests/ui/test_telegram_ui.py`

- [ ] **Step 1: Failing tests schreiben**

In `tests/ui/test_telegram_ui.py` vor `if __name__ == "__main__":` einfügen:

```python
class TestKameraAkkustandImStatus(unittest.TestCase):
    """Testet die Akkustand-Anzeige der Kamera im /status."""

    def _status_call(self, mock_db, mock_ctrl, cameras):
        from daemon.adapters import mqtt_client as mc
        mock_db.get_last_weather.return_value = None
        mock_db.get_all_valves.return_value = []
        mock_db.get_all_cameras.return_value = cameras
        mock_db.get_recent_history.return_value = []
        mock_ctrl.get_active_cycle.return_value = None
        with patch.object(mc, "HAS_PAHO", False), \
             patch.object(mc, "request_valve_status"), \
             patch.object(mc, "is_broker_connected", return_value=True), \
             patch.object(mc, "get_bridge_status", return_value="online"):
            from daemon.ui.telegram_ui import handle_status
            handle_status(100)

    def _make_cam(self, battery=None, last_seen=None):
        from datetime import datetime, timezone
        ts = last_seen or datetime.now(timezone.utc).isoformat()
        return {
            "wish_name": "Hochbeet",
            "last_seen": ts,
            "sleep_duration_seconds": 900,
            "battery": battery,
        }

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_kamera_akkustand_wird_angezeigt(self, mock_client, mock_db, mock_ctrl):
        """Kamera-Akkustand erscheint im Status wenn vorhanden."""
        self._status_call(mock_db, mock_ctrl, [self._make_cam(battery=78)])
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("78", text)

    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_kamera_kein_akkustand_kein_crash(self, mock_client, mock_db, mock_ctrl):
        """Kamera ohne Akkustand (None) zeigt kein Batterie-Label."""
        self._status_call(mock_db, mock_ctrl, [self._make_cam(battery=None)])
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("Hochbeet", text)

    @patch("daemon.config.get_setting", return_value=20)
    @patch("daemon.ui.telegram_ui._watering_ctrl")
    @patch("daemon.ui.telegram_ui.database")
    @patch("daemon.ui.telegram_ui.telegram_client")
    def test_kamera_niedrig_akkustand_kippt_ampel(self, mock_client, mock_db, mock_ctrl, mock_get):
        """Kamera mit Akku <= Schwellenwert kippt Garten-Ampel auf 🟡."""
        self._status_call(mock_db, mock_ctrl, [self._make_cam(battery=10)])
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("🟡", text)
```

- [ ] **Step 2: Tests ausführen — müssen fehlschlagen**

```powershell
python -m unittest tests.ui.test_telegram_ui.TestKameraAkkustandImStatus -v
```
Erwartet: `FAILED`

- [ ] **Step 3: Kamera-Akkustand im Status-Block anzeigen**

In `src/daemon/ui/telegram_ui.py`, die Zeile `camera_sections.append(f"{wish_name} · {cam_status}")` ersetzen:

```python
battery = cam.get("battery")
battery_label = f" · {_get_battery_description(battery)}" if battery is not None else ""
camera_sections.append(f"{wish_name} · {cam_status}{battery_label}")
```

- [ ] **Step 4: Kameras in `_garden_ampel_level` einbeziehen**

In `src/daemon/ui/telegram_ui.py`, am Ende von `_garden_ampel_level`, vor `return worst`:

```python
# Kamera-Akkustände prüfen
for cam in database.get_all_cameras():
    cam_battery = cam.get("battery")
    if cam_battery is not None and int(cam_battery) <= threshold:
        worst = "yellow"
```

Dazu den Funktions-Signature anpassen — `database` ist bereits im Modulscope importiert, kein weiterer Import nötig.

- [ ] **Step 5: Tests ausführen — müssen grün sein**

```powershell
python -m unittest discover tests
```
Erwartet: alle Tests grün.

- [ ] **Step 6: Commit**

```powershell
git add src/daemon/ui/telegram_ui.py tests/ui/test_telegram_ui.py
git commit -m "feat: Kamera-Akkustand im /status + Garten-Ampel"
```

---

### Task 4: Tagesbericht — Kamera-Batteriewarnung

**Files:**
- Modify: `src/daemon/adapters/daily_report.py`
- Test: `tests/adapters/test_daily_report.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/adapters/test_daily_report.py` ergänzen:

```python
class TestKameraWarnungen(unittest.TestCase):

    def test_niedrige_kamera_batterie_erzeugt_warnung(self):
        """Kamera mit Akku <= Schwellenwert erscheint in den Warnungen."""
        with patch("daemon.config.get_setting", return_value=20):
            result = dr._camera_warnings({"wish_name": "Hochbeet", "battery": 10})
        self.assertEqual(len(result), 1)
        self.assertIn("Hochbeet", result[0])
        self.assertIn("10%", result[0])

    def test_volle_kamera_batterie_keine_warnung(self):
        """Kamera mit vollem Akku erzeugt keine Warnung."""
        with patch("daemon.config.get_setting", return_value=20):
            result = dr._camera_warnings({"wish_name": "Hochbeet", "battery": 80})
        self.assertEqual(result, [])

    def test_kamera_ohne_akkustand_keine_warnung(self):
        """Kamera ohne bekannten Akkustand (None) erzeugt keine Warnung."""
        with patch("daemon.config.get_setting", return_value=20):
            result = dr._camera_warnings({"wish_name": "Hochbeet", "battery": None})
        self.assertEqual(result, [])
```

- [ ] **Step 2: Tests ausführen — müssen fehlschlagen**

```powershell
python -m unittest tests.adapters.test_daily_report.TestKameraWarnungen -v
```
Erwartet: `FAILED` — `AttributeError: module has no attribute '_camera_warnings'`

- [ ] **Step 3: `_camera_warnings` in `daily_report.py` implementieren**

In `src/daemon/adapters/daily_report.py` nach `_valve_warnings` einfügen:

```python
def _camera_warnings(camera: dict) -> list[str]:
    """Gibt Warnungen für eine einzelne Kamera zurück (aktuell: Akkustand)."""
    warnings = []
    battery = camera.get("battery")
    if battery is None:
        return warnings
    wish_name = camera["wish_name"]
    _bat_threshold = config.get_setting("BATTERY_WARNING_THRESHOLD", 20)
    if int(battery) <= _bat_threshold:
        warnings.append(
            f"🪫 *Niedriger Akkustand ({wish_name}):* {battery}%"
            f" (Grenzwert: {_bat_threshold}%)"
        )
    return warnings
```

- [ ] **Step 4: `_camera_warnings` in den Tagesbericht einbinden**

In `src/daemon/adapters/daily_report.py` die Funktion `generate_daily_report` (oder wo die `_valve_warnings` gesammelt werden) suchen und Kamera-Warnungen ergänzen.

Zunächst suchen wo Ventil-Warnungen gesammelt werden:

```python
# Bestehend — ungefähr so:
all_warnings = []
for valve in valves:
    all_warnings.extend(_valve_warnings(valve))

# Ergänzen:
cameras = database.get_all_cameras()
for cam in cameras:
    all_warnings.extend(_camera_warnings(cam))
```

- [ ] **Step 5: Alle Tests ausführen**

```powershell
python -m unittest discover tests
```
Erwartet: alle Tests grün.

- [ ] **Step 6: Commit**

```powershell
git add src/daemon/adapters/daily_report.py tests/adapters/test_daily_report.py
git commit -m "feat: Kamera-Batteriewarnung im Tagesbericht"
```

---

### Task 5: Referenz-Dokument aktualisieren

**Files:**
- Modify: `docs/reference/telegram-nachrichten.html`
- Modify: `docs/features/0024-kamera-akkustand.md` → nach `docs/features/completed/`
- Modify: `docs/plans/0024-kamera-akkustand-plan.md` → nach `docs/plans/completed/`

- [ ] **Step 1: `/status`-Kamera-Zeile aktualisieren**

In `docs/reference/telegram-nachrichten.html` die Kamera-Statuszeile um Akkustand ergänzen.

Vorher:
```
Hochbeet · 🟢 14:30 Uhr
```
Nachher:
```
Hochbeet · 🟢 14:30 Uhr · 🔋 Voll (78%)
```
Variante ohne Akkustand (battery=None): unverändert.

- [ ] **Step 2: Tagesbericht-Sektion aktualisieren**

Kamera-Batteriewarnung analog zu Ventil-Batteriewarnung ergänzen:
```
🪫 *Niedriger Akkustand (Hochbeet):* 12% (Grenzwert: 20%)
```

- [ ] **Step 3: Feature-Docs verschieben**

```powershell
Move-Item "docs/features/0024-kamera-akkustand.md" "docs/features/completed/"
Move-Item "docs/plans/0024-kamera-akkustand-plan.md" "docs/plans/completed/"
```

- [ ] **Step 4: Abschluss-Commit**

```powershell
git add docs/
git commit -m "docs: Feature 0024 Referenz aktualisiert + abgeschlossen"
```
