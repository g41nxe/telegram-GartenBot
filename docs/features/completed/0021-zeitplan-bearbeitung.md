# Feature: Zeitplan-Bearbeitung

## Problemstellung (Problem Statement)

Zeitpläne lassen sich heute nur **anlegen** und **löschen** — nicht ändern. Wer den Abend-Guss von 20:15 auf 20:45 verschieben oder die Wassermenge anpassen will, muss den bestehenden Zeitplan löschen und den vollständigen 6-Schritt-Assistenten neu durchlaufen. Für etwas, das man saisonal oder bei Urlaub gelegentlich justiert, ist das unverhältnismäßig viel Reibung — und fehleranfällig, weil man alle Werte erneut eingeben muss. Die Datenbank unterstützt das Aktualisieren bereits (`update_schedule`), nur die Bedienoberfläche bietet keinen Weg dorthin.

## Lösung (Solution)

Jeder Zeitplan in der Liste erhält einen „✏️ Bearbeiten"-Einstieg. Von dort kann der Benutzer entweder gezielt ein einzelnes Feld ändern (Zeit, Tage, Dauer, Menge, Name) oder den geführten Assistenten mit den vorausgefüllten Werten erneut durchlaufen. Gespeichert wird über die bereits vorhandene `update_schedule`-Funktion. Anlegen und Löschen bleiben unverändert; Bearbeiten ergänzt die fehlende dritte Operation.

## User Stories

1. Als Benutzer möchte ich die Startzeit eines bestehenden Zeitplans ändern können, ohne ihn zu löschen und neu anzulegen.
2. Als Benutzer möchte ich die Wochentage, die Dauer oder die Wassermenge eines Zeitplans anpassen können.
3. Als Benutzer möchte ich beim Bearbeiten die aktuellen Werte sehen, damit ich weiß, was ich ändere.
4. Als Benutzer möchte ich nur das ändern müssen, was sich tatsächlich ändert, statt alle Felder neu einzugeben.
5. Als Benutzer möchte ich eine Bestätigung sehen, welche Werte nach dem Speichern gelten.
6. Als Benutzer möchte ich das Bearbeiten abbrechen können, ohne dass sich etwas ändert.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Einstiegspunkt:** Neuer „✏️ Bearbeiten"-Button pro Zeitplan im Inline-Keyboard der Zeitplan-Liste (`get_schedules_inline_keyboard`), neben dem bestehenden Lösch-Button.
- **Bearbeitungsmodell:** Ein Feld-Auswahl-Menü („Was möchtest du ändern? — ⏰ Zeit · 📅 Tage · ⏳ Dauer · 💧 Menge · ✏️ Name"), das pro Feld die bestehende Eingabe-/Tastatur-Komponente des Anlege-Assistenten wiederverwendet (Stunden-/Minuten-Raster, Dauer-/Mengen-Buttons, Tage-Auswahl). So wird kein neuer Eingabeweg erfunden.
- **Vorbelegung:** Die aktuellen Werte des Zeitplans werden geladen und angezeigt; bei der Tage-Auswahl sind die bisherigen Tage vorausgewählt.
- **Persistenz:** Speichern über die bestehende `database.update_schedule(...)`. Keine Schemaänderung.
- **Zustand:** Der Bearbeitungs-Dialog nutzt das vorhandene `wizard_states`/`_state_*`-Muster mit TTL, analog zum Anlege-Assistenten (inkl. Bereinigung bei Inaktivität).
- **Design-System-Konform:** Alle Texte und Bestätigungen folgen ADR 0029 (Anrede „du", neutrales Register, Überschrift `*✏️ Zeitplan bearbeiten*`). Die Zusammenfassung nach dem Speichern entspricht der Anlege-Bestätigung.
- **Keine Logikänderung** am Scheduler — er liest weiterhin dieselben DB-Felder.

## Test-Entscheidungen (Testing Decisions)

- **Test-Nahtstelle (Seam):** `tests/ui/test_telegram_ui.py` (Wizard-/Callback-Pfade) plus `tests/adapters/test_database.py` für `update_schedule` (sofern noch nicht abgedeckt).
- **Was geprüft wird:** „Bearbeiten" lädt die aktuellen Werte; eine Feldänderung ruft `update_schedule` mit genau den geänderten Werten und unveränderten übrigen auf; Abbrechen verändert nichts; die Tage-Vorauswahl entspricht dem gespeicherten Stand.
- **Referenz-Pflege:** Die neuen Bearbeiten-Nachrichten werden in IST- und SOLL-Referenz nachgezogen (`.claude/rules/telegram_messages.md`).
- **Coverage** darf nicht regredieren; neue UI-Pfade werden abgedeckt.

## Nicht im Leistungsumfang (Out of Scope)

- **Mehrere Zeitpläne gleichzeitig bearbeiten** (Massenänderung).
- **Verschieben/Kopieren** von Zeitplänen.
- **Historie/Undo** von Zeitplan-Änderungen.

## Weitere Anmerkungen (Further Notes)

- Offene Detailfrage für die Planung: feldweises Bearbeiten (gezielt ein Feld) vs. vollständiger Assistent mit Vorbelegung — empfohlen ist feldweises Bearbeiten, weil es genau die Reibung adressiert (nur ändern, was sich ändert). Beides ließe sich kombinieren.
- Schließt die größte funktionale Lücke des Zeitplan-Managements und macht die ohnehin vorhandene `update_schedule`-Fähigkeit endlich zugänglich.
