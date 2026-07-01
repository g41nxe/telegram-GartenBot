# Implementierungsplan: Feature 0033 — Inline-Buttons nach Aktion aufräumen

Referenz: `docs/features/0033-inline-buttons-nach-aktion-aufraeumen.md` · ADR 0038 · ADR 0029
(Design-System)

Betroffen: `src/daemon/ui/telegram_client.py` (neuer Wrapper), `src/daemon/ui/telegram_ui.py`
(Abbruch-/Fehler-Handler), Tests in `tests/ui/test_telegram_client.py` und
`tests/ui/test_telegram_ui.py` (Muster: `tests/ui/test_ux_redesign.py`).

## Schritt 1 — Client-Wrapper `edit_message_reply_markup` (RED → GREEN)

- **RED:** Test in `tests/ui/test_telegram_client.py` (analog zu bestehenden `edit_message_text`-
  Tests) mit gemocktem HTTP: `edit_message_reply_markup(chat_id, message_id, None)` ruft den
  Endpunkt `editMessageReplyMarkup` mit korrektem Payload auf (`chat_id`, `message_id`; bei
  `None` wird kein/leeres `reply_markup` gesendet).
- **GREEN:** Dünner stdlib-HTTP-Wrapper analog zu `edit_message_text`.

## Schritt 2 — Abbruch-Callbacks vereinheitlichen (RED → GREEN)

Nahtstelle: `_process_callback_query` mit gemocktem `telegram_client`/`database`.

- **RED:** je ein Test pro Abbruch-Callback (`cancel`, `wiz_cancel`, `man_cancel`, `nebel_cancel`,
  `setup_cancel`, `update_cancel`, `camsetup_cancel`, `sched_edit_cancel`): nach dem Callback wird
  `edit_message_reply_markup` mit der `message_id` der Callback-Query und **ohne** Inline-Keyboard
  (`None`) aufgerufen. Die bestehende Bestätigungs-`send_message` bleibt (trägt kein
  Inline-Keyboard).
- **GREEN:** in jedem der acht Handler `telegram_client.edit_message_reply_markup(chat_id,
  message_id, None)` ergänzen. `sched_edit_cancel` behält `handle_schedules(chat_id)` und ergänzt
  den Strip.

## Schritt 3 — Callback-getriebener Guss-Fehler (RED → GREEN)

- **RED:** Test, dass der manuelle Guss-Fehler im Callback-Flow (Mengen-**Button**, `message_id`
  vorhanden) das Keyboard der Ursprungsnachricht entfernt.
- **GREEN:** an der Fehlerstelle im Callback-Flow den Strip ergänzen.

## Schritt 4 — Getippter Guss-Fehler via Flow-State-`message_id` (RED → GREEN)

- **RED:** Test des Text-Flows (Custom-Menge getippt, `start_watering` schlägt fehl): das im
  `manual_states` gemerkte Prompt-`message_id` wird zum Entfernen des Keyboards genutzt.
- **GREEN:** beim Zeigen des Custom-Eingabe-Prompts (Callback `man_*_custom`) die `message_id` in
  `manual_states` ablegen; im Text-Flow-Fehlerpfad (`_process_message`) bei gesetztem
  Prompt-`message_id` `edit_message_reply_markup(chat_id, pmid, None)` aufrufen.

## Schritt 5 — Regression Erfolgspfad

- Ein Test, der für einen Erfolgspfad (z. B. Stopp/Guss gestartet) belegt, dass das Keyboard
  weiterhin entfernt wird (Referenzmuster bleibt intakt).

## Schritt 6 — Wiring-Smoke-Test

- Unverändert (keine neuen Wiring-Funktionen); bestehender Smoke-Test muss grün bleiben.

## Schritt 7 — Doku

- `docs/design/telegram-nachrichten.html`: kurze Notiz an den betroffenen Abbruch-/Fehler-Karten,
  dass das Inline-Keyboard der Ursprungsnachricht beim Ende entfernt wird (Regel
  `telegram_messages.md`). Nachrichtentexte ändern sich nicht.

## Schritt 8 — Coverage & Abschluss

- `.\scripts\run_coverage.ps1` — Coverage darf nicht regredieren.

## Definition of Done

- [ ] `edit_message_reply_markup` im `telegram_client` + Test
- [ ] Alle 8 Abbruch-Callbacks entfernen das Inline-Keyboard der Ursprungsnachricht
- [ ] Callback- **und** getippter Guss-Fehler räumen auf (Text-Flow via Flow-State-`message_id`)
- [ ] Erfolgspfad-Regression grün; Haupttastatur bleibt erhalten
- [ ] Alle Tests grün (bestehende + neue), Coverage nicht regriert
- [ ] `telegram-nachrichten.html` aktualisiert
- [ ] Beads-Issue geschlossen
- [ ] Feature- und Plan-Dokument nach `completed/` verschoben
