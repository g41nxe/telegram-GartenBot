# Implementierungsplan: Feature 0037 — Mehrstufige Assistenten vereinheitlichen

Referenz: `docs/features/0037-mehrstufige-assistenten-einheitlich.md` · ADR 0039 · ADR 0038

Betroffen: `src/daemon/ui/telegram_client.py` (neue `send_message_id`), `src/daemon/ui/telegram_ui.py`
(`show_step` + Assistenten-Schritte), Tests in `tests/ui/test_telegram_client.py` und
`tests/ui/test_ux_redesign.py`.

**Struktur nach kritischem Review:** `send_message` bleibt unangetastet (Contract `-> bool`,
Chunk-Splitting, Markdown-Fallback, bestehende Tests). Der sichtbare Bug (Leftover-Keyboards) sitzt
**nur** in den getippten Übergängen — der wird zuerst behoben (Schritte 1–5). Die reine Konvergenz
der bereits sauberen **Button-Ketten** auf `show_step` folgt **danach** (Schritt 6) und ist jederzeit
abbrechbar, ohne den Fix zu gefährden.

## Schritt 1 — `send_message_id` (RED → GREEN)

- **RED:** Test in `tests/ui/test_telegram_client.py`: bei 200 gibt `send_message_id` die
  `result.message_id` aus dem geparsten Antwort-Body zurück; ohne Token / bei Fehler `None`.
  Mock liefert einen JSON-Body (`{"ok":true,"result":{"message_id":123}}`).
- **GREEN:** Dünne, eigenständige Funktion (Wizard-Prompts sind kurz → kein Chunking nötig);
  Markdown→Klartext-Fallback wie `_send_chunk`. **`send_message` und seine Tests bleiben unberührt.**

## Schritt 2 — Renderer `show_step` (RED → GREEN)

- **RED:** Tests beider Zweige:
  - Button (`message_id` gesetzt): `edit_message_text` aufgerufen; `state['prompt_msg_id']` ==
    message_id; kein Strip.
  - Getippt (`message_id=None`, altes `prompt_msg_id` vorhanden): altes Keyboard via
    `edit_message_reply_markup(chat_id, alt, None)` abgeräumt; `send_message_id` gesendet;
    `state['prompt_msg_id']` == neue id.
  - Getippt ohne vorheriges `prompt_msg_id` (Entry-Prompt): kein Strip, id wird gemerkt.
- **GREEN:** `show_step(chat_id, state, text, keyboard=None, *, message_id=None)` gemäß ADR 0039.

## Schritt 3 — Bug-Fix: getippte Übergänge + Entry-Prompts (RED → GREEN)

Nur die Stellen anfassen, die den sichtbaren Bug erzeugen — **je Flow ein Durchlauf-Test**, der
belegt: nach dem getippten Übergang ist das vorige Prompt-Keyboard entfernt (genau eine lebende
Prompt-Nachricht).
- **Zeitplan-Wizard** (Referenz): Name-getippt-Übergang + Custom-Dauer/-Menge über `show_step`.
- **Nebel-Wizard:** analog.
- **Kamera-Kopplung:** Entry-Prompt (Name) via `send_message_id`/`show_step`; getippte Schritte
  (Name, Intervall).
- **Ventil-Kopplung:** Entry-Prompt (Name).
- **Manueller Guss:** Custom-Dauer/-Menge; den 0033-`prompt_message_id`-Sonderfall hier auf die
  einheitliche `prompt_msg_id`/`show_step`-Konvention heben.

## Schritt 4 — Validierungsfehler ≠ Schritt-Wechsel

- Sicherstellen (Test je Beispiel), dass Eingabe-Validierungsfehler (leerer Name, Zahl außerhalb
  Bereich) **re-prompten** und das aktive Keyboard **stehen lassen** — kein `show_step`-Übergang.

## Schritt 5 — Regression (Bug-Fix)

- Bestehende Wizard-/UX-Tests und die Feature-0033-Abbruch-Tests bleiben grün.
- `send_message`-Tests unberührt (unverändert).

## Schritt 6 — Optional/danach: Button-Ketten auf `show_step` konvergieren

- Reiner Refactor der bereits sauberen Button-Schritt-Renderings (`edit_message_text` →
  `show_step(..., message_id=…)`), Flow für Flow, jeweils mit grünem Durchlauf-Test.
- **Abbruchsicher:** Bricht dieser Schritt ab, bleibt der Bug-Fix (Schritte 1–5) vollständig — die
  Button-Schritte lassen ohnehin nichts liegen. Kein „halb migriert"-Risiko für den Nutzer.

## Schritt 7 — Doku

- `docs/design/telegram-nachrichten.html`: Notiz, dass Assistenten über eine lebende
  Prompt-Nachricht laufen (Regel `telegram_messages.md`; Nachrichtentexte unverändert).

## Schritt 8 — Coverage & Abschluss

- `.\scripts\run_coverage.ps1` — Coverage darf nicht regredieren.

## Definition of Done

- [ ] `send_message_id` liefert die `message_id` (+ Test); `send_message` unverändert
- [ ] `show_step`-Renderer mit Invariante (+ Tests für beide Zweige + Entry-Fall)
- [ ] Getippte Übergänge + Entry-Prompts aller Flows über `show_step`; genau eine lebende
  Prompt-Nachricht je Flow
- [ ] Validierungsfehler lassen das aktive Keyboard stehen
- [ ] 0033-Sonderlogik (Guss-`prompt_message_id`) auf `prompt_msg_id` konsolidiert
- [ ] (Optional) Button-Ketten auf `show_step` konvergiert
- [ ] Alle Tests grün, Coverage nicht regriert
- [ ] `telegram-nachrichten.html` aktualisiert
- [ ] Beads-Issue geschlossen
- [ ] Feature- und Plan-Dokument nach `completed/` verschoben
