# Implementierungsplan: Feature 0031 — Bot UX Redesign

Referenz: `docs/features/0031-bot-ux-redesign-befehle-und-menues.md`

## Schritt 1 — Tests (RED)

Neue Tests in `tests/ui/test_ux_redesign.py`:

- Neue Tastatur-Button-Texte lösen korrekte Handler aus (`📊 Status`, `🚿 Bewässern`, `🛑 Stopp`, `📅 Zeitpläne`, `📷 Kamera`, `⚙️ Einstellungen`)
- `📷 Kamera`-Button sendet Inline-Keyboard mit Callbacks `kamera_foto`, `kamera_verlauf`, `phtadd_start`
- `⚙️ Einstellungen`-Button sendet Inline-Keyboard mit 5 Buttons inkl. `update_start`
- `/tagesbericht` ruft denselben Report-Handler auf wie bisher `/report`
- `/zeitplaene` öffnet direkt die Gieß-Zeitpläne (keine Routing-Frage)
- `/stopp` stoppt die Bewässerung
- _Endstand (De-dup):_ `/foto` **nicht** als Befehl übernommen (Foto nur über 📷 Kamera ▸ Foto anzeigen). Registriertes Menü: `/status` (Ausnahme), `/tagesbericht`, `/update`. `/zeitplaene`, `/einstellungen`, `/stopp` ganz entfernt (nur Button).
- Entfernte Befehle (`/add`, `/delete`, `/toggle`, `/photo`, `/foto`, `/report`, `/stop`, `/setup`, `/zeitplan`, `/camera_setup`, `/photo_clear`, `/aufnahmen`) → „Unbekannter Befehl"
- Alte Tastatur-Texte (`📊 Status anzeigen`, `🚿 Bewässern starten`, `📸 Foto anzeigen`, `⚙️ Setup`) → „Unbekannter Befehl"
- Bewässern: `🚿 Bewässern` zeigt zuerst die Art-Auswahl (`water_mode_guss`, `nebel_now`)
- Bewässern/Guss: bei genau einem Ventil entfällt die Ventil-Frage und der Zeitlimit-Schritt folgt direkt
- Bewässern/Guss: bei mehreren Ventilen erscheint die Auswahl (`water_valve_{id}`); der gewählte `mqtt_name` landet in `start_watering(..., mqtt_name=…)`
- Bewässern: ohne gekoppeltes Ventil → Hinweis statt Start
- Sofort-Nebel: nach Ventil-Wahl folgt Stoß-Dauer-Auswahl
- Sofort-Nebel: `nebel_now_on_{s}` zeigt danach die Pause-Auswahl
- Sofort-Nebel: `nebel_now_pause_{m}` zeigt zuletzt die Laufzeit-Auswahl (`nebel_dur_{m}`)
- Sofort-Nebel: nach der Laufzeit-Wahl wird `_nebel_ctrl.start(...)` mit den **gewählten** Stoß-/Pause-Werten aufgerufen (nicht mit den Config-Defaults)
- Stopp: aktive Quellen zählen Güsse + laufendes Nebel-Fenster; bei 0/1 sofort stoppen, bei mehreren erscheint die Auswahl inkl. `stop_valve_all`
- Stopp: laufendes Nebel-Fenster erscheint als `stop_nebel_{mqtt_name}` und stoppt via `nebel_ctrl.stop(mqtt_name)`
- Stopp: `stop_valve_{mqtt_name}` stoppt einen Guss gezielt; `stop_valve_all` → `stop_watering()` **und** `nebel_ctrl.stop()`
- Nebel-Unterdrückung: nach `nebel_ctrl.stop()` ist `is_suppressed(mqtt_name)` bis `end_time` wahr; `_ensure_nebel_window` startet nicht neu
- Nebel-Unterdrückung: `nebel_ctrl.start(mqtt_name)` hebt die Sperre auf; nach `end_time` läuft sie lazy ab
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

## Schritt 8 — „Stopp": querschnittlicher Aus-Knopf (Güsse + Nebel) + Restart-Unterdrückung

**Neue Lese-Methoden in `core/`:**
```python
# watering_controller.py
def get_active_valve_names(self):
    with self._lock:
        return list(self._active_cycles.keys())

# nebel_controller.py — laufendes Fenster fürs Stopp-Menü
def get_active_window(self):           # -> mqtt_name | None (ein Fenster pro Ventil)
    with self._lock:
        return next(iter(self._cycles.keys()), None)
```

**Restart-Unterdrückung in `nebel_controller.py` (C1, in-memory):**
```python
# __init__
self._suppressed_until: Dict[str, datetime] = {}

# stop(mqtt_name): vor _finish die end_time des laufenden Fensters merken
self._suppressed_until[name] = self._cycles[name]["end_time"]

# start(mqtt_name): expliziter Neustart hebt die Sperre auf
self._suppressed_until.pop(mqtt_name, None)

def is_suppressed(self, mqtt_name: str) -> bool:
    until = self._suppressed_until.get(mqtt_name)
    if until is None:
        return False
    if datetime.now() >= until:       # lazy ablaufen lassen
        self._suppressed_until.pop(mqtt_name, None)
        return False
    return True
```

**Scheduler-Prüfung** (`scheduler._ensure_nebel_window`): Start nur, wenn
`not _nebel_controller.is_active(mqtt_name) and not _nebel_controller.is_suppressed(mqtt_name)`.

**Dispatcher „🛑 Stopp":**
- Aktive Quellen sammeln: Güsse (`get_active_valve_names()`) + laufendes Nebel-Fenster (`get_active_window()`).
- 0 → „Es läuft gerade nichts."
- 1 → direkt stoppen (Guss → `stop_watering(name)`; Nebel → `nebel_ctrl.stop(name)`).
- >1 → Inline-Keyboard: je Guss `stop_valve_{mqtt_name}`, fürs Fenster `stop_nebel_{mqtt_name}` (Label „{wish_name} (Nebel)"), plus `stop_valve_all`.

**Callbacks:**
- `stop_valve_{mqtt_name}` → `stop_watering(mqtt_name)`
- `stop_nebel_{mqtt_name}` → `nebel_ctrl.stop(mqtt_name)` (setzt damit die Suppression)
- `stop_valve_all` → `stop_watering()` **und** `nebel_ctrl.stop()`

**Hinweis:** Der bestehende „🛑 Nebel stoppen"-Button (`nebel_stop`) bleibt; auch er setzt künftig die Suppression (gleicher `stop()`-Pfad).

## Schritt 9 — Alle Dispatcher-Umbenennungen (Clean Cut)

| Alt | Neu |
|---|---|
| `/report`, `/statusbericht` | `/tagesbericht` |
| `/zeitplan` | `/zeitplaene` |
| `/photo` | Entfernt (→ 📷 Kamera ▸ Foto anzeigen; `/foto` bei Umsetzung verworfen) |
| `/stop` | `/stopp` |
| `/camera_setup` | Entfernt (→ Kamera-Untermenü Callback) |
| `/photo_clear` | Entfernt (→ Kamera-Untermenü Callback) |
| `/aufnahmen` | Entfernt (→ Kamera-Untermenü Callback) |
| `/camera_interval` | Entfernt (→ Einstellungen Callback) |
| `/giesscheck` (Slash-Cmd) | Entfernt (nur Tastatur-Button) |

## Schritt 10 — `main.py`: registrierte Befehle

```python
{"command": "status",        "description": "Systemstatus anzeigen"},
{"command": "tagesbericht",  "description": "Tagesbericht anzeigen"},
{"command": "update",        "description": "Software-Update starten"},
```
_Endstand (De-dup-Regel):_ Registriert sind nur Befehle ohne gleichwertigen Button (`/tagesbericht`, `/update`) plus die bewusste Ausnahme `/status` (häufigster + in Nachrichten verlinkt). `/zeitplaene`, `/einstellungen` und `/stopp` wurden **ganz entfernt** (reine Button-Duplikate ohne Verlinkung) — nur noch über ihren Tastatur-Button erreichbar. `/update` ist registriert (CI-verlinkt). Siehe `.agents/rules/telegram_messages.md`.

## Schritt 11 — `telegram-nachrichten.html` aktualisieren

- Sektion 1: alle umbenannten Befehle, neue Untermenü-Karten für Kamera und Einstellungen
- „Bewässern"-Karte: neuer Art→Ventil→Details-Flow (Guss und Sofort-Nebel)
- Sofort-Nebel-Karte: Ventil-Auswahl + Drei-Schritt-Takt (Stoß-Dauer → Pause → Laufzeit)
- „Stopp"-Karte: querschnittlicher Aus-Knopf (Güsse + laufendes Nebel-Fenster), Auswahl bei mehreren aktiven (inkl. „Alle stoppen")
- Zeitplan-Karte: Sofort-Nebel-Zeile entfernt
- Entfernte Karten: alle wegfallenden Befehle
- ADR-Amendments einarbeiten: `/report` → `/tagesbericht` (0012)

## Schritt 12 — ADRs schreiben/ergänzen

- **ADR 0012:** Amendment-Notiz zu `/tagesbericht` (bereits eingefügt — verifizieren).
- **ADR 0015 (Amendment):** manueller Sofort-Guss = Einzel-Ventil; Mehrfach + Ausführungsmodus bleibt den Zeitplänen vorbehalten; systemweite Einzel-Ventil-Konvention, ungefilterte Ventil-Liste.
- **ADR 0033 (Amendment):** (a) Sofort-Nebel fragt Stoß-Dauer/Pause pro Lauf; (b) manuell gestopptes Fenster wird bis `end_time` gegen Scheduler-Neustart unterdrückt (in-memory, C1); (c) „Stopp" ist querschnittlicher Notfall-Aus über Güsse + Nebel.
- **Neuer ADR 0034** (0033 belegt): Bot-Navigation — Gruppierung, Sprache, Menü-Struktur, „Bewässern" als gemeinsamer Einstieg (Art → Ventil → Details), Auto-Selektion bei einem Ventil, „Stopp" als querschnittlicher Aus-Knopf. ADR 0034 ist im Grilling bereits gedraftet — bei Implementierung nur finalisieren.

## Definition of Done

- [ ] Alle Tests grün (bestehende + neue)
- [ ] Coverage nicht regriert
- [ ] `telegram-nachrichten.html` aktualisiert (inkl. Bewässern-Flow, Sofort-Nebel, Stopp-Auswahl)
- [ ] Sofort-Nebel fragt Stoß-Dauer und Pause pro Lauf ab
- [ ] Bewässern fragt Art und Ventil ab; Stopp ist querschnittlicher Aus-Knopf (Güsse + Nebel)
- [ ] Manuell gestopptes Nebel-Fenster läuft nicht wieder an (Suppression, C1)
- [ ] Sofort-Nebel aus der Zeitplan-Ansicht in „Bewässern" umgezogen
- [ ] ADR 0034 geschrieben; Amendments zu 0012, 0015, 0033 eingefügt
- [ ] Beads-Issue `telegram-GartenBot-uxr` geschlossen
- [ ] Feature- und Plan-Dokument nach `completed/` verschoben
