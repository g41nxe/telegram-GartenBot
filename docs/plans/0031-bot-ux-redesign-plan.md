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

## Schritt 6 — Alle Dispatcher-Umbenennungen (Clean Cut)

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

## Schritt 7 — `main.py`: registrierte Befehle

```python
{"command": "tagesbericht",  "description": "Tagesbericht anzeigen"},
{"command": "zeitplaene",    "description": "Zeitpläne verwalten"},
{"command": "einstellungen", "description": "Einstellungen öffnen"},
{"command": "stopp",         "description": "Bewässerung sofort stoppen"},
```

## Schritt 8 — `telegram-nachrichten.html` aktualisieren

- Sektion 1: alle umbenannten Befehle, neue Untermenü-Karten für Kamera und Einstellungen
- Entfernte Karten: alle wegfallenden Befehle
- ADR 0012 Amendment einarbeiten: `/report` → `/tagesbericht`

## Schritt 9 — ADR 0012 und ADR 0033

- ADR 0012: Amendment-Notiz zu `/tagesbericht` einfügen
- Neuen ADR 0033 schreiben: Bot-Navigation — Gruppierung, Sprache, Menü-Struktur

## Definition of Done

- [ ] Alle Tests grün (bestehende + neue)
- [ ] Coverage nicht regriert
- [ ] `telegram-nachrichten.html` aktualisiert
- [ ] ADR 0012 und ADR 0033 geschrieben
- [ ] Beads-Issue `telegram-GartenBot-uxr` geschlossen
- [ ] Feature- und Plan-Dokument nach `completed/` verschoben
