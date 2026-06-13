# Feature: Gartenmodell & Aufgaben-System

## Problemstellung (Problem Statement)

Der Bewässerungs-Daemon kennt nur Ventile, Zeitpläne und Wetterdaten – aber nichts über den eigentlichen Garten. Der Benutzer hat keine digitale Möglichkeit, den Aufbau seines Gartens (Beete, Pflanzen) festzuhalten, Erfahrungen und Erntemengen zu protokollieren oder sich an unregelmäßige Aufgaben (z.&nbsp;B. „Zaun streichen", „Hochbeet düngen") erinnern zu lassen. Das Ergebnis: Wissen über den Garten lebt nur im Kopf des Benutzers und geht zwischen Saisons verloren.

## Lösung (Solution)

Der Telegram-Bot wird um ein **Gartenmodell** erweitert: Beete können angelegt und mit Pflanzen bestückt werden. Zu jedem Beet und jeder Pflanze können Erntemengen und Beobachtungen protokolliert werden. Ein flexibles **Aufgaben-System** erlaubt es, datumsgenaue Erinnerungen sowie dauerhafte Nudges zu erstellen, die beim nächsten Öffnen des Bots sichtbar sind. Der Bot entwickelt sich so vom reinen Bewässerungscontroller zum digitalen Zentrum des Gartens.

## User Stories

### Gartenmodell – Beete

1. Als Benutzer des Telegram-Bots möchte ich ein neues Beet anlegen und ihm einen Namen geben (z.&nbsp;B. „Hochbeet 1", „Beet am Zaun"), um meinen Garten strukturiert abzubilden.
2. Als Benutzer möchte ich einem Beet optional ein Ventil zuordnen, damit der Bot weiß, welches Ventil dieses Beet bewässert.
3. Als Benutzer möchte ich alle angelegten Beete in einer Übersicht sehen, um schnell zu einem bestimmten Beet navigieren zu können.
4. Als Benutzer möchte ich ein Beet umbenennen oder löschen können, wenn es nicht mehr existiert oder einen falschen Namen hat.

### Gartenmodell – Pflanzen

5. Als Benutzer möchte ich eine Pflanze in einem Beet eintragen (Name, Sorte, Pflanzdatum), um festzuhalten, was wo wächst.
6. Als Benutzer möchte ich eine Pflanze als „entfernt" markieren (mit Datum), damit die Saisonhistorie erhalten bleibt, ohne dass die Pflanze weiterhin als aktiv erscheint.
7. Als Benutzer möchte ich sehen, welche Pflanzen aktuell in einem bestimmten Beet wachsen.
8. Als Benutzer möchte ich auch vergangene Pflanzen eines Beetes einsehen können, um Erfahrungen aus vorherigen Saisons zu nutzen.

### Ernte- und Beobachtungs-Logbuch

9. Als Benutzer möchte ich eine Ernte zu einer Pflanze protokollieren (Menge, Einheit, optionale Notiz), um am Ende der Saison meinen Gesamtertrag zu kennen.
10. Als Benutzer möchte ich eine freie Beobachtung zu einem Beet oder einer Pflanze eintragen (z.&nbsp;B. „Schädlingsbefall", „Wächst super"), um Erfahrungen für die nächste Saison festzuhalten.
11. Als Benutzer möchte ich alle Ernteeinträge einer Pflanze auf einen Blick sehen, um den Saisonertrag zu beurteilen.
12. Als Benutzer möchte ich alle Beobachtungen zu einem Beet chronologisch lesen, um die Geschichte dieses Beetes nachzuvollziehen.

### Aufgaben-System

13. Als Benutzer möchte ich eine datumsgenaue Aufgabe erstellen (Titel, Fälligkeitsdatum, optionaler Bezug zu einem Beet oder einer Pflanze), damit der Bot mich am jeweiligen Tag per Push-Nachricht erinnert.
14. Als Benutzer möchte ich eine Aufgabe als „Nudge" ohne festes Datum anlegen, die mir beim nächsten Öffnen des Bots als Erinnerung angezeigt wird, solange sie offen ist.
15. Als Benutzer möchte ich eine offene Aufgabe als erledigt markieren, damit sie aus der aktiven Liste verschwindet.
16. Als Benutzer möchte ich alle offenen Aufgaben auf einmal sehen, um einen Überblick über anstehende Arbeiten zu haben.
17. Als Benutzer möchte ich eine Aufgabe mit optionaler Wiederholung (alle N Tage) anlegen, damit regelmäßige Aufgaben (z.&nbsp;B. „Hochbeet düngen alle 14 Tage") automatisch wieder aktiv werden, nachdem ich sie erledigt habe.
18. Als Benutzer möchte ich eine Aufgabe löschen, ohne sie als erledigt zu markieren.

### Tagesbericht & Proaktive Erinnerungen

19. Als Benutzer möchte ich, dass der tägliche Statusbericht (08:00 Uhr) Aufgaben enthält, die heute oder in den nächsten zwei Tagen fällig sind, damit ich meinen Gartentag planen kann.
20. Als Benutzer möchte ich eine Push-Nachricht erhalten, wenn eine datumsgenaue Aufgabe heute fällig ist und noch nicht erledigt wurde.
21. Als Benutzer möchte ich beim Öffnen des Bots (Klick auf Hauptmenü) sehen, ob Nudge-Aufgaben offen sind, ohne dass der Bot mich unaufgefordert anschreibt.

## Implementierungs-Entscheidungen (Implementation Decisions)

### Datenbank-Schema

- Neue Tabelle **`beete`**: `id`, `name`, `description` (nullable), `valve_id` (FK auf `valves`, nullable). Kein `deleted_at` — Beete werden hart gelöscht (Pflanzen kaskadieren).
- Neue Tabelle **`pflanzen`**: `id`, `beet_id` (FK), `name`, `variety` (nullable), `planted_at` (ISO-Datum), `removed_at` (nullable ISO-Datum), `notes` (nullable).
- Neue Tabelle **`ernte_log`**: `id`, `pflanze_id` (FK), `logged_at` (ISO-Zeitstempel), `quantity` (REAL), `unit` (TEXT, z.&nbsp;B. „kg", „Stück"), `notes` (nullable).
- Neue Tabelle **`beobachtungen`**: `id`, `beet_id` (nullable FK), `pflanze_id` (nullable FK), `logged_at` (ISO-Zeitstempel), `text` (TEXT). Mindestens ein FK muss gesetzt sein.
- Neue Tabelle **`aufgaben`**: `id`, `title` (TEXT), `beet_id` (nullable FK), `pflanze_id` (nullable FK), `due_date` (nullable ISO-Datum), `is_nudge` (INTEGER 0/1, default 0), `recurrence_days` (nullable INTEGER), `completed_at` (nullable ISO-Zeitstempel).
- Schema-Migration via bestehenden `try/except OperationalError`-Mechanismus in `init_db()`.

### Architektur

- Alle Datenbankoperationen für das Gartenmodell werden als Funktionen in `database.py` implementiert (konsistent mit bestehenden CRUD-Funktionen).
- Kein neuer Adapter — die gesamte Logik ist reine Datenbankschicht plus UI-Handler.
- Keine neuen Domain-Events erforderlich: Aufgaben-Benachrichtigungen werden vom Scheduler direkt über `telegram_client.broadcast_notification()` versendet, analog zur bestehenden Tagesbericht-Erzeugung. Eine neue Scheduler-Event-Klasse (`TasksDueTriggered`) ist nur dann nötig, falls die Tagesbericht-Logik in `daily_report.py` ausgelagert wird — andernfalls liest der Scheduler direkt die DB.
- Nudge-Aufgaben: Jede Bot-Antwort, die das Hauptmenü-Reply-Keyboard zurückgibt (z.&nbsp;B. nach `/start`, nach Abschluss eines Wizards, nach einem Statusbefehl), prüft `database.get_open_nudge_tasks()` und hängt eine kompakte Liste an, wenn Einträge vorhanden sind. Der Bot schreibt den Benutzer nicht unaufgefordert an.

### Telegram-UX

- Einstiegspunkt: Neuer Hauptmenü-Button **„🌱 Garten"** führt zu einer Beet-Übersicht.
- Navigation: Beet auswählen → Detailansicht (aktive Pflanzen, offene Aufgaben für dieses Beet, letzter Ernteeintrag). Von dort: Pflanze hinzufügen, Ernte/Beobachtung loggen, Aufgabe erstellen.
- Aufgabe erstellen: Wizard (Titel → Bezug optional → Datum oder Nudge → optional Wiederholung). Folgt dem bestehenden Wizard-Muster mit `wizard_states` in `telegram_ui.py`.
- Aufgaben-Übersicht: Button **„📋 Aufgaben"** zeigt alle offenen Aufgaben (fälligkeitssortiert, Nudges zuletzt).
- Erledigte Aufgaben mit `recurrence_days` werden automatisch mit neuem `due_date = today + recurrence_days` neu angelegt.

### Scheduler-Integration

- Der bestehende 08:00-Check in `scheduler.py` wird um einen Aufruf einer neuen Funktion `daily_report.get_due_tasks_section()` erweitert, die Aufgaben der nächsten 48 Stunden als Abschnitt in den Tagesbericht einfügt.
- Zusätzlich: Im Scheduler-Loop wird einmalig pro Tag (analog zum Tagesbericht-Guard) geprüft, ob heute fällige Aufgaben existieren, die noch nicht erledigt sind — falls ja, wird eine separate Push-Nachricht gesendet.

## Test-Entscheidungen (Testing Decisions)

Getestet wird ausschließlich das **externe Verhalten** (Was gibt die Funktion zurück? Welche Nachricht wird gesendet?), nicht die interne Implementierung (keine Assertions auf SQL-Queries oder dict-Strukturen).

### Datenbankfunktionen (`tests/adapters/test_garden_model.py`)

- Referenz-Pattern: bestehende DB-Tests (z.&nbsp;B. für `schedule`-CRUD in `tests/test_irrigation.py`), die eine temporäre SQLite-Datei in `setUpClass` anlegen und in `tearDownClass` löschen.
- Szenarios: Beet anlegen / umbenennen / löschen; Pflanze hinzufügen / entfernen; Ernte loggen und Summe abrufen; Beobachtung speichern; Aufgabe anlegen (mit und ohne Datum, mit Wiederholung); Aufgabe erledigen → Wiederholung prüfen; `get_open_nudge_tasks()` gibt nur unerledigte Nudges zurück; `get_due_tasks(date)` gibt nur Aufgaben zurück, deren `due_date ≤ date`.

### Telegram-UI-Handler (`tests/ui/test_telegram_ui.py`)

- Referenz-Pattern: bestehende Wizard-Tests (Zeitplan-Assistent, Ventil-Kopplung).
- `setUpClass` mockt alle fünf `telegram_client`-Sendefunktionen (ADR-0017-Regel).
- Szenarios: Hauptmenü zeigt Nudge-Aufgaben an, wenn welche vorhanden; Aufgabe-Wizard läuft vollständig durch (Titel → Datum → Speichern); Erledigen einer Aufgabe mit Wiederholung legt neue Aufgabe an; Beet-Detailansicht zeigt aktive Pflanzen und offene Aufgaben.

### Scheduler-Integration (`tests/test_irrigation.py` oder eigene Datei)

- Szenario: Seed einer heute fälligen, unerledigten Aufgabe → Scheduler-Tick auslösen → `broadcast_notification` wird aufgerufen.
- Referenz-Pattern: bestehende Scheduler-Tests im Integration-Test-File.

## Nicht im Leistungsumfang (Out of Scope)

- Foto-Anhänge zu Beobachtungen (Telegram-Foto-Handling ist komplex und ein eigenes Feature).
- Automatischer Saison-Rückblick als separater Bericht (der Benutzer kann Infos manuell über die Beet-Ansicht abrufen).
- KI-gestützte Pflegehinweise oder vordefinierte Pflanzenkataloge mit Standard-Pflegeplänen.
- Integration mit dem Füllstandssensor (separates Feature 0003).
- Inaktivitäts-Watchdog (separates Feature 0004 / Plan 0004).

## Empfohlene Implementierungs-Phasen

Dieses Feature ist in drei unabhängig deploybare Phasen aufgeteilt, die jeweils abgeschlossen und getestet werden, bevor die nächste beginnt:

1. **Phase 1 – Gartenmodell**: Datenbank-Schema (Beete, Pflanzen), CRUD-Funktionen, Beet-Übersicht und Pflanzenverwaltung im Bot (User Stories 1–8).
2. **Phase 2 – Aufgaben-System**: Tabelle `aufgaben`, Wizard, Nudge-Anzeige, Scheduler-Integration (User Stories 13–21).
3. **Phase 3 – Logbuch**: Tabellen `ernte_log` und `beobachtungen`, Ernte- und Beobachtungs-Workflows (User Stories 9–12).

Jede Phase liefert eigenständigen Mehrwert und kann separat committed und deployed werden.

## Weitere Anmerkungen (Further Notes)

- Die Verlinkung eines Beetes mit einem Ventil (`valve_id`) ist optional und hat im ersten Schritt nur informativen Charakter — der Scheduler startet kein Ventil automatisch auf Basis des Gartenmodells. Eine spätere Verknüpfung (z.&nbsp;B. „Bewässere Beet X via Ventil Y") wäre ein separates Feature.
- Die Saison ist kein explizites Konzept in der Datenbank: Pflanzen haben ein `planted_at`- und optionales `removed_at`-Datum; der Benutzer kann die Ansicht nach Jahr filtern lassen (zukünftiges Enhancement).
- Für die Einheit im Ernte-Log (`unit`) wird ein Freitext-Feld verwendet, kein Enum — das hält die Implementierung einfach und vermeidet Lokalisierungsprobleme.
