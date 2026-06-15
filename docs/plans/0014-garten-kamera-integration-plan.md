# Implementation Plan: Garten-Kamera-Integration (M5Stack Timer Camera F)

Dieser Plan beschreibt den Entwurf und die zu ändernden Dateien für die Integration der WLAN-basierten Garten-Kamera (M5Stack Timer Camera F) in das GartenBot-System.

## Design Rules & Decisions

- **Indirekte Verbindung (Sicherheit):** Garten-Kameras laden Bilder per HTTP POST auf den Pi hoch. Der Pi speichert sie und leitet sie per Telegram weiter. Das Bot-Token verbleibt sicher auf dem Pi.
- **Akkuschonung (Deep Sleep & Statische IP):** Die Kamera schläft fast immer (2 µA). Um die Online-Zeit zu verringern, bypassen wir DHCP und weisen der Kamera im C++ Code eine statische IP-Adresse zu.
- **Dynamische Parameter (Hybrid-Config):** WLAN-Zugangsdaten sind statisch einkompiliert. Vor dem Foto holt sich die Kamera über `GET /config` unter Angabe ihrer MAC-Adresse ihre aktuellen Parameter (Schlafintervall, Auflösung, Qualität) vom Pi.
- **WLAN-Fehlertoleranz (Exponential Backoff):** Schlägt die Verbindung fehl, wird ein Fehlerzähler im RTC-RAM (`RTC_DATA_ATTR`) erhöht und stufenweise seltener aufgewacht (1, 2, 4, 8 Min) bis zum maximal regulären Intervall. Bei Erfolg wird der Zähler zurückgesetzt.
- **Kamera-Kopplung (Pairing):** Ein 90-Sekunden-Fenster wird über den Telegram-Befehl `/camera_setup` gestartet, in dem die Kamera ihre MAC-Adresse per `POST /register` registrieren kann und einem Wunschnamen zugeordnet wird.
- **Watchdog-Integration:** Der Inaktivitäts-Watchdog des Daemons überwacht alle registrierten Kameras. Das Timeout beträgt das **3-Fache des Schlafintervalls** (mindestens jedoch 1 Stunde).
- **Intelligente Bereinigung:** Ein täglicher Scheduler-Job löscht Bilder, die älter als 30 Tage sind, schließt jedoch das jeweils erste Bild eines jeden Kalendertages aus, um Zeitraffer-Aufnahmen zu ermöglichen.
- **Telegram-UI:** Befehl `/photo` / `/camera`. Ist 1 Kamera gekoppelt, wird das Bild direkt gesendet. Sind mehrere gekoppelt, wird ein Inline-Keyboard zur Auswahl eingeblendet. Die Buttons `"📷 Foto anzeigen"` und `"📷 Kamera koppeln"` werden dem Hauptmenü hinzugefügt.

---

## Proposed Changes

### 1. Konfiguration

#### [MODIFY] [.env.template](file:///c:/Users/g41nx/Repositories/garden/.env.template) & [.env](file:///c:/Users/g41nx/Repositories/garden/.env)
Hinzufügen der neuen Parameter für die Kamera-Anbindung:
```env
# --- Garten-Kamera-Konfiguration ---
CAMERA_RECEIVER_PORT=8080
CAMERA_IMAGE_DIR=data/camera
CAMERA_CLEANUP_DAYS=30
```

#### [MODIFY] [config.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/config.py)
- Importieren und Validieren von `CAMERA_RECEIVER_PORT` (Standard: 8080), `CAMERA_IMAGE_DIR` (Standard: `"data/camera"`) und `CAMERA_CLEANUP_DAYS` (Standard: 30).

---

### 2. Datenhaltung (Datenbank)

#### [MODIFY] [database.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/adapters/database.py)
- **Schema-Erweiterung:** In `init_db()` die Tabelle `cameras` erstellen:
  - `mac_address TEXT PRIMARY KEY`
  - `wish_name TEXT UNIQUE NOT NULL`
  - `last_seen TEXT`
  - `sleep_duration_seconds INTEGER DEFAULT 900` -- Standard 15 Minuten
  - `resolution TEXT DEFAULT 'XGA'`
  - `quality INTEGER DEFAULT 10`
- **CRUD-Funktionen:**
  - `add_camera(mac_address: str, wish_name: str) -> bool`
  - `get_camera(mac_address: str) -> dict | None`
  - `get_all_cameras() -> list[dict]`
  - `update_camera_last_seen(mac_address: str)`
  - `update_camera_settings(mac_address: str, sleep_seconds: int, resolution: str, quality: int) -> bool`
  - `delete_camera(mac_address: str) -> bool`

---

### 3. Events & Kopplungs-Logik

#### [NEW] [camera_events.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/core/camera_events.py)
- Domain-Event `CameraImageReceived(Event)` mit den Feldern `mac_address`, `wish_name`, `timestamp` und `filepath`.

#### [NEW] [camera_pairing.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/adapters/camera_pairing.py)
- Verwaltet das 90-Sekunden-Koppelzeitfenster und merkt sich den temporären Wunschnamen sowie die Telegram `notify_fn` zur Benachrichtigung des Benutzers über den Fortschritt.
- Funktionen:
  - `is_pairing_active() -> bool`
  - `start_pairing(chat_id: int, notify_fn, wish_name: str) -> bool`
  - `try_pair_camera(mac_address: str) -> bool` (wird vom HTTP-Empfänger bei `POST /register` aufgerufen)

---

### 4. HTTP-Empfänger (driving adapter)

#### [NEW] [camera_receiver.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/adapters/camera_receiver.py)
- Startet bei Initialisierung einen Thread mit einem `HTTPServer` (aus der Python-Standardbibliothek) auf dem konfigurierten `CAMERA_RECEIVER_PORT`.
- **Endpunkte:**
  - `POST /register`: Empfängt `mac` im Request-Body. Versucht die Kamera über `camera_pairing.try_pair_camera(mac)` zu koppeln. Gibt `200 OK` bei Erfolg zurück, andernfalls `403 Forbidden`.
  - `GET /config`: Liest die MAC-Adresse aus dem Header `X-Camera-MAC`. Prüft in der DB, ob die Kamera registriert ist. Falls ja, sendet sie die Einstellungen (Schlafintervall, Auflösung, Qualität) als JSON zurück.
  - `POST /upload`: Liest die MAC-Adresse aus `X-Camera-MAC`. Verifiziert die Registrierung. Liest den Body als Binärstrom und speichert das Bild unter `data/camera/<wish_name>/photo_<timestamp>.jpg` ab. Kopiert/Verlinkt es nach `latest.jpg` im selben Verzeichnis. Feuert das Event `CameraImageReceived`.

#### [MODIFY] [main.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/main.py)
- Importiert und startet den `camera_receiver` im Hintergrund-Thread beim Systemstart.

---

### 5. Inaktivitäts-Watchdog

#### [MODIFY] [watchdog.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/adapters/watchdog.py)
- Abonniert das Event `CameraImageReceived`, um die lokale Variable des letzten Kontakts pro Kamera zurückzusetzen.
- Holt in `check_inactivity()` alle registrierten Kameras über `database.get_all_cameras()`.
- Berechnet für jede Kamera das dynamische Limit: `3 * sleep_duration_seconds` (mindestens aber 1 Stunde / 3600 Sekunden).
- Löst bei Inaktivität eine Warnung über das Event `InactivityAlertTriggered` aus.

---

### 6. Scheduler & Cleanup-Job

#### [MODIFY] [scheduler.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/scheduler.py)
- Hinzufügen eines täglichen Jobs `cleanup_camera_photos()`.
- **Cleanup-Logik:** 
  - Durchläuft alle Unterordner von `data/camera/`.
  - Sortiert alle Fotos eines Ordners chronologisch.
  - Löscht Fotos, die älter als `CAMERA_CLEANUP_DAYS` (30 Tage) sind.
  - Ausgeschlossen von der Löschung wird jeweils das erste aufgenommene Foto eines Kalendertages (das Foto mit dem frühesten Zeitstempel des Tages), um Zeitraffer-Analysen zu ermöglichen.

---

### 7. Benutzeroberfläche (Telegram UI)

#### [MODIFY] [telegram_ui.py](file:///c:/Users/g41nx/Repositories/garden/src/daemon/ui/telegram_ui.py)
- **Kopplung-Befehl (`/camera_setup`):** Startet den Assistenten, fragt nach dem Wunschnamen und ruft `camera_pairing.start_pairing(...)` auf.
- **Befehl `/photo` / `/camera`:**
  - Prüft über `database.get_all_cameras()`, wie viele Kameras registriert sind.
  - Wenn 0: Fehlermeldung ausgeben.
  - Wenn 1: Liest die Datei `latest.jpg` aus dem Verzeichnis der Kamera und sendet sie per `telegram_client.send_photo()`.
  - Wenn >1: Zeigt ein Inline-Keyboard mit den Wunschnamen der Kameras an. Der Klick auf eine Kamera führt das Senden des jeweiligen `latest.jpg`-Fotos aus.
- **Menü-Erweiterung:** Fügt die Buttons `"📷 Foto anzeigen"` und `"📷 Kamera koppeln"` in das Haupttastaturmenü (`get_main_keyboard()`) ein.

---

### 8. C++ Firmware (Garten-Kamera)

#### [NEW] [camera/main.cpp](file:///c:/Users/g41nx/Repositories/garden/camera/main.cpp)
Das C++ Programm auf Basis der M5Stack `TimerCam-arduino` und `ArduinoJson` Bibliotheken:
- **Konstruktoren & Setup:** Statische IP, Gateway und DNS-Server zur schnellen WLAN-Assoziierung konfigurieren.
- **Exponential Backoff:** `RTC_DATA_ATTR int failCount = 0` sichert den Zähler im RTC-RAM.
  - Bei erfolgreicher Übertragung: `failCount = 0`.
  - Bei Fehlschlag: `failCount++`. Das nächste Intervall beträgt $\min(60 \times 2^{\text{failCount}}, \text{default\_interval\_seconds})$.
- **Kopplung (`POST /register`):** Wird bei Erststart aufgerufen.
- **Upload (`POST /upload`):** Bild aufnehmen und raw per HTTP POST mit `X-Camera-MAC` Header an den Pi senden.
- **Schlafzustand:** Führt `bat_disable_output(sleep_seconds)` aus.

#### [NEW] [camera/config.h](file:///c:/Users/g41nx/Repositories/garden/camera/config.h)
- Statische Zugangsdaten: WLAN SSID, Passwort, IP-Adresse des Raspberry Pi, statische IP der Kamera, Standard-Schlafintervall.

---

## Verification Plan

### Automated Tests
- **`tests/adapters/test_camera_receiver.py`**:
  - Testet den HTTP-Server des Daemons (Mocks für DB und EventBus).
  - Verifiziert `POST /register` mit offenem/geschlossenem Koppel-Fenster.
  - Verifiziert `GET /config` für gekoppelte/ungekoppelte Kameras.
  - Verifiziert `POST /upload` mit gültigen Bild-Bytes und Assert auf das korrekte Dateiverzeichnis und die Event-Generierung.
- **`tests/core/test_camera_cleanup.py`**:
  - Mockt das Dateisystem und erstellt Bilddateien mit verschiedenen Zeitstempeln (z.B. vor 35 Tagen, 31 Tagen, 29 Tagen).
  - Führt den Cleanup-Algorithmus aus und prüft, ob alte Dateien (älter als 30 Tage) gelöscht, Tages-Erstbilder und neuere Dateien jedoch behalten wurden.

### Manual Verification
1. Führe den Koppelprozess über Telegram aus: `/camera_setup` eingeben, Name "Tomaten" vergeben.
2. Simuliere den Kamera-Pairing-Request:
   `curl -X POST -d "mac=94:B9:7E:12:34:56" http://<pi-ip>:8080/register`
   Prüfe, ob der Bot meldet: "Kamera 'Tomaten' erfolgreich gekoppelt!".
3. Simuliere einen Konfigurationsabruf:
   `curl -X GET -H "X-Camera-MAC: 94:B9:7E:12:34:56" http://<pi-ip>:8080/config`
   Die Antwort muss das standardmäßige Intervall und Kamera-Parameter als JSON enthalten.
4. Simuliere einen Bild-Upload:
   `curl -X POST -H "X-Camera-MAC: 94:B9:7E:12:34:56" -H "Content-Type: image/jpeg" --data-binary @tests/ui/test_telegram_ui.py http://<pi-ip>:8080/upload` (Hinweis: Hier kann eine echte JPG-Datei als Testbild übergeben werden).
5. Rufe `/photo` im Telegram-Bot ab und überprüfe die Fotoanzeige.
6. Simuliere eine Inaktivität (Watchdog-Test) durch manuelles Setzen der Systemzeit oder Mocken von `last_seen` in der DB und verifiziere die Warnung im Bot.
7. Kompiliere das C++ Programm in der Arduino-IDE, flashe die Kamera und prüfe das physische Aufwach- und Sende-Intervall per Serieller Konsole.
