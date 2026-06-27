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
- Bewässern: `🚿 Bewässern` zeigt zuerst die Art-Auswahl (`water_mode_guss`, `nebel_now`)
- Bewässern/Guss: bei genau einem Ventil entfällt die Ventil-Frage und der Zeitlimit-Schritt folgt direkt
- Bewässern/Guss: bei mehreren Ventilen erscheint die Auswahl (`water_valve_{id}`); der gewählte `mqtt_name` landet in `start_watering(..., mqtt_name=…)`
- Bewässern: ohne gekoppeltes Ventil → Hinweis statt Start
- Sofort-Nebel: nach Ventil-Wahl folgt Stoß-Dauer-Auswahl
- Sofort-Nebel: `nebel_now_on_{s}` zeigt danach die Pause-Auswahl
- Sofort-Nebel: `nebel_now_pause_{m}` zeigt zuletzt die Laufzeit-Auswahl (`nebel_dur_{m}`)
- Sofort-Nebel: nach der Laufzeit-Wahl wird `_nebel_ctrl.start(...)` mit den **gewählten** Stoß-/Pause-Werten aufgerufen (nicht mit den Config-Defaults)
- Stopp: bei 0/1 aktivem Ventil sofort stoppen; bei mehreren aktiven erscheint die Auswahl inkl. `stop_valve_all`
- Stopp: `stop_valve_{mqtt_name}` stoppt gezielt; `stop_valve_all` → `stop_watering()` ohne Argument
- Zeitplan-Ansicht enthält keine Sofort-Nebel-Zeile mehr

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

## Schritt 7 — „Bewässern": Art- und Ventil-Auswahl + Nebel-Umzug

Den „Bewässern"-Einstieg zum gemeinsamen Einstieg für Guss **und** Sofort-Nebel machen. Muster für beide Zweige: **Art → Ventil → Details**.

**Art-Auswahl (neu):** Tastatur-Button „🚿 Bewässern" sendet künftig ein Inline-Keyboard statt direkt den Zeitlimit-Schritt:
```
[🚿 Guss]  [🌫️ Sofort-Nebel]
[❌ Abbrechen]
```
Callbacks: `water_mode_guss`, `nebel_now` (bestehend).

**Guss-Zweig — Ventil-Auswahl (neu):** `water_mode_guss` →
- `database.get_all_valves()`: 0 → Hinweis; 1 → `mqtt_name` in Flow-State, direkt zum bestehenden Zeitlimit-Schritt; >1 → Auswahl `water_valve_{id}`.
- `water_valve_{id}` → `mqtt_name` in Flow-State, weiter zum Zeitlimit-Schritt.
- Bestehenden Volumenlimit-Abschluss anpassen: `_watering_ctrl.start_watering(dur, vol, "manual", mqtt_name=<state>)`.

**Nebel-Zweig — Ventil vor Takt:** Die Ventil-Auswahl aus dem Nebel-Flow (heute am Ende nach `nebel_dur_`) nach vorne ziehen: `nebel_now` → Ventil-Auswahl (skip bei 1) → dann Schritt 6 (Stoß-Dauer → Pause → Laufzeit). Das gewählte Ventil im Flow-State halten; `nebel_dur_` nutzt es direkt statt erneut zu fragen.

**Nebel-Button aus Zeitplänen entfernen:** In `get_schedules_inline_keyboard` die Zeile `rows.append([{"text": "🌫️ Sofort-Nebel", …}])` ([telegram_ui.py:258](../../src/daemon/ui/telegram_ui.py)) streichen.

## Schritt 8 — „Stopp": Ventil-Auswahl bei mehreren aktiven

**Neue Controller-Lese-Methode** in `core/watering_controller.py`:
```python
def get_active_valve_names(self):
    with self._lock:
        return list(self._active_cycles.keys())
```

**Dispatcher „🛑 Stopp":**
- `aktiv = _watering_ctrl.get_active_valve_names()`
- 0 → „Es läuft gerade keine Bewässerung."
- 1 → `_watering_ctrl.stop_watering(aktiv[0])` direkt.
- >1 → Inline-Keyboard mit `stop_valve_{mqtt_name}` je aktivem Ventil (Anzeigename via `database.get_valve_by_mqtt_name`) + `stop_valve_all`.

**Callbacks:** `stop_valve_{mqtt_name}` → `stop_watering(mqtt_name)`; `stop_valve_all` → `stop_watering()` (alle).

## Schritt 9 — Alle Dispatcher-Umbenennungen (Clean Cut)

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

## Schritt 10 — `main.py`: registrierte Befehle

```python
{"command": "tagesbericht",  "description": "Tagesbericht anzeigen"},
{"command": "zeitplaene",    "description": "Zeitpläne verwalten"},
{"command": "einstellungen", "description": "Einstellungen öffnen"},
{"command": "stopp",         "description": "Bewässerung sofort stoppen"},
```

## Schritt 11 — `telegram-nachrichten.html` aktualisieren

- Sektion 1: alle umbenannten Befehle, neue Untermenü-Karten für Kamera und Einstellungen
- „Bewässern"-Karte: neuer Art→Ventil→Details-Flow (Guss und Sofort-Nebel)
- Sofort-Nebel-Karte: Ventil-Auswahl + Drei-Schritt-Takt (Stoß-Dauer → Pause → Laufzeit)
- „Stopp"-Karte: Ventil-Auswahl bei mehreren aktiven (inkl. „Alle stoppen")
- Zeitplan-Karte: Sofort-Nebel-Zeile entfernt
- Entfernte Karten: alle wegfallenden Befehle
- ADR 0012 Amendment einarbeiten: `/report` → `/tagesbericht`

## Schritt 12 — ADR 0012 und ADR 0034

- ADR 0012: Amendment-Notiz zu `/tagesbericht` einfügen
- Neuen ADR **0034** schreiben (0033 ist vom Nebel-Intervall belegt): Bot-Navigation — Gruppierung, Sprache, Menü-Struktur; inkl. Entscheidungen „Sofort-Nebel-Takt pro Lauf, nicht persistiert", „manuelle Bewässerung folgt Muster Art → Ventil → Details", „Ventil-Auswahl wird bei genau einem Ventil übersprungen", „Stopp fragt nur bei mehreren aktiven Ventilen"

## Definition of Done

- [ ] Alle Tests grün (bestehende + neue)
- [ ] Coverage nicht regriert
- [ ] `telegram-nachrichten.html` aktualisiert (inkl. Bewässern-Flow, Sofort-Nebel, Stopp-Auswahl)
- [ ] Sofort-Nebel fragt Stoß-Dauer und Pause pro Lauf ab
- [ ] Bewässern fragt Art und Ventil ab; Stopp fragt Ventil bei mehreren aktiven ab
- [ ] Sofort-Nebel aus der Zeitplan-Ansicht in „Bewässern" umgezogen
- [ ] ADR 0012 und ADR 0034 geschrieben
- [ ] Beads-Issue `telegram-GartenBot-uxr` geschlossen
- [ ] Feature- und Plan-Dokument nach `completed/` verschoben
