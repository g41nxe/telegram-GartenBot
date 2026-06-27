# Implementierungsplan: Feature 0031 — Bot UX Redesign

Referenz: `docs/features/0031-bot-ux-redesign-befehle-und-menues.md`

## Schritt 1 — Tests (RED)

Neue Tests in `tests/ui/test_ux_redesign.py`:

- Neue Tastatur-Button-Texte lösen korrekte Handler aus (`📊 Status`, `🚿 Bewässern`, `🛑 Stopp`, `📅 Zeitpläne`, `📷 Kamera`, `⚙️ Einstellungen`)
- `📷 Kamera`-Button sendet Inline-Keyboard mit Callbacks `kamera_foto`, `kamera_verlauf`, `phtadd_start`
- `⚙️ Einstellungen`-Button sendet Inline-Keyboard mit 5 Buttons inkl. `update_start`
- `/tagesbericht` ruft denselben Report-Handler auf wie bisher `/report`
- `/zeitplaene` öffnet direkt die Gieß-Zeitpläne (keine Routing-Frage)
- `/foto` öffnet direkt die Foto-Anzeige
- `/stopp` stoppt die Bewässerung
- Entfernte Befehle (`/add`, `/delete`, `/toggle`, `/photo`, `/report`, `/stop`, `/setup`, `/zeitplan`, `/camera_setup`, `/photo_clear`, `/aufnahmen`) → „Unbekannter Befehl"
- Alte Tastatur-Texte (`📊 Status anzeigen`, `🚿 Bewässern starten`, `📸 Foto anzeigen`, `⚙️ Setup`) → „Unbekannter Befehl"
- Sofort-Nebel: `nebel_now` zeigt zuerst die Stoß-Dauer-Auswahl
- Sofort-Nebel: `nebel_now_on_{s}` zeigt danach die Pause-Auswahl
- Sofort-Nebel: `nebel_now_pause_{m}` zeigt zuletzt die Laufzeit-Auswahl (`nebel_dur_{m}`)
- Sofort-Nebel: nach der Laufzeit-Wahl wird `_nebel_ctrl.start(...)` mit den **gewählten** Stoß-/Pause-Werten aufgerufen (nicht mit den Config-Defaults)

## Schritt 2 — Legacy-Handler entfernen

- `handle_add_schedule()`, `handle_delete_schedule()`, `handle_toggle_schedule()` aus `telegram_ui.py` löschen
- Dispatcher-Einträge für `/add`, `/delete`, `/toggle` entfernen

## Schritt 3 — Haupttastatur aktualisieren (`get_main_keyboard`)

```
📊 Status          💧 Gießcheck
🚿 Bewässern       🛑 Stopp
📅 Zeitpläne       📷 Kamera
⚙️ Einstellungen
```

Dispatcher anpassen: alle alten Button-Text-Matches (`"📊 Status anzeigen"`, `"🚿 Bewässern starten"`, `"🛑 Sofort Stopp"`, `"📸 Foto anzeigen"`, `"⚙️ Setup"`) auf neue Texte umstellen.

## Schritt 4 — Kamera-Untermenü einführen

Neue Funktion `handle_kamera_menu(chat_id)` — sendet Inline-Keyboard:
```
📸 Foto anzeigen    🗑️ Fotos löschen
⏰ Fotozeiten
```
Callbacks: `kamera_foto` → `handle_photo()`, `kamera_verlauf` → `handle_photo_clear()`, `phtadd_start` → bestehender Wizard.

Dispatcher: `"📷 Kamera"` → `handle_kamera_menu(chat_id)`.

## Schritt 5 — Einstellungen-Untermenü erweitern (`handle_setup_menu`)

Funktion umbenennen → `handle_einstellungen_menu`. Untermenü erweitern:
```
🔧 Ventil koppeln    📷 Kamera koppeln
⏱ Kamera-Einstellungen   📊 Schwellenwerte
🔄 Software-Update
```
Neuer Callback `update_start` → `handle_update(chat_id)`.

Dispatcher: `"⚙️ Einstellungen"` und `/einstellungen` → `handle_einstellungen_menu(chat_id)`. `/setup` entfernen (Clean Cut).

## Schritt 6 — Sofort-Nebel: Takt-Auswahl (Inline-Flow)

Den Sofort-Nebel von Ein-Schritt (nur Laufzeit) auf Drei-Schritt umstellen: Stoß-Dauer → Pause → Laufzeit.

**`_start_sofort_nebel` Signatur erweitern** ([telegram_ui.py:64](../../src/daemon/ui/telegram_ui.py)):
```python
def _start_sofort_nebel(valve, minutes, on_seconds, pause_minutes):
    ...
    return _nebel_ctrl.start(valve["mqtt_name"], on_seconds, pause_minutes, end, "nebel_manual")
```
Die fest verdrahteten `config.NEBEL_ON_SECONDS` / `config.NEBEL_PAUSE_MINUTES` weichen den übergebenen Werten.

**Flow-Zustand** im Per-Chat-State halten (analog Wizard):
`{"flow": "nebel_now", "valve": …, "on_seconds": …, "pause_minutes": …}`

**Callback-Kette:**
| Callback | Aktion |
|---|---|
| `nebel_now` | Stoß-Dauer-Tastatur zeigen (`get_nebel_on_keyboard()`, Callbacks `nebel_now_on_{s}`) |
| `nebel_now_on_{s}` | `on_seconds` merken → Pause-Tastatur (`get_nebel_pause_keyboard()`, Callbacks `nebel_now_pause_{m}`) |
| `nebel_now_pause_{m}` | `pause_minutes` merken → Laufzeit-Tastatur (`get_nebel_now_keyboard()`, bestehende `nebel_dur_{m}`) |
| `nebel_dur_{m}` | `_start_sofort_nebel(valve, m, on_seconds, pause_minutes)` aus dem Flow-State |

- Die Stoß-/Pause-Tastaturen werden mit dem Zeitplan-Wizard geteilt, bekommen aber eigene Callback-Präfixe (`nebel_now_*`), damit der Dispatcher beide Flows sauber trennt.
- `NEBEL_ON_SECONDS` / `NEBEL_PAUSE_MINUTES` bleiben als vorausgewählte Default-Werte/Fallback in `config.py`.
- `nebel_stop` / `nebel_cancel` bleiben unverändert in jedem Schritt erreichbar.

## Schritt 7 — Alle Dispatcher-Umbenennungen (Clean Cut)

| Alt | Neu |
|---|---|
| `/report`, `/statusbericht` | `/tagesbericht` |
| `/zeitplan` | `/zeitplaene` |
| `/photo` | `/foto` |
| `/stop` | `/stopp` |
| `/camera_setup` | Entfernt (→ Kamera-Untermenü Callback) |
| `/photo_clear` | Entfernt (→ Kamera-Untermenü Callback) |
| `/aufnahmen` | Entfernt (→ Kamera-Untermenü Callback) |
| `/camera_interval` | Entfernt (→ Einstellungen Callback) |
| `/giesscheck` (Slash-Cmd) | Entfernt (nur Tastatur-Button) |

## Schritt 8 — `main.py`: registrierte Befehle

```python
{"command": "tagesbericht",  "description": "Tagesbericht anzeigen"},
{"command": "zeitplaene",    "description": "Zeitpläne verwalten"},
{"command": "einstellungen", "description": "Einstellungen öffnen"},
{"command": "stopp",         "description": "Bewässerung sofort stoppen"},
```

## Schritt 9 — `telegram-nachrichten.html` aktualisieren

- Sektion 1: alle umbenannten Befehle, neue Untermenü-Karten für Kamera und Einstellungen
- Sofort-Nebel-Karte: von Ein-Schritt auf Drei-Schritt-Flow (Stoß-Dauer → Pause → Laufzeit) aktualisieren
- Entfernte Karten: alle wegfallenden Befehle
- ADR 0012 Amendment einarbeiten: `/report` → `/tagesbericht`

## Schritt 10 — ADR 0012 und ADR 0034

- ADR 0012: Amendment-Notiz zu `/tagesbericht` einfügen
- Neuen ADR **0034** schreiben (0033 ist vom Nebel-Intervall belegt): Bot-Navigation — Gruppierung, Sprache, Menü-Struktur; inkl. Entscheidung „Sofort-Nebel-Takt pro Lauf, nicht persistiert"

## Definition of Done

- [ ] Alle Tests grün (bestehende + neue)
- [ ] Coverage nicht regriert
- [ ] `telegram-nachrichten.html` aktualisiert (inkl. Sofort-Nebel Drei-Schritt-Flow)
- [ ] Sofort-Nebel fragt Stoß-Dauer und Pause pro Lauf ab
- [ ] ADR 0012 und ADR 0034 geschrieben
- [ ] Beads-Issue `telegram-GartenBot-uxr` geschlossen
- [ ] Feature- und Plan-Dokument nach `completed/` verschoben
