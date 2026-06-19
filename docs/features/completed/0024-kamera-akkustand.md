# Feature: Kamera-Akkustand anzeigen

## Problemstellung

Die Garten-Kamera (m5-GartenKamera, ESP32) wird von einem eingebauten LiPo-Akku versorgt. Der Bewässerungs-Daemon hat heute keinen Zugriff auf den Ladestand dieses Akkus — er erscheint weder im `/status` noch im Tagesbericht. Ein leerer Kamera-Akku bleibt unbemerkt, bis keine Bilder mehr eintreffen.

## Ziel

Der Akkustand der Kamera wird im `/status` angezeigt, beeinflusst die Garten-Ampel und erzeugt im Tagesbericht eine Warnung — analog zur bestehenden Ventil-Batterie-Logik.

## Entscheidungen

- **Übertragungsweg:** Die Firmware hängt bei jedem `/upload`-Request den Header `X-Battery-Level: <0–100>` an. Kein neuer Endpoint.
- **Werteformat:** Integer-Prozent (0–100). Die Umrechnung von Rohspannung auf Prozent erfolgt in der Firmware.
- **Fehlender Header:** Ist der Header nicht vorhanden, bleibt der gespeicherte Wert unverändert (kein Reset auf NULL).

## Änderungen

### Firmware (m5-GartenKamera)
- Akkuspannung messen und auf 0–100 % umrechnen
- Header `X-Battery-Level: <wert>` bei jedem POST `/upload` mitsenden

### `src/daemon/adapters/database.py`
- `cameras`-Tabelle: neue Spalte `battery INTEGER` (Migration via `ALTER TABLE … ADD COLUMN`, mit `try/except OperationalError`)
- `update_camera_last_seen(mac)` → umbenennen oder erweitern zu `update_camera_on_upload(mac, battery=None)`, das `battery` nur aktualisiert wenn nicht `None`

### `src/daemon/adapters/camera_receiver.py`
- `handle_upload()`: Header `X-Battery-Level` auslesen, als Integer parsen, an `update_camera_on_upload()` weitergeben

### `src/daemon/ui/telegram_ui.py`
- `handle_status()` / Kamera-Abschnitt: `_get_battery_description(cam.get("battery"))` an den Kamera-Statustext anhängen
- `_garden_ampel_level()`: Kameras mit bekanntem Akkustand in die Ampel-Berechnung einbeziehen (gleicher `BATTERY_WARNING_THRESHOLD`)

### `src/daemon/adapters/daily_report.py`
- Kamera-Batteriewarnungen analog zu Ventil-Batteriewarnungen erzeugen

### `docs/reference/telegram-nachrichten.html`
- `/status`-Kamera-Zeile aktualisieren (Akkustand-Darstellung)
- Tagesbericht-Sektion: Kamera-Batteriewarnung ergänzen
