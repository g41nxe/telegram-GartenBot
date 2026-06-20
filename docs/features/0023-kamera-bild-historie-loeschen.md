# Feature: Bild-Historie einer Garten-Kamera löschen

## Problemstellung (Problem Statement)

Die Steuerzentrale sammelt die Bild-Historie jeder Garten-Kamera dauerhaft im Dateisystem an. Der automatische Cleanup dünnt die Historie zwar altersbasiert aus (behält pro Tag ein Zeitraffer-Bild), aber der Nutzer hat keine Möglichkeit, die Bild-Historie einer Garten-Kamera bewusst und sofort komplett zu leeren — etwa nach einer fehlerhaften Aufnahmeserie, einem Standortwechsel der Garten-Kamera oder um Speicherplatz auf der Steuerzentrale freizugeben. Heute bliebe nur der manuelle Eingriff auf dem Dateisystem der Steuerzentrale.

## Lösung (Solution)

Ein neuer Telegram-Befehl löscht auf Wunsch die gesamte Bild-Historie einer ausgewählten Garten-Kamera. Bei mehreren gekoppelten Garten-Kameras wählt der Nutzer zunächst die betroffene Kamera; bei nur einer geht es direkt weiter. Vor dem unwiderruflichen Löschen erscheint eine Ja/Nein-Rückfrage, die die Anzahl der betroffenen Bilder nennt. Nach Bestätigung werden alle gespeicherten Bilder der Garten-Kamera entfernt (einschließlich des aktuellsten Bildes); die Steuerzentrale meldet die Anzahl der gelöschten Bilder. Der Befehl ist bewusst nur als Slash-Befehl verfügbar und nicht als Menü-Button, damit er nicht versehentlich ausgelöst wird.

## User Stories

1. Als Nutzer des Telegram-Bots möchte ich die komplette Bild-Historie einer Garten-Kamera löschen können, um Speicherplatz auf der Steuerzentrale freizugeben.
2. Als Nutzer möchte ich vor dem Löschen sehen, wie viele Bilder betroffen sind, um die Tragweite der Aktion einzuschätzen.
3. Als Nutzer möchte ich eine ausdrückliche Ja/Nein-Rückfrage erhalten, um nicht versehentlich eine ganze Bild-Historie zu verlieren.
4. Als Nutzer mit mehreren Garten-Kameras möchte ich auswählen, welche Kamera geleert wird, um nicht versehentlich die falsche zu treffen.
5. Als Nutzer mit nur einer Garten-Kamera möchte ich direkt zur Rückfrage gelangen, ohne überflüssigen Auswahlschritt.
6. Als Nutzer möchte ich nach dem Löschen eine Bestätigung mit der Anzahl gelöschter Bilder sehen, um sicher zu sein, dass die Aktion erfolgreich war.
7. Als Nutzer möchte ich den Vorgang abbrechen können, ohne dass etwas gelöscht wird.
8. Als Nutzer möchte ich einen klaren Hinweis erhalten, wenn für die gewählte Garten-Kamera gar keine Bilder vorhanden sind, statt einer leeren Rückfrage.
9. Als Nutzer möchte ich einen klaren Hinweis erhalten, wenn überhaupt keine Garten-Kamera gekoppelt ist.
10. Als Nutzer möchte ich, dass der Befehl nicht prominent als Menü-Button erscheint, damit ich ihn im Alltag nicht versehentlich antippe.
11. Als Betreiber möchte ich, dass nur autorisierte Nutzer (bestehende Whitelist) den Befehl auslösen können, damit Fremde keine Bild-Historie löschen.
12. Als Betreiber möchte ich, dass der Befehl auch bei fehlendem Kamera-Verzeichnis robust bleibt und nicht abstürzt.
13. Als Nutzer möchte ich, dass das Löschen die Kamera-Kopplung und die Kamera-Einstellungen unberührt lässt, damit die Garten-Kamera danach normal weiterläuft.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Neuer Telegram-Befehl** (Arbeitsname `/camera_clear`; Alternative `/camera_delete` — finaler Name vor Implementierung mit dem Nutzer abstimmen), eingereiht in die bestehende `/camera_*`-Befehlsfamilie. **Kein** Menü-Button, da destruktiv.
- **Auswahl- und Bestätigungsfluss:**
  - Keine Garten-Kamera gekoppelt → Hinweis-Nachricht, Abbruch.
  - Genau eine Garten-Kamera → direkt zur Lösch-Rückfrage.
  - Mehrere Garten-Kameras → Inline-Tastatur zur Auswahl der betroffenen Kamera (gleiches Muster wie die bestehende Bild-Anzeige).
  - Anschließend Ja/Nein-Rückfrage mit Anzahl der betroffenen Bilder via Inline-Tastatur. Bestätigung löscht, Abbruch lässt alles unverändert.
  - Sind null Bilder vorhanden → Hinweis statt Rückfrage.
- **Löschfunktion:** eine neue Funktion in der Scheduler-Fassade, als Geschwister des bestehenden automatischen Cleanups. Sie leert das Bild-Verzeichnis einer Garten-Kamera (alle gespeicherten Bilder **einschließlich** des aktuellsten Bildes), lässt das nun leere Verzeichnis bestehen (das nächste empfangene Bild legt es ohnehin neu an) und gibt die Anzahl gelöschter Bilder zurück. Sie ist robust gegen ein fehlendes Verzeichnis (Rückgabe 0).
- **Adressierung:** Der Bezug Garten-Kamera → Verzeichnis erfolgt über den Wunschnamen; die Liste der Garten-Kameras stammt aus der Datenbank.
- **Keine Datenbank-Änderung:** Die Bild-Historie hat keine eigenen Datenbank-Einträge; Kopplung, `last_seen` und Kamera-Einstellungen bleiben unberührt.
- **Architektur:** Das Dateisystem-I/O verbleibt in der Scheduler-Fassade, wo bereits der automatische Cleanup liegt — keine neue Adapter-zu-Adapter-Kopplung und kein Verstoß gegen die „stateless adapters"-Regel. Die Telegram-UI ruft die Funktion direkt auf (analog dazu, wie die Bild-Anzeige direkt auf das aktuellste Bild im Verzeichnis zugreift). Ein Ereignis-Kanal ist nicht nötig, da es sich um eine direkte, nutzerausgelöste Aktion handelt und nicht um einen Querschnitts-Seiteneffekt.
- **Nachrichten nach Telegram-Design-System (ADR 0029):** durchgängig „du", Legacy-Markdown (`*fett*`, `_kursiv_`), ein Emoji im Titel. Neue benutzersichtbare Nachrichten: Kamera-Auswahl, Lösch-Rückfrage mit Anzahl, Erfolgsmeldung, Abbruch, „keine Bilder vorhanden", „keine Garten-Kamera gekoppelt". Alle neuen Nachrichten werden im selben Arbeitsschritt in `docs/design/telegram-nachrichten.html` ergänzt (Pflege-Regel) und müssen `telegram-design-system.html` entsprechen.

## Test-Entscheidungen (Testing Decisions)

- **Gute Tests** prüfen nur das beobachtbare externe Verhalten — welche Bilder nach dem Aufruf noch existieren, welcher Zahlenwert zurückkommt und welche Nachrichten/Callback-Ergebnisse die UI erzeugt — nicht interne Implementierungsdetails.
- **Höchste bestehende Nahtstelle für die Löschlogik:** direkter Aufruf der neuen Scheduler-Funktion mit einem temporären Verzeichnis (`tmp_path`) und gesetztem Bild-Verzeichnis, exakt nach dem Muster von `tests/core/test_camera_cleanup.py`. Abgedeckte Fälle:
  - Alle gespeicherten Bilder einer Garten-Kamera (inkl. aktuellstem Bild) werden gelöscht.
  - Der Rückgabewert entspricht der Anzahl gelöschter Bilder.
  - Ein fehlendes Verzeichnis liefert 0 ohne Fehler.
  - Bilder anderer Garten-Kameras bleiben unberührt.
- **UI-/Callback-Fluss:** an der bestehenden UI-Test-Nahtstelle nach dem Muster von `tests/ui/test_camera_wizard.py`:
  - Bestätigung (Ja) ruft die Löschung auf und meldet die Anzahl.
  - Abbruch löscht nichts.
  - Bei mehreren Garten-Kameras wird die Auswahl korrekt aufgelöst.
  - Sonderfälle „keine Garten-Kamera" und „keine Bilder" erzeugen die jeweilige Hinweis-Nachricht.
- **Coverage:** Die Gesamt-Coverage darf nicht sinken; die neue Löschfunktion und der neue Befehlszweig sind vollständig durch Tests abgedeckt (TDD: Test zuerst).

## Nicht im Leistungsumfang (Out of Scope)

- Altersbasiertes oder selektives Löschen (Zeitraum, „älter als X Tage") — Altersregeln deckt der bestehende automatische Cleanup ab.
- Das Leeren **aller** Garten-Kameras in einem Schritt.
- Ein Menü-Button für den Befehl.
- Das Löschen einzelner Bilder.
- Änderungen an der Kamera-Kopplung, den Kamera-Einstellungen oder am Datenbankschema.
- Auswirkungen auf bereits erzeugte Zeitraffer-GIFs — der Befehl leert ausschließlich die Einzelbild-Historie.

## Weitere Anmerkungen (Further Notes)

- **Wechselwirkung mit dem Zeitraffer-GIF / Bild-Puffer:** Das Leeren der Bild-Historie entfernt Rohmaterial, das sonst in ein Zeitraffer-GIF einfließen würde. Vor der Implementierung ist zu prüfen, wo Bild-Puffer und bereits erzeugte GIFs liegen, damit der Befehl gezielt nur die Einzelbild-Historie der gewählten Garten-Kamera trifft und keine separat abgelegten GIFs löscht.
- **Befehlsname** final mit dem Nutzer abstimmen (`/camera_clear` vs. `/camera_delete`).
- Der bestehende automatische Cleanup verschont heute das aktuellste Bild; dieser Befehl löscht es bewusst mit, weil die Garten-Kamera bei der nächsten Aufnahme ohnehin ein neues aktuellstes Bild liefert.
