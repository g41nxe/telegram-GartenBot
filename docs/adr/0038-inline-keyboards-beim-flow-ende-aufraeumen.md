# 38. Inline-Keyboards beim Flow-Ende einheitlich aufräumen

Jeder Inline-getriebene Flow entfernt sein Keyboard, sobald er endet — bei Erfolg, Abbruch
**und** Fehler. Umgesetzt über einen einheitlichen Aufräum-Aufruf auf der auslösenden Nachricht.

## Kontext

Erfolgspfade räumten bereits auf (`edit_message_text` ohne Markup ersetzt die Nachricht). Die
Abbruch-Callbacks und einige Fehlerpfade sendeten stattdessen eine **neue** Nachricht und ließen
das ursprüngliche Inline-Keyboard stehen — es blieb klickbar. Ein versehentlicher Druck auf ein
solches totes Keyboard löste einen bereits beendeten Vorgang erneut aus oder erzeugte einen
„⌛ abgelaufen"-Hinweis. Die Inkonsistenz ist Alt-Verhalten (vor Feature 0031).

## Entscheidung

- **Neuer Client-Wrapper `edit_message_reply_markup(chat_id, message_id, reply_markup=None)`** um
  Telegrams `editMessageReplyMarkup` (stdlib-HTTP, analog zu `edit_message_text`). Wird **jetzt**
  gebaut (nicht erst mit Feature 0018).
- **Universelles Muster:** Die bestehende Bestätigungs-/Ergebnis-Nachricht bleibt unverändert;
  **zusätzlich** wird `edit_message_reply_markup(chat_id, message_id, None)` auf der
  Ursprungsnachricht aufgerufen — die Buttons verschwinden, der Text bleibt stehen. Kein
  Umschreiben von Texten, keine Flow-Änderung, nur ein Zusatz-Call je Abschlussstelle.
- **Geltungsbereich:** alle acht Abbruch-Callbacks (`cancel`, `wiz_cancel`, `man_cancel`,
  `nebel_cancel`, `setup_cancel`, `update_cancel`, `camsetup_cancel`, `sched_edit_cancel`) sowie
  die callback-getriebenen Fehlerpfade. `sched_edit_cancel` behält sein `handle_schedules()`
  (neue Listen-Nachricht) und strippt zusätzlich das alte Bearbeiten-Menü-Keyboard.
- **Getippte Eingabe-Fehler ohne Callback-`message_id`:** Die `message_id` des Eingabe-Prompts
  wird im Flow-State mitgeführt, damit auch dieser Pfad (manueller Guss mit getippter Menge)
  sein Keyboard aufräumen kann.
- **Haupttastatur (Reply-Keyboard) bleibt unberührt** — sie ist permanent und muss nicht erneut
  gesendet werden; das Aufräumen betrifft ausschließlich das aufgabenbezogene **Inline**-Keyboard.

## Konsequenzen

- Künftige Inline-Flows (z. B. Feature 0018, aktionsfähige Benachrichtigungen) erben die Mechanik
  über `edit_message_reply_markup` ohne Sonderlogik.
- Rein präsentationsseitig: nur `ui/telegram_ui.py` und `ui/telegram_client.py`; keine Core- oder
  Adapter-Änderung. Ergänzt ADR 0029 (Telegram-Design-System) um diese Interaktionsregel.
- Reply-Keyboard-Bestätigungen (ADR 0013, „✅ Ja / ❌ Nein") bleiben außen vor — sie nutzen
  `ReplyKeyboardRemove`, einen anderen Mechanismus.
