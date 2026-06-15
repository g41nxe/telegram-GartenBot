# Feature: Kamera-Setup Wizard — Auflösung, Bildqualität und Menü-Reorganisation

## Problemstellung (Problem Statement)

Der bestehende Kamera-Kopplungs-Assistent (`/camera_setup`) fragt bisher nur nach einem Namen und einem Sendeintervall. Auflösung und Bildqualität können nach der Kamera-Kopplung nicht ohne technisches Wissen angepasst werden. Außerdem fehlen die Kamera-bezogenen Buttons im Hauptmenü des Telegram-Bots und die Kopplungsbefehle sind auf oberster Menüebene sichtbar, obwohl sie nur selten benötigt werden.

## Lösung (Solution)

Der Kamera-Kopplungs-Assistent wird um zwei weitere Schritte (Auflösung und Bildqualität) erweitert. Der Benutzer wählt diese per Inline-Keyboard aus, bevor die eigentliche Kamera-Kopplung startet. Die gewählten Werte werden in der Datenbank gespeichert und beim nächsten `/config`-Abruf der Garten-Kamera an die Firmware übermittelt, die sie sofort anwendet.

Parallel dazu wird das Hauptmenü des Telegram-Bots reorganisiert: Ein neuer `⚙️ Setup`-Button bündelt alle selten benötigten Kopplungs- und Einstellungsbefehle in einem zweiten Menü-Level, während häufig genutzte Funktionen (Status, Zeitpläne, Bewässerung, Foto) auf der Hauptebene bleiben.

## User Stories

1. Als Benutzer des Telegram-Bots möchte ich beim Anlegen einer neuen Garten-Kamera die gewünschte Auflösung aus einer vorgegebenen Liste auswählen können, um die Bildgröße an mein Speicher- und Übertragungsbudget anzupassen.
2. Als Benutzer des Telegram-Bots möchte ich beim Anlegen einer neuen Garten-Kamera die gewünschte Bildqualität aus einer vorgegebenen Liste auswählen können, um zwischen Dateigrößen und Bildschärfe abwägen zu können.
3. Als Benutzer des Telegram-Bots möchte ich die Auflösungs- und Qualitätsoptionen mit beschreibenden Labels (Hoch/Mittel/Niedrig) und passenden Emojis angezeigt bekommen, ohne technische Parameter wie Pixelzahlen oder numerische Qualitätswerte sehen zu müssen.
4. Als Benutzer des Telegram-Bots möchte ich, dass der Kamera-Kopplungs-Assistent genau 4 Schritte hat (Name → Intervall → Auflösung → Bildqualität), bevor die eigentliche Kopplung gestartet wird, um alle nötigen Einstellungen vorab zu treffen.
5. Als Benutzer des Telegram-Bots möchte ich, dass die von mir gewählte Auflösung und Bildqualität dauerhaft in der Datenbank gespeichert werden, damit die Garten-Kamera beim nächsten Einschalten automatisch mit diesen Einstellungen arbeitet.
6. Als Garten-Kamera möchte ich beim `/config`-Abruf einen Auflösungsparameter erhalten und diesen vor der Fotoaufnahme anwenden, damit die Bilder in der konfigurierten Auflösung aufgenommen werden.
7. Als Benutzer des Telegram-Bots möchte ich im Hauptmenü einen `⚙️ Setup`-Button sehen, hinter dem ich alle Kopplungs- und Einstellungsbefehle finde, damit das Hauptmenü übersichtlich bleibt.
8. Als Benutzer des Telegram-Bots möchte ich `📸 Foto anzeigen` weiterhin direkt im Hauptmenü haben, da ich diesen Befehl täglich nutze.
9. Als Benutzer des Telegram-Bots möchte ich im Setup-Untermenü `🔧 Ventil koppeln`, `📷 Kamera koppeln` und `⏱ Kamera-Einstellungen` als Inline-Keyboard finden, damit ich alle gerätebezogenen Aktionen an einem Ort habe.
10. Als Benutzer des Telegram-Bots möchte ich über `⏱ Kamera-Einstellungen` das Sendeintervall einer bereits gekoppelten Kamera ändern können, ohne die Kamera neu koppeln zu müssen.

## Implementierungs-Entscheidungen (Implementation Decisions)

### Wizard-Ablauf (4 Schritte)

Der Kamera-Kopplungs-Assistent durchläuft folgende State-Machine-Schritte im `wizard_states`-Dict:

```
"setup_camera_wish_name"
  → "setup_camera_interval"
    → "setup_camera_resolution"   [NEU — Inline-Keyboard]
      → "setup_camera_quality"    [NEU — Inline-Keyboard]
        → camera_pairing.start_pairing(...)
```

Die neuen Schritte werden durch Inline-Keyboard-Callbacks abgewickelt (`camsetup_res_<wert>` und `camsetup_qual_<wert>`), nicht durch Freitexteingabe.

### Auflösungs-Optionen

| Label | Inline-Wert | Technischer Wert | Framesize-Konstante |
|-------|-------------|------------------|---------------------|
| 🏔 Hoch (1600×1200) | `UXGA` | `UXGA` | `FRAMESIZE_UXGA` |
| ⚡ Mittel (1024×768) | `XGA`  | `XGA`  | `FRAMESIZE_XGA`  |
| 💨 Niedrig (640×480) | `VGA`  | `VGA`  | `FRAMESIZE_VGA`  |

Standard-Default: `UXGA` (höchste Qualität, da Speicher- und Bandbreitenkosten bei stündlichen Bildern vernachlässigbar).

### Qualitäts-Optionen

| Label | Inline-Wert | Numerischer Wert (ESP32-Treiber) |
|-------|-------------|----------------------------------|
| 🌟 Hoch  | `high`   | 10 |
| ⚡ Mittel | `medium` | 25 |
| 💨 Niedrig | `low`  | 40 |

Der ESP32-JPEG-Treiber verwendet eine inverse Skala (niedrigere Zahl = höhere Qualität). Im Telegram-Bot werden ausschließlich die beschreibenden Labels angezeigt.

Standard-Default: `high` → 10.

### Anpassungen an `camera_pairing.start_pairing()`

Die Funktion erhält zwei neue optionale Parameter `resolution: str = "UXGA"` und `quality: int = 10`. Nach erfolgreicher Kopplung werden diese gemeinsam mit `sleep_seconds` per `database.update_camera_settings()` persistiert.

### `/config`-Endpunkt (Bewässerungs-Daemon)

Der bestehende `/config`-Endpunkt der Kamera-HTTP-API wird um das Feld `resolution` (String: `"VGA"`, `"XGA"`, `"UXGA"`) erweitert. `quality` und `sleep_duration_seconds` sind bereits vorhanden.

### Firmware-Anpassung (Garten-Kamera)

In der Firmware wird nach dem Auslesen der Konfiguration vom `/config`-Endpunkt die Auflösung per `esp_camera_sensor_get()` → `s->set_framesize()` gesetzt. Dies geschieht zusammen mit dem bereits implementierten `s->set_quality()`-Aufruf.

### Menü-Reorganisation

**Neues Hauptmenü (Haupttastatur, 4×2):**
```
📊 Status anzeigen  │  📅 Zeitpläne
🟢 Bewässern starten │  🔴 Sofort Stopp
📸 Foto anzeigen    │  ⚙️ Setup
```

**Setup-Untermenü (Inline-Keyboard nach Klick auf ⚙️ Setup):**
```
🔧 Ventil koppeln   │  📷 Kamera koppeln
⏱ Kamera-Einstellungen
```

`⏱ Kamera-Einstellungen` startet einen Mini-Wizard: Bei einer Kamera direkte Minuteneingabe; bei mehreren Kameras zuerst Kamera-Auswahl per Inline-Keyboard.

Der Button-Text `📷 Foto anzeigen` wird zu `📸 Foto anzeigen` geändert (kein Doppel-Emoji mehr mit `📷 Kamera koppeln`).

### Callback-Daten-Konventionen

| Aktion | Callback-Data |
|--------|---------------|
| Auflösung gewählt | `camsetup_res_VGA`, `camsetup_res_XGA`, `camsetup_res_UXGA` |
| Qualität gewählt | `camsetup_qual_high`, `camsetup_qual_medium`, `camsetup_qual_low` |
| Setup-Menü öffnen | Textbutton `⚙️ Setup` → Inline-Keyboard-Reply |
| Kamera-Einstellungen | `camsetup_settings` |

### Datenbankschema

Keine Schema-Änderung erforderlich. Die Spalten `resolution` und `quality` existieren bereits in der `cameras`-Tabelle und werden durch `update_camera_settings()` befüllt.

## Test-Entscheidungen (Testing Decisions)

### Was einen guten Test ausmacht

Tests prüfen das beobachtbare Verhalten aus der Außenperspektive: Welche Werte landen nach einem vollständigen Wizard-Durchlauf in der Datenbank? Welche Nachricht wird an welchen Chat gesendet? Interna des Wizard-State-Dicts werden nicht direkt geprüft.

### Zu testende Module

**`tests/adapters/test_camera_pairing.py`** (bereits vorhanden):
- Neuer Test: `start_pairing` mit `resolution="VGA"` und `quality=25` persistiert diese Werte korrekt in der Datenbank.
- Neuer Test: Default-Werte (`resolution="UXGA"`, `quality=10`) werden gespeichert, wenn die Parameter weggelassen werden.

**`tests/ui/test_telegram_ui_camera_wizard.py`** (neu):
- Der Wizard-State wechselt nach Intervall-Eingabe in den Schritt `setup_camera_resolution`.
- Nach Auswahl der Auflösung via Callback wechselt der State in `setup_camera_quality`.
- Nach Auswahl der Qualität via Callback wird `camera_pairing.start_pairing()` mit den korrekten `resolution`- und `quality`-Argumenten aufgerufen.
- Ungültige Callback-Daten (unbekannte Auflösungs-/Qualitäts-Werte) werden verworfen.

### Vorarbeiten / Referenzen

- `tests/adapters/test_camera_pairing.py`: Referenzmuster für Setup, Triggering und DB-Verifikation.
- `tests/test_irrigation.py` (`setUpClass`): Referenz für EventBus-Verdrahtung in Tests.

## Nicht im Leistungsumfang (Out of Scope)

- Nachträgliche Änderung von Auflösung und Qualität einer bereits gekoppelten Kamera (separater Wizard-Schritt oder Befehl). `⏱ Kamera-Einstellungen` ändert vorerst nur das Sendeintervall.
- Kamera-spezifische Helligkeits-, Sättigungs- oder Weißabgleich-Einstellungen.
- Vollständige Trennung der Feature-0013-Konfigurationsdatei (explizit zurückgestellt).
- Validierung, ob die gewählte Auflösung vom Kamera-Sensor unterstützt wird (der OV3660 unterstützt alle drei Optionen).

## Weitere Anmerkungen (Further Notes)

- Der ESP32-JPEG-Qualitätswert ist invers (10 = hoch, 40 = niedrig). Die Firmware-Dokumentation ist irreführend — der tatsächliche Wertebereich des OV3660-Treibers ist 0–63, wobei niedrigere Werte schärfere Bilder bei größeren Dateien ergeben.
- Die Garten-Kamera schläft zwischen den Übertragungen im Deep-Sleep. Die Auflösungsänderung wird daher erst beim nächsten Aufwachen wirksam, wenn die Kamera erneut `/config` abruft.
- ADR-0026 (Integration M5Stack Timer Camera F) bleibt gültig — dieses Feature erweitert den `/config`-Vertrag, bricht ihn aber nicht.
