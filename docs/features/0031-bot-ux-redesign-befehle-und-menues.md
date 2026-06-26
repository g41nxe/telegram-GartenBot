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
- Neuer ADR 0033 dokumentiert die Gesamtentscheidung zur Bot-Navigation

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

## Nicht im Leistungsumfang (Out of Scope)

- Inhaltliche Änderungen an den Handler-Funktionen selbst (nur Routing und Benennung ändern sich)
- Umbenennung interner Python-Funktionsnamen (soweit nicht nötig)
- Redesign der Nachrichten-Texte oder Wizard-Dialoge
- Neue Funktionalität

## Weitere Anmerkungen (Further Notes)

- **Emoji-Semantik (ADR 0029):** `📅` ist für Gieß-Zeitpläne reserviert. Fotozeiten-Button verwendet `⏰`.
- **UI-Ausnahmen in CONTEXT.md:** „Fotos löschen" und „Fotozeiten" sind als _UI-Ausnahme_ in den Domain-Term-Einträgen „Bild-Historie" und „Aufnahme-Zeitpunkt" vermerkt.
- **ADR 0013 (Bestätigungen via Reply-Keyboard):** Bleibt für „Fotos löschen" erhalten — Inline-Button löst Handler aus, der Reply-Keyboard-Bestätigung sendet.
- **Kein Rückwärtskompatibilitäts-Shim:** Alle alten Befehlsnamen werden hart entfernt. Nutzer die `/photo` o.ä. gelernt haben, müssen sich umgewöhnen.
