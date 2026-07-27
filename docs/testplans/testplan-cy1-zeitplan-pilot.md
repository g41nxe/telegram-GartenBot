# Testplan — cy1 Zeitplan-Assistent (Live-Migration)

**Wann:** nachdem der Zeitplan-Wizard in `telegram_ui` auf `ScheduleAssistent` umgestellt ist.
**Ziel:** Verhaltens-**Parität** mit dem alten Wizard + der ADR-0039-Fix (eine lebende Prompt-Nachricht) am echten Bot verifizieren. Der Kern ist bereits unit-getestet (13 Tests); diese Session prüft das Rendering, die Eingabe-Normalisierung und die DB-Schreibung, die Unit-Tests nicht abdecken.

## A · Happy-Path (Wässern) — ein Zeitplan von Anfang bis Ende
- [ ] „📅 Zeitpläne" → „➕ Anlegen" → Modus-Frage erscheint (Wässern / Nebel).
- [ ] „🚿 Wässern" → **Name-Prompt** erscheint, genau **ein** aktives Keyboard (❌ Abbrechen).
- [ ] Name tippen (`Rasen`) → Stunde-Prompt; die getippte Nachricht bleibt sichtbar, das alte Prompt-Keyboard ist **abgeräumt**.
- [ ] Stunde `14` → Minute-Prompt → Minute `30` → Dauer-Prompt.
- [ ] Dauer `10` → Menge-Prompt → Menge `25` → (Ventil-/) Tage-Prompt.
- [ ] Tage: `Mo` antippen, dann „✅ Weiter" → **Bestätigung** mit korrekter Zusammenfassung (14:30, 10 Min, 25 l, Mo).
- [ ] „✅ Speichern" → „Zeitplan 'Rasen' erfolgreich angelegt". In „📅 Zeitpläne" (oder per SSH `sqlite3 … "SELECT * FROM schedules"`) steht der Zeitplan mit **exakt** diesen Werten.

## B · ADR-0039 — lebende Prompt-Nachricht (der eigentliche Fix)
- [ ] **Custom-Dauer:** Dauer → „✏️ Andere" → Zahl tippen (`12`). Danach existiert **nur ein** aktives Keyboard (Menge). Das alte Custom-Eingabe-Keyboard ist **weg** — *nicht* zwei lebende Keyboards (der alte Bug).
- [ ] **Custom-Menge:** analog mit `40`.
- [ ] Zu keinem Zeitpunkt sind zwei antippbare Inline-Keyboards gleichzeitig aktiv.

## C · Validierung (Parität, ADR 0039: kein Schritt-Wechsel)
- [ ] Leerer Name → Fehlermeldung, **bleibt** im Name-Schritt.
- [ ] Custom-Dauer außerhalb 1–25 (`99`) → Fehler, bleibt im Schritt.
- [ ] Custom-Dauer **Unsinn** (`abc`) → Fehler „Ungültige Eingabe" (kein Crash!) — der Review-Fix.
- [ ] Custom-Menge `0` bzw. `13,5` → Fehler, bleibt im Schritt.
- [ ] Tage leer + „✅ Weiter" → Alarm „Wähle mindestens einen Tag", bleibt bei den Tagen.

## D · Verzweigungen
- [ ] **Ein Ventil** gekoppelt → Ventil-Schritt wird **übersprungen** (direkt zu Tagen), Zeitplan bekommt trotzdem das Ventil.
- [ ] **Mehrere Ventile** → Ventil-Auswahl erscheint, gewähltes Ventil landet im Zeitplan.
- [ ] „🗓 Täglich" hebt einzelne Tage auf und umgekehrt (gegenseitig exklusiv).

## E · Abbrechen
- [ ] „❌ Abbrechen" an **jedem** Schritt → „Vorgang abgebrochen", Wizard-Zustand weg (kein Geister-Keyboard).
- [ ] Während des Wizards einen `/`-Befehl oder Menü-Button tippen → Wizard bricht still ab, Befehl wird normal ausgeführt.

## F · Regression — was NICHT kaputt gehen darf
- [ ] **Nebel-Wizard** („🌫️ Nebel") läuft **unverändert** über den alten Pfad (noch nicht migriert) — anlegen bis speichern funktioniert.
- [ ] Bestehende Zeitpläne bleiben lauffähig; ein geplanter Guss feuert wie gehabt.
- [ ] `/status`, Tagesbericht, andere Wizards (Kopplung, manueller Guss) unbeeinflusst.
- [ ] `journalctl` beim Anlegen ohne `Traceback`/`Error`.

## Abbruch-Kriterien
- Zwei gleichzeitig aktive Keyboards, ein Crash bei getippter Eingabe, ein Zeitplan mit falschen Werten, oder ein gebrochener Nebel-Wizard → **nicht mergen/releasen**, zurück zum Kern.

## Nach erfolgreicher Session
- [ ] Zeitplan-Wizard-Migration abhaken; **dann** die restlichen Wizards (Nebel, Kopplung, manueller Guss) + Router-Tabelle nachziehen (jeder mit eigener Runde).
