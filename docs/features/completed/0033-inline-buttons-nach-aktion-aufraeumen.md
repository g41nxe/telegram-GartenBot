# Feature 0033: Inline-Buttons nach Abschluss einer Aktion aufräumen

## Problemstellung (Problem Statement)

Die Aktions-Buttons unter einer Bot-Nachricht (Inline-Keyboard) verschwinden derzeit nur **manchmal**, wenn die Aktion abgeschlossen ist:

- **Bei Erfolg** ersetzt der Handler die Nachricht über `edit_message_text(...)` ohne neues Markup — die Buttons fallen korrekt weg (z. B. „Bewässerung gestartet", „Sofort-Nebel gestartet", Stopp ausgeführt).
- **Bei Abbruch** (`❌ Abbrechen`) und bei **einigen Fehlerpfaden** schickt der Handler stattdessen eine **neue** Nachricht über `send_message(...)` und lässt die ursprüngliche Nachricht unangetastet. Das alte Inline-Keyboard bleibt im Chat stehen und ist **weiter klickbar**.

Dadurch hängen nach einem „❌ Abbrechen" z. B. die Ventil-Auswahl, der Nebel-Takt oder die Schwellenwert-Buttons noch im Verlauf. Ein versehentlicher Druck löst eine bereits abgebrochene Auswahl erneut aus oder erzeugt einen „⌛ Vorgang abgelaufen"-Hinweis — unsauber und irritierend.

## Lösung (Solution)

Jede Inline-getriebene Aktion räumt ihr Keyboard auf, **sobald sie endet — egal ob Erfolg, Abbruch oder Fehler**. Nach dem Abschluss zeigt die ursprüngliche Nachricht ein abschließendes Ergebnis (z. B. „❌ Vorgang abgebrochen.") ohne Buttons. So bleibt im Verlauf nie ein totes, klickbares Keyboard zurück.

Mechanisch wird die ursprüngliche Nachricht (über die bereits vorhandene `message_id` der Callback-Query) bearbeitet statt eine neue Nachricht zu senden — analog zum bereits konsistenten Erfolgspfad.

## User Stories

1. Als Benutzer des Telegram-Bots möchte ich, dass nach einem „❌ Abbrechen" die zugehörigen Auswahl-Buttons verschwinden, damit ich sie nicht versehentlich erneut drücke.
2. Als Benutzer möchte ich, dass nach einem Fehler („❌ Fehler beim Starten …") das Auswahl-Keyboard der fehlgeschlagenen Aktion verschwindet, damit klar ist, dass dieser Vorgang beendet ist.
3. Als Benutzer möchte ich, dass nach erfolgreichem Abschluss (Guss/Nebel gestartet, gestoppt) keine alten Buttons zurückbleiben — wie bisher, aber jetzt durchgängig garantiert.
4. Als Benutzer möchte ich beim Abbruch eines mehrstufigen Flows (Bewässern Art→Ventil→Details, Sofort-Nebel-Takt, Zeitplan-Wizard, Schwellenwert-Editor, Ventil-/Kamera-Kopplung) ein eindeutiges Ende sehen, statt einer neuen Nachricht über einem noch aktiven Keyboard.
5. Als Benutzer möchte ich, dass die abschließende Rückmeldung (z. B. „❌ Vorgang abgebrochen.") an der Stelle des Vorgangs erscheint, damit der Chatverlauf nachvollziehbar bleibt.
6. Als Entwickler möchte ich einen einheitlichen Weg, ein Keyboard zu entfernen, damit künftige Flows (z. B. aktionsfähige Benachrichtigungen, Feature 0018) das Aufräumen ohne Sonderlogik erben.
7. Als Benutzer möchte ich, dass die permanente Haupttastatur (Reply-Keyboard) weiterhin verfügbar bleibt, während nur das aufgaben­bezogene **Inline**-Keyboard verschwindet.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Betroffene Schicht:** ausschließlich `ui/telegram_ui.py` (Callback-Handler) und `ui/telegram_client.py` (neue Hilfsfunktion). Keine Änderung an `core/` oder Adaptern — rein präsentationsseitig. Siehe **ADR 0038**.
- **Universelles Aufräum-Muster (gegrillt):** Die bestehende Bestätigungs-/Ergebnis-Nachricht bleibt **unverändert**; zusätzlich wird `edit_message_reply_markup(chat_id, message_id, None)` auf der **Ursprungsnachricht** aufgerufen — die Buttons verschwinden, der Text bleibt stehen. Kein Umschreiben von Texten, keine Flow-Änderung, nur **ein Zusatz-Call** je Abschlussstelle. (Die Alternative „Prompt-Text via `edit_message_text` ersetzen" wurde verworfen zugunsten des einheitlichen, minimalen Musters.)
- **Neue Telegram-Client-Schnittstelle:** `edit_message_reply_markup(chat_id, message_id, reply_markup=None)` als dünner Wrapper um `editMessageReplyMarkup` (stdlib-HTTP, analog zu `edit_message_text`). Wird **jetzt** gebaut (nicht erst mit Feature 0018) — es ist die zentrale Mechanik.
- **Zu vereinheitlichende Abbruch-Callbacks:** `cancel`, `wiz_cancel`, `man_cancel`, `nebel_cancel`, `setup_cancel`, `update_cancel`, `camsetup_cancel`, `sched_edit_cancel` — je ein Zusatz-Call. `sched_edit_cancel` behält sein `handle_schedules()` (neue Listen-Nachricht) und strippt zusätzlich das alte Bearbeiten-Menü-Keyboard.
- **Zu vereinheitlichende Fehlerpfade:** Der callback-getriebene manuelle Guss-Fehler (`message_id` vorhanden) wird direkt aufgeräumt. Der **getippte** Custom-Mengen-Fehler läuft in `_process_message` ohne Callback-`message_id`; dafür wird die `message_id` des Eingabe-Prompts im Flow-State (`manual_states`) mitgeführt, sodass auch dieser Pfad sein Keyboard entfernt.
- **Erfolgspfade bleiben unverändert**, sind aber Referenz: Sie nutzen bereits `edit_message_text` ohne Markup und gelten als das konsistente Zielmuster.
- **`answer_callback_query`** bleibt für den kurzen Toast erhalten; es entfernt keine Buttons und ist kein Ersatz für das Aufräumen.
- **Haupttastatur (Reply-Keyboard):** Wo nach Abbruch bisher `get_main_keyboard()` mitgeschickt wurde, bleibt die permanente Tastatur erhalten — sie ist ein Reply-Keyboard und vom Inline-Aufräumen unberührt. Falls eine abschließende Bestätigung als eigene Nachricht gewünscht ist, kann sie zusätzlich gesendet werden; entscheidend ist, dass das **Inline**-Keyboard der ursprünglichen Nachricht entfernt wird.

## Test-Entscheidungen (Testing Decisions)

- **Nahtstelle (höchste vorhandene):** Dispatcher-Ebene über `_process_callback_query(...)` mit gemocktem `telegram_client` und `database` — exakt das Muster aus `tests/ui/test_ux_redesign.py` und `tests/ui/test_telegram_ui.py`.
- **Gutes-Test-Kriterium:** Nur das externe Verhalten prüfen — nämlich „die ursprüngliche Nachricht wird editiert / ihr Keyboard entfernt", nicht den genauen Wortlaut interner Hilfsfunktionen. Konkret pro Abbruch-/Fehler-Callback:
  - `telegram_client.edit_message_text` (oder `edit_message_reply_markup`) wird mit der `message_id` der Callback-Query aufgerufen.
  - Das dabei gesetzte `reply_markup` ist leer/`None` (kein Inline-Keyboard mehr).
  - Es wird **keine** neue, das Keyboard duplizierende `send_message` mehr für den Abbruchfall verwendet (bzw. falls eine Bestätigung gesendet wird, trägt sie kein Inline-Keyboard).
- **Abdeckung:** je ein Test pro Abbruch-Callback (`man_cancel`, `nebel_cancel`, `wiz_cancel`, `setup_cancel`, `update_cancel`, `camsetup_cancel`, `sched_edit_cancel`, `cancel`) und für den Guss-Fehlerpfad; plus ein Regressionstest, der für einen Erfolgspfad (z. B. Stopp) belegt, dass das Keyboard weiterhin entfernt wird.
- **Neue Client-Funktion:** falls `edit_message_reply_markup` ergänzt wird, ein schmaler Test analog zu bestehenden `telegram_client`-Tests (`tests/ui/test_telegram_client.py`), der den korrekten Payload/Endpunkt mit gemocktem HTTP belegt.
- **Wiring-Smoke-Test (ADR-Regel 6):** unverändert — keine neuen Wiring-Funktionen.

## Nicht im Leistungsumfang (Out of Scope)

- **Reply-Keyboard-Bestätigungen (ADR 0013):** Die „✅ Ja / ❌ Nein"-Lösch-Rückfragen laufen über ein Reply-Keyboard, nicht über Inline-Buttons; deren Entfernung (`ReplyKeyboardRemove`) ist ein separater Mechanismus und bleibt außen vor.
- **Inhaltliche Neugestaltung der Abschluss-/Fehlertexte** (Ton, Wortlaut) — es geht nur um das Entfernen der Buttons, nicht um neue Botschaften.
- **Aktionsfähige Benachrichtigungen** (Feature 0018) — dieses Feature schafft nur die saubere Grundlage (`edit_message_reply_markup`), implementiert aber keine neuen Button-Aktionen an Broadcast-Nachrichten.
- **Timeout-/TTL-getriebenes Aufräumen** abgelaufener Wizard-Sessions im Hintergrund (ohne Nutzer-Interaktion) — die `message_id` ist dort nicht zur Hand; bleibt eine mögliche spätere Verfeinerung.
- **Prompt-`message_id`-Mitführung über den manuellen Guss-Flow hinaus** — andere getippte Eingabe-Flows (z. B. Wizard-Textschritte) räumen ihr Keyboard weiterhin über den regulären Abbruch-/Callback-Weg auf; eine flächendeckende State-Mitführung für alle getippten Fehlerfälle ist nicht Teil dieses Features.

## Weitere Anmerkungen (Further Notes)

- **Konsistenz mit ADR 0029** (Telegram-Design-System): vorhersehbare, aufgeräumte Interaktionen sind Teil des Zielbilds; dieses Feature schließt eine Lücke zwischen Erfolgs- und Abbruch-/Fehlerpfaden.
- **Ursache historisch:** Die Inkonsistenz ist Alt-Verhalten (vor Feature 0031) — die Abbruch-Handler sendeten seit jeher eine neue Nachricht. Feature 0031 hat das Muster unverändert übernommen; dieses Feature behebt es querschnittlich.
- **`message_id` ist immer vorhanden**, da Abbruch/Fehler hier stets aus einer Callback-Query stammen (Inline-Button) — das Editieren der ursprünglichen Nachricht ist also immer möglich.
- Architektur-konform: keine adapterübergreifenden Importe, keine Core-Änderung; die neue Client-Funktion ist ein zustandsloser Boundary-Wrapper.
