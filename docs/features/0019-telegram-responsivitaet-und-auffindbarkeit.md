# Feature: Telegram-Responsivität & Auffindbarkeit

## Problemstellung (Problem Statement)

Zwei kleine, aber spürbare Schwächen mindern das Bedienerlebnis:

1. **Der Bot wartet schweigend.** `/report` blockiert fest 5 Sekunden, `/status` 1,5 Sekunden, um auf Ventil-Antworten zu warten — ohne jedes Lebenszeichen. Auf dem Handy wirkt das wie „hängt der?". Zudem ist der feste `sleep` eine Wette: mal sind die Ventildaten schon da, mal nicht.
2. **Befehle sind unsichtbar.** Es gibt `/status`, `/report`, `/zeitplan`, `/stop`, `/setup`, `/update` u. a., aber kein gesetztes Telegram-Befehlsmenü. Neue Nutzer (und der Nutzer selbst nach Wochen) sehen die Befehle nur, wenn sie den Code kennen.

## Lösung (Solution)

Drei plattformnahe Verbesserungen, die ausschließlich die Boundary zur Telegram-API betreffen:

1. **Typing-Indikator:** Vor jeder spürbaren Wartezeit sendet der Bot `sendChatAction: typing`, sodass der „tippt…"-Hinweis erscheint.
2. **Warte-auf-Antwort statt Blind-Sleep:** `/status` und `/report` warten aktiv auf die tatsächliche Ventil-Statusmeldung (Event auf dem Ereignis-Kanal) mit einem Timeout als Obergrenze, statt blind eine feste Zeit zu schlafen. Kommt die Antwort früher, geht es früher weiter; bleibt sie aus, greift der Timeout.
3. **Natives Befehlsmenü:** Beim Daemon-Start registriert der Bot seine Befehle via `setMyCommands`, sodass das „/"-Menü im Eingabefeld alle verfügbaren Befehle mit Kurzbeschreibung anzeigt.

## User Stories

1. Als Benutzer möchte ich nach `/status` oder `/report` sofort ein „tippt…"-Signal sehen, damit ich weiß, dass der Bot arbeitet und nicht hängt.
2. Als Benutzer möchte ich Statusantworten so schnell erhalten, wie die Ventildaten tatsächlich eintreffen, statt immer die volle feste Wartezeit abzusitzen.
3. Als Benutzer möchte ich im Telegram-Eingabefeld über das „/"-Menü alle verfügbaren Befehle samt Kurzbeschreibung sehen, damit ich nicht raten oder im Code nachsehen muss.
4. Als Benutzer möchte ich, dass das Befehlsmenü automatisch aktuell ist, ohne dass ich etwas manuell pflegen muss.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Neue Transport-Methoden** in `telegram_client.py`: `send_chat_action(chat_id, action)` und `set_my_commands(commands)`. Beide reine API-Aufrufe, stdlib-only (kein SDK), konsistent mit dem bestehenden Stil.
- **Typing-Indikator** wird in `telegram_ui.py` an den Stellen ausgelöst, an denen heute `sleep` steht (Status, Report). Telegram blendet „tippt…" für ~5 s ein; bei längerem Warten erneut senden.
- **Warte-auf-Antwort:** Die Status-/Report-Handler fordern den Ventilstatus an und warten auf das `ValveStatusReported`-Event (über ein `threading.Event` o. ä.) mit Timeout. Die feste Sleep-Heuristik entfällt. Der Timeout-Wert wird konfigurierbar gemacht (sinnvoller Default, z. B. 3 s für Status, 6 s für Report).
- **Befehlsmenü** wird einmalig beim Start in `main.py` registriert (nach Token-Prüfung). Die Befehlsliste ist eine einzige Quelle der Wahrheit im Code; Beschreibungen folgen dem Design-System (ADR 0029: „du", knapp).
- **Design-System-Konform:** Befehls-Kurzbeschreibungen im Befehlsmenü folgen Ton und Anrede aus ADR 0029.
- **Keine Logikänderung** an Bewässerung, Scheduler oder DB. Reine UI-/Transport-Verbesserung.

## Test-Entscheidungen (Testing Decisions)

- **Test-Nahtstelle (Seam):** `tests/ui/test_telegram_ui.py` und `tests/ui/test_telegram_client.py` mit gemocktem HTTP-Transport bzw. gemocktem `telegram_client`.
- **Typing-Indikator:** Test, dass vor der Statusausgabe `send_chat_action` mit `typing` aufgerufen wird.
- **Warte-auf-Antwort:** Test, dass der Handler bei früher eintreffendem `ValveStatusReported`-Event nicht die volle Zeit wartet, und dass der Timeout greift, wenn keine Antwort kommt (deterministisch über ein gesetztes/ungesetztes Event, ohne reale Wartezeit).
- **Befehlsmenü:** Test, dass `set_my_commands` beim Start mit der erwarteten Befehlsliste aufgerufen wird.
- **Thread-Hygiene:** Etwaige Warte-Primitive dürfen den Prozess nicht am Leben halten (Daemon-Threads / Timeout).
- **Coverage** darf nicht regredieren.

## Nicht im Leistungsumfang (Out of Scope)

- **Aktionsfähige Benachrichtigungen** (Feature 0018) — unabhängig.
- **Inline-„Aktualisieren"-Buttons** unter dem Status — denkbar, aber separat.
- **Mehrsprachige Befehlsbeschreibungen** — nur Deutsch.

## Weitere Anmerkungen (Further Notes)

- Offene Detailfrage für die Planung: konkrete Timeout-Werte für Status/Report und ob sie über `.env` konfigurierbar sein sollen.
- Offene Detailfrage: vollständige, finale Befehlsliste fürs Menü (welche Befehle öffentlich sichtbar sein sollen — z. B. `/update` evtl. nicht).
- Baut auf der ereignisgetriebenen Architektur (ADR 0008) auf; das Warte-auf-Antwort nutzt den bestehenden `ValveStatusReported`-Pfad.
