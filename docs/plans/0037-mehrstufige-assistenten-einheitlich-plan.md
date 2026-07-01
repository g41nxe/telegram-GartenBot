# Implementierungsplan: Feature 0037 — Mehrstufige Assistenten vereinheitlichen

Referenz: `docs/features/0037-mehrstufige-assistenten-einheitlich.md` · ADR 0039 · ADR 0038

Betroffen: `src/daemon/ui/telegram_client.py` (`send_message` → id), `src/daemon/ui/telegram_ui.py`
(`show_step` + Umstellung der Assistenten-Schritte), Tests in `tests/ui/test_telegram_client.py`
und `tests/ui/test_ux_redesign.py`.

## Schritt 1 — `send_message` gibt die `message_id` zurück (RED → GREEN)

- **RED:** Test in `tests/ui/test_telegram_client.py`: bei 200 gibt `send_message` die
  `result.message_id` aus der Telegram-Antwort zurück; bei Fehler/ohne Token `None`.
- **GREEN:** Antwort-JSON parsen und `result.message_id` zurückgeben. Rückwärtskompatibel — die
  vielen bestehenden Aufrufer ignorieren den Rückgabewert.

## Schritt 2 — Renderer `show_step` (RED → GREEN)

- **RED:** Dispatcher-nahe Tests für beide Zweige:
  - Button-Fall (`message_id` gesetzt): `edit_message_text` wird aufgerufen; `state['prompt_msg_id']`
    == message_id; kein Strip.
  - Getippt-Fall (`message_id=None`, `state['prompt_msg_id']` vorhanden): altes Keyboard wird via
    `edit_message_reply_markup(chat_id, alt, None)` abgeräumt, `send_message` gesendet,
    `state['prompt_msg_id']` == neue id.
- **GREEN:** `show_step(chat_id, state, text, keyboard=None, *, message_id=None)` gemäß ADR 0039.

## Schritt 3 — Zeitplan-Wizard umstellen (Referenz) (RED → GREEN)

- **RED:** Durchlauf-Test des Zeitplan-Wizards (`wiz_start` → Modus → Name **getippt** → Stunde →
  … → Tage): nach dem getippten Namens-Übergang ist das Namens-Prompt-Keyboard entfernt; genau eine
  lebende Prompt-Nachricht; getippte Eingabe nicht gelöscht.
- **GREEN:** Alle Schritt-Renderings des Zeitplan-/Nebel-Wizards auf `show_step` umstellen
  (Button-Schritte mit `message_id`, getippter Namens-/Custom-Schritt ohne). `prompt_msg_id` beim
  ersten Prompt setzen.

## Schritt 4 — Übrige Flows umstellen (je RED → GREEN)

Je Flow ein Durchlauf-Test + Umstellung auf `show_step`:
- **Nebel-Wizard** (falls nicht schon mit Schritt 3 abgedeckt).
- **Kamera-Kopplung** (Name/Intervall getippt, Auflösung/Qualität Buttons).
- **Ventil-Kopplung** (Name getippt).
- **Manueller Guss** (Ventil/Dauer/Menge; Custom-Dauer/-Menge getippt) — den in Feature 0033
  eingeführten `prompt_message_id`-Sonderfall auf `show_step`/`prompt_msg_id` vereinheitlichen.

## Schritt 5 — Validierungsfehler nicht als Schritt-Wechsel

- Sicherstellen, dass Eingabe-Validierungsfehler (leerer Name, Zahl außerhalb Bereich) **re-prompten**
  und das aktive Keyboard **stehen lassen** (kein `show_step`-Übergang). Test je Flow-Beispiel.

## Schritt 6 — Regression & Aufräumen

- Bestehende Wizard-/UX-Tests und die Feature-0033-Abbruch-Tests bleiben grün.
- Doppelte Prompt-`message_id`-Logik aus 0033 (manueller Guss) auf die neue `prompt_msg_id`-
  Konvention konsolidieren (kein zweiter State-Schlüssel).

## Schritt 7 — Doku

- `docs/design/telegram-nachrichten.html`: Notiz, dass Assistenten über eine lebende
  Prompt-Nachricht laufen (Regel `telegram_messages.md`; Nachrichtentexte unverändert).

## Schritt 8 — Coverage & Abschluss

- `.\scripts\run_coverage.ps1` — Coverage darf nicht regredieren.

## Definition of Done

- [ ] `send_message` gibt die `message_id` zurück (+ Test)
- [ ] `show_step`-Renderer mit Invariante (+ Tests für beide Zweige)
- [ ] Alle Flows (Zeitplan, Nebel, Kamera-Kopplung, Ventil-Kopplung, manueller Guss) auf `show_step`
- [ ] Getippte Übergänge räumen das alte Keyboard ab; genau eine lebende Prompt-Nachricht je Flow
- [ ] Validierungsfehler lassen das aktive Keyboard stehen
- [ ] 0033-Sonderlogik (Guss-`prompt_message_id`) konsolidiert
- [ ] Alle Tests grün, Coverage nicht regriert
- [ ] `telegram-nachrichten.html` aktualisiert
- [ ] Beads-Issue geschlossen
- [ ] Feature- und Plan-Dokument nach `completed/` verschoben
