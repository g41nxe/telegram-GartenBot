# 13. Telegram-Bestätigungen über Reply-Keyboards

Wir legen fest, dass alle Benutzerbestätigungen im Telegram-Bot einheitlich über Reply-Keyboards (am unteren Bildschirmrand) statt über Inline-Keyboards (direkt unter Nachrichten) abgewickelt werden.

## Kontext

Der Telegram-Bot bietet verschiedene Aktionen, die potenziell destruktiv sind oder eine explizite Freigabe erfordern (z. B. das Löschen eines Zeitplans, das Speichern eines neu erstellten Zeitplans oder das Überschreiben einer bestehenden Ventil-Kopplung).

Bisher wurden Bestätigungen uneinheitlich implementiert (teilweise als Inline-Keyboards direkt unter der Nachricht). Dies birgt folgende Nachteile:
1. **Fehlklicks**: Inline-Buttons auf Mobilgeräten liegen oft nah beieinander und sind kleiner als Tastaturknöpfe.
2. **Historien-Flickering**: Alte Inline-Buttons in älteren Chat-Nachrichten bleiben klickbar, es sei denn, sie werden aufwendig wegeditiert. Das kann zu fehlerhaften Zuständen führen, wenn der Benutzer einen alten Bestätigungsknopf drückt.
3. **Inkonsistentes Benutzererlebnis (UX)**: Bestätigungsdialoge sollten sich visuell klar von regulären Informationsnachrichten abheben.

## Entscheidung

Wir führen eine systemweite UX-Richtlinie ein: **Alle Bestätigungsabfragen (Confirmations) müssen über Reply-Keyboards realisiert werden.**

Dazu gehören:
1. **Löschen von Zeitplänen:** Nach Klick auf den Löschen-Button (`🗑️`) wird eine Bestätigungsmeldung gesendet. Das Tastaturmenü unten wird durch `[ ✅ Ja, löschen ]` und `[ ❌ Nein, abbrechen ]` ersetzt.
2. **Wizard-Speichervorgang:** Am Ende des Zeitplan-Assistenten wird die finale Zusammenfassung mit einer Reply-Tastatur `[ ✅ Speichern ]` und `[ ❌ Abbrechen ]` bestätigt.
3. **Neu-Kopplung (Setup):** Wird `/setup` aufgerufen, obwohl bereits ein Ventil gekoppelt ist, fordert der Bot die Bestätigung via `[ ✅ Ja, neu koppeln ]` und `[ ❌ Abbrechen ]` an.

Sobald der Benutzer eine Option wählt (oder den Vorgang abbricht), wird die Reply-Tastatur wieder durch das permanente Hauptmenü-Keyboard (`get_main_keyboard()`) ersetzt.

## Konsequenzen

- **Höhere Bediensicherheit:** Durch die Platzierung am unteren Bildschirmrand als große, eindeutige Schaltflächen werden Fehlklicks drastisch reduziert.
- **Saubere Chat-Historie:** Es verbleiben keine aktiven Inline-Bestätigungsknöpfe in älteren Chatnachrichten, was die Robustheit des Daemons erhöht.
- **Zustandsverwaltung:** Der Daemon muss für laufende Bestätigungen Sitzungszustände (wie `delete_states` für Löschungen) vorhalten, um eingehende Textnachrichten korrekt dem jeweiligen Vorgang zuordnen zu können.
