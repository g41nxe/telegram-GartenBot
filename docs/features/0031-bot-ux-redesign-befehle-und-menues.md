# Feature 0031: Bot UX Redesign — Befehle vereinheitlichen, Untermenüs strukturieren

## Problemstellung (Problem Statement)

Die Telegram-Bot-Befehle sind organisch gewachsen und weisen mehrere Inkonsistenzen auf:
- Gemischte Sprachen: englische Namen (`/photo`, `/report`, `/setup`, `/camera_setup`, `/photo_clear`, `/stop`) neben deutschen (`/zeitplan`, `/einstellungen`, `/giesscheck`)
- Keine klare Gruppierung: Kamera-Funktionen sind auf mehrere Standalone-Befehle verteilt (`/photo`, `/photo_clear`, `/camera_setup`, `/aufnahmen`)
- Das Telegram-Befehlsmenü (`/`-Liste) listet 11 Befehle, darunter Setup-Befehle die selten gebraucht werden
- Legacy-Textbefehle `/add`, `/delete`, `/toggle` sind seit Feature 0021 (Zeitplan-Bearbeitung) durch den Wizard-UI ersetzt, aber weiterhin registriert
- `/setup` öffnet direkt den Ventil-Wizard statt ein Untermenü zu zeigen, obwohl `handle_setup_menu()` bereits existiert

## Lösung (Solution)

Vollständiges UX-Redesign der Telegram-Bot-Navigation:

- Alle Befehle werden auf Deutsch umbenannt und nach Domäne gruppiert
- Ein neuer „📷 Kamera"-Tastatur-Button bündelt alle Kamera-Funktionen in einem Inline-Untermenü
- „⚙️ Setup" wird zu „⚙️ Einstellungen" mit erweitertem Untermenü (inkl. Software-Update)
- Das registrierte Telegram-Menü schrumpft auf 4 Befehle (nur was nicht per Tastatur erreichbar ist)
- Legacy-Befehle `/add`, `/delete`, `/toggle` werden vollständig entfernt
- Sauberer Schnitt: keine Aliases für umbenannte Befehle

## User Stories

1. Als Benutzer möchte ich alle Befehle auf Deutsch sehen, damit ich nicht zwischen englischen und deutschen Namen wechseln muss.
2. Als Benutzer möchte ich alle Kamera-Funktionen unter einem einzigen „📷 Kamera"-Button finden, damit ich nicht mehrere separate Befehle kennen muss.
3. Als Benutzer möchte ich den Tagesbericht mit `/tagesbericht` abrufen, damit der Befehlsname dem bekannten Begriff „Tagesbericht" entspricht.
4. Als Benutzer möchte ich `/zeitplaene` tippen und sofort die Gieß-Zeitpläne sehen (ohne zusätzliche Routing-Frage), damit der häufigste Weg keine Extraklicks kostet.
5. Als Benutzer möchte ich Foto-Aufnahme-Zeitpunkte über das Kamera-Untermenü verwalten, damit zusammengehörige Funktionen gemeinsam zu finden sind.
6. Als Benutzer möchte ich Software-Updates über das Einstellungen-Untermenü starten, damit gefährliche Aktionen nicht prominent im Hauptmenü sichtbar sind.
7. Als Benutzer möchte ich `/stopp` als Notfallbefehl tippen können (auch ohne Tastatur), damit ich die Bewässerung jederzeit schnell unterbrechen kann.
8. Als Benutzer möchte ich ein aufgeräumtes Telegram-`/`-Menü mit maximal 4 Einträgen sehen, damit ich schnell den gewünschten Befehl finde.
9. Als Benutzer möchte ich „Bild-Historie löschen" über das Kamera-Untermenü (Button „Fotos löschen") auslösen, damit die Löschaktion im richtigen Kontext liegt.
10. Als Benutzer möchte ich, dass `/setup` dasselbe Einstellungen-Untermenü öffnet wie der Tastatur-Button, damit es kein inkonsistentes Verhalten gibt.
11. Als Benutzer möchte ich beim Sofort-Nebel die Stoß-Dauer und die Pause zwischen den Stößen pro Lauf wählen, damit ich den Kühl-Takt situativ an Hitze und Wind anpassen kann, ohne die Konfiguration auf dem Pi zu ändern.
12. Als Benutzer möchte ich beim manuellen Bewässern auswählen, welches Ventil geöffnet werden soll, damit ich bei mehreren Ventilen gezielt das richtige bewässere.
13. Als Benutzer möchte ich beim Sofort-Stopp auswählen, welches aktive Ventil geschlossen werden soll (oder alle), damit ich bei mehreren laufenden Güssen gezielt eingreifen kann.
14. Als Benutzer möchte ich den Sofort-Nebel über „Bewässern starten" auslösen statt über die Zeitpläne, damit alle manuellen Bewässerungs-Aktionen (Guss und Nebel) an einem Ort liegen und die Zeitplan-Ansicht nur noch Zeitpläne enthält.

## Implementierungs-Entscheidungen (Implementation Decisions)

### Haupttastatur (Reply-Keyboard)
```
📊 Status          💧 Gießcheck
🚿 Bewässern       🛑 Stopp
📅 Zeitpläne       📷 Kamera
⚙️ Einstellungen
```
- „Status anzeigen" → „Status", „Bewässern starten" → „Bewässern", „Sofort Stopp" → „Stopp"
- „📸 Foto anzeigen" entfällt aus der Haupttastatur (→ Kamera-Untermenü)
- „⚙️ Setup" → „⚙️ Einstellungen"

### 🚿 Bewässern starten — Art- und Ventil-Auswahl (Inline-Flow)

„Bewässern" wird ein gemeinsamer Einstieg für *alle* manuellen Bewässerungs-Aktionen. Reihenfolge: **Art → Ventil → Details** (für beide Zweige gleich).

```
🚿 Bewässern
 1. Was möchtest du?   [🚿 Guss]  [🌫️ Sofort-Nebel]
 2. Welches Ventil?    [🚰 Rasen] [🚰 Beet]   (entfällt bei genau einem Ventil)
 3a. Guss:  Zeitlimit → Volumenlimit → Start
 3b. Nebel: Stoß-Dauer → Pause → Laufzeit → Start
```

- **Schritt 1 (Art):** Inline-Keyboard `[🚿 Guss] [🌫️ Sofort-Nebel]` + Abbrechen. Callbacks `water_mode_guss`, `nebel_now`.
- **Schritt 2 (Ventil):** Liste der gekoppelten Ventile (`database.get_all_valves()`). 0 Ventile → Hinweis „Koppel zuerst ein Ventil über Einstellungen". Genau 1 Ventil → Frage entfällt, direkt weiter (kein Extra-Klick, analog zum bestehenden Nebel-Muster). >1 → Auswahl `water_valve_{id}`.
- **Guss-Zweig:** der gewählte `mqtt_name` wird im Flow-State gehalten und an `_watering_ctrl.start_watering(dur, vol, "manual", mqtt_name=…)` übergeben. Der Controller unterstützt das bereits (Feature 0006).
- **Nebel-Zweig:** identisch zur Sofort-Nebel-Logik (siehe unten), nur dass die Ventil-Auswahl jetzt **vor** Stoß-Dauer/Pause/Laufzeit kommt — damit beide Zweige dem Muster „Art → Ventil → Details" folgen.
- Die Sofort-Nebel-Zeile **wandert aus der Zeitplan-Ansicht** (`get_schedules_inline_keyboard`) hierher. Die Zeitplan-Ansicht zeigt danach nur noch Zeitpläne + „➕ Neuer Zeitplan".

### 🛑 Sofort Stopp — Ventil-Auswahl (nur bei mehreren aktiven)

```
🛑 Stopp
 0/1 aktives Ventil → sofort stoppen (kein Extra-Klick im Notfall)
 >1 aktiv → [🛑 Rasen] [🛑 Beet] [🛑 Alle stoppen]
```

- Aktive Ventile kommen aus dem `WateringController` (neue Lese-Methode `get_active_valve_names()` → `list(self._active_cycles.keys())`).
- 0 aktiv → „Es läuft gerade keine Bewässerung." 1 aktiv → direkt `stop_watering(mqtt_name)`. >1 aktiv → Auswahl `stop_valve_{mqtt_name}` je aktivem Ventil + „🛑 Alle stoppen" (`stop_valve_all` → `stop_watering()` ohne Argument).
- Wunschname für die Buttons über `database.get_valve_by_mqtt_name(...)`.
- Scope: „Stopp" bezieht sich auf laufende Güsse. Der Nebel-Intervall wird weiterhin über seinen eigenen „🛑 Nebel stoppen"-Button beendet (unverändert).

### 📷 Kamera-Untermenü (Inline-Keyboard)
```
📸 Foto anzeigen    🗑️ Fotos löschen
⏰ Fotozeiten
```
- „Fotos löschen" ist UI-Kurzform für „Bild-Historie löschen" (CONTEXT.md: _UI-Ausnahme_)
- „Fotozeiten" ist UI-Kurzform für „Aufnahme-Zeitpunkte" (CONTEXT.md: _UI-Ausnahme_)
- Emoji ⏰ für Fotozeiten (nicht 📅 — ADR 0029: 📅 ist semantisch für Gieß-Zeitpläne reserviert)
- Bestätigungs-Dialog für „Fotos löschen" bleibt als Reply-Keyboard (ADR 0013)

### ⚙️ Einstellungen-Untermenü (Inline-Keyboard)
```
🔧 Ventil koppeln    📷 Kamera koppeln
⏱ Kamera-Einstellungen   📊 Schwellenwerte
🔄 Software-Update
```
- Erweitert um „🔄 Software-Update" (bisher eigener Menü-Eintrag)

### 🌫️ Sofort-Nebel — Takt pro Lauf wählbar (Inline-Flow)

Bisher fragt der Sofort-Nebel nur die Gesamtlaufzeit ab und nutzt für Stoß-Dauer und Pause feste Config-Defaults (`NEBEL_ON_SECONDS`, `NEBEL_PAUSE_MINUTES`). Künftig fragt der Flow drei Takt-Schritte ab (nach der Ventil-Auswahl aus „Bewässern starten"):

```
🌫️ Sofort-Nebel  (Ventil bereits gewählt)
 1. Stoß-Dauer?  [10s] [20s] [30s] [45s]
 2. Pause?       [2] [3] [5] [10] Min
 3. Laufzeit?    [15] [30] [60] [120] Min
```

- Reihenfolge im Gesamt-Flow: Art (Nebel) → Ventil → Stoß-Dauer → Pause → Laufzeit → Start. Erst nach der Laufzeit-Wahl öffnet sich das Nebel-Ventil.
- **Änderung gegenüber Ist-Stand:** Die Ventil-Auswahl wandert vom Ende (heute nach `nebel_dur_`) an den Anfang (direkt nach der Art-Wahl), damit Guss- und Nebel-Zweig demselben Muster „Art → Ventil → Details" folgen.
- Die Tastaturen für Stoß-Dauer und Pause werden mit dem geplanten Nebel-Intervall geteilt (`get_nebel_on_keyboard()` / `get_nebel_pause_keyboard()`), bekommen aber eigene Callbacks (`nebel_now_on_{s}`, `nebel_now_pause_{m}`), damit der Dispatcher Sofort- und Zeitplan-Flow nicht verwechselt.
- `NEBEL_ON_SECONDS` und `NEBEL_PAUSE_MINUTES` bleiben als voreingestellte Default-Werte erhalten (vorausgewählter Button bzw. Fallback), steuern das Verhalten aber nicht mehr fest.
- `NEBEL_MANUAL_MAX_MINUTES` deckelt weiterhin die Laufzeit (harter Backstop, unverändert).
- Der gewählte Takt gilt nur für diesen einen Lauf — es wird nichts persistiert (bewusst, analog zur „Laufzeit"-Wahl).

### Registriertes Telegram-Menü (4 Einträge, keine Duplikate zu Tastatur-Buttons)
- `/tagesbericht` — Tagesbericht manuell abrufen
- `/zeitplaene` — Gieß-Zeitpläne öffnen
- `/einstellungen` — Einstellungen-Untermenü öffnen
- `/stopp` — Bewässerung sofort stoppen (Notfall-Direktzugriff)

### Dispatcher-only Befehle (funktionieren, aber nicht registriert)
- `/status` — entspricht Tastatur-Button „📊 Status"
- `/foto` — entspricht „📸 Foto anzeigen" im Kamera-Untermenü
- `/stopp` — auch im Menü registriert

### Entfernte Befehle (Clean Cut — keine Aliases)
- `/add`, `/delete`, `/toggle` — seit Feature 0021 durch Wizard-UI ersetzt
- `/photo`, `/report`, `/stop`, `/setup`, `/zeitplan` — englisch/umbenannt
- `/camera_setup`, `/photo_clear`, `/camera_times`, `/aufnahmen` — in Untermenüs integriert
- `/statusbericht`, `/camera_interval` — wegfallende Aliases

### ADR-Änderungen
- ADR 0012, Punkt 6: `/report` und `/statusbericht` werden zu `/tagesbericht` zusammengeführt (domain-konform zu CONTEXT.md „Tagesbericht"; _Avoid_: Daily-Report, Status-Report)
- Neuer ADR **0034** dokumentiert die Gesamtentscheidung zur Bot-Navigation (ADR 0033 ist bereits vom Nebel-Intervall belegt). Der ADR hält auch fest, dass der Sofort-Nebel-Takt pro Lauf gewählt wird (nicht persistiert), konsistent zur Laufzeit-Wahl.

### telegram-nachrichten.html
Bei der Implementierung muss `docs/design/telegram-nachrichten.html` aktualisiert werden:
- Sektion 1 (Befehle & Menüs): alle umbenannten Befehle, neue Untermenü-Karten
- Neue Karte: „📷 Kamera"-Untermenü (Inline-Keyboard)
- Geänderte Karte: „⚙️ Einstellungen"-Untermenü (mit Software-Update)
- Entfernte Karten: alle wegfallenden Befehle

## Test-Entscheidungen (Testing Decisions)

- Tests erfolgen auf der Dispatcher-Ebene in `telegram_ui.py` via `_process_message()` und `_process_callback_query()` — analog zu `tests/ui/test_photo_times.py`
- Kein Test für die Menü-Registrierung (`set_my_commands`) nötig — das ist ein Telegram-API-Aufruf beim Start
- Zu testen:
  - Neue Tastatur-Button-Texte lösen korrekte Handler aus
  - „📷 Kamera"-Button sendet Inline-Keyboard mit den 3 Buttons
  - „⚙️ Einstellungen"-Button öffnet das erweiterte Untermenü (5 Buttons inkl. Update)
  - `/tagesbericht` ruft denselben Handler auf wie bisher `/report`
  - `/zeitplaene` öffnet direkt die Gieß-Zeitpläne (kein Routing)
  - `/foto` öffnet direkt die Foto-Anzeige
  - Entfernte Befehle (`/add`, `/delete`, `/toggle`, `/photo`, `/report` etc.) lösen „Unbekannter Befehl" aus
  - Callback `phtadd_start` (Fotozeiten-Wizard) erreichbar über Kamera-Untermenü
  - Callback `photoclear_` (Fotos löschen) erreichbar über Kamera-Untermenü
  - Sofort-Nebel: nach Ventil-Wahl zeigt der Flow zuerst die Stoß-Dauer-Auswahl, dann Pause, dann Laufzeit
  - Sofort-Nebel: Nach Laufzeit-Wahl wird `_nebel_ctrl.start(...)` mit den **gewählten** Stoß-/Pause-Werten aufgerufen — nicht mit `config.NEBEL_ON_SECONDS` / `config.NEBEL_PAUSE_MINUTES`
  - Sofort-Nebel: Laufzeit über `NEBEL_MANUAL_MAX_MINUTES` bleibt gedeckelt
  - Bewässern: „🚿 Bewässern" zeigt zuerst die Art-Auswahl (`water_mode_guss`, `nebel_now`)
  - Bewässern/Guss: bei genau einem gekoppelten Ventil entfällt die Ventil-Frage; bei mehreren erscheint die Auswahl (`water_valve_{id}`)
  - Bewässern/Guss: der gewählte `mqtt_name` wird an `_watering_ctrl.start_watering(..., mqtt_name=…)` durchgereicht
  - Bewässern: ohne gekoppeltes Ventil → Hinweis statt Start
  - Stopp: bei 0/1 aktivem Ventil sofort stoppen; bei mehreren aktiven erscheint die Auswahl inkl. „Alle stoppen"
  - Stopp: `stop_valve_{mqtt_name}` stoppt gezielt, `stop_valve_all` ruft `stop_watering()` ohne Argument
  - Zeitplan-Ansicht enthält nach dem Umzug **keine** Sofort-Nebel-Zeile mehr

## Nicht im Leistungsumfang (Out of Scope)

- Inhaltliche Änderungen an den Handler-Funktionen selbst, mit **drei Ausnahmen**: (a) der Sofort-Nebel-Flow wird um Stoß-Dauer- und Pause-Auswahl erweitert; (b) „Bewässern" erhält Art- und Ventil-Auswahl; (c) „Stopp" erhält Ventil-Auswahl bei mehreren aktiven Ventilen. Alle anderen Handler ändern nur Routing und Benennung.
- Umbenennung interner Python-Funktionsnamen (soweit nicht nötig)
- Redesign der Nachrichten-Texte oder Wizard-Dialoge (außer den neuen Sofort-Nebel-Prompts)
- Persistieren des Sofort-Nebel-Takts (bewusst nur pro Lauf)
- Weitere neue Funktionalität über den Sofort-Nebel-Takt hinaus

## Weitere Anmerkungen (Further Notes)

- **Emoji-Semantik (ADR 0029):** `📅` ist für Gieß-Zeitpläne reserviert. Fotozeiten-Button verwendet `⏰`.
- **UI-Ausnahmen in CONTEXT.md:** „Fotos löschen" und „Fotozeiten" sind als _UI-Ausnahme_ in den Domain-Term-Einträgen „Bild-Historie" und „Aufnahme-Zeitpunkt" vermerkt.
- **ADR 0013 (Bestätigungen via Reply-Keyboard):** Bleibt für „Fotos löschen" erhalten — Inline-Button löst Handler aus, der Reply-Keyboard-Bestätigung sendet.
- **Kein Rückwärtskompatibilitäts-Shim:** Alle alten Befehlsnamen werden hart entfernt. Nutzer die `/photo` o.ä. gelernt haben, müssen sich umgewöhnen.
- **Feature 0006 (Multi-Ventil):** Die Ventil-Auswahl in „Bewässern" und „Stopp" liefert faktisch den noch offenen UI-Schritt (Schritt 9) von Feature 0006 mit. Core und DB tragen Multi-Ventil bereits (`start_watering(mqtt_name=…)`, `stop_watering(mqtt_name=…)`, `database.get_all_valves()`); hier wird es nur in der UI sichtbar gemacht. Das „skip bei genau einem Ventil"-Muster ist aus dem Sofort-Nebel übernommen.
- **Neue Controller-Methode:** `WateringController.get_active_valve_names()` (reine Lese-Methode, keine Architektur-Verletzung) für die Stopp-Auswahl.
