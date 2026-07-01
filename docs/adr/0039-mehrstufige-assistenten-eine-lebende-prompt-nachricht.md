# 39. Mehrstufige Assistenten als eine lebende Prompt-Nachricht

Mehrstufige Eingabe-Assistenten (Zeitplan, Nebel, Kamera-Kopplung, Ventil-Kopplung, manueller
Guss) führen den Nutzer über genau **eine lebende Prompt-Nachricht**: zu jedem Zeitpunkt gibt es
höchstens ein aktives Inline-Keyboard des Assistenten. Alle Schritte laufen über einen
gemeinsamen Renderer `show_step`.

## Kontext

Button-Schritte editierten bereits dieselbe Nachricht (`edit_message_text`). **Getippte** Schritte
(Name, Custom-Dauer/-Menge, Kamera-Name/-Intervall) laufen in `_process_message` ohne die
`message_id` des Prompts — sie sendeten eine **neue** Nachricht und ließen den vorherigen Prompt
samt Inline-Keyboard stehen (tote, klickbare Buttons; uneinheitliches Verhalten).

Ein rein editierender „Einzelkarten"-Ansatz scheidet aus: **Editieren verschiebt eine Nachricht in
Telegram nicht.** Nach einer getippten Eingabe (die als eigene Bubble darunter erscheint) würde der
in place editierte Prompt nach oben driften — der Nutzer sieht unten seine Eingabe, nicht den
nächsten Schritt.

## Entscheidung

- **Aufgeräumter Gesprächsverlauf (nicht Einzelkarte):** Getippte Nutzer-Eingaben bleiben sichtbar;
  der Bot löscht keine Nutzernachrichten. Nach einer getippten Eingabe erscheint der nächste Schritt
  als **frische** Nachricht unten (gute Sichtbarkeit).
- **Invariante „eine lebende Prompt-Nachricht":** `state["prompt_msg_id"]` zeigt stets auf den
  aktuell aktiven Assistenten-Prompt. Beim Übergang wird das Keyboard des vorherigen Prompts
  entfernt (`edit_message_reply_markup`, ADR 0038).
- **Ein gemeinsamer Renderer** `show_step(chat_id, state, text, keyboard, message_id=None)`:
  - `message_id` gesetzt (Button-Schritt) → editiert diese Nachricht in place.
  - `message_id` None (getippter Schritt) → räumt das alte Prompt-Keyboard ab und sendet einen
    frischen Prompt.
  - hält in beiden Fällen die Invariante (`state["prompt_msg_id"]`).
- **Dedizierte `send_message_id(...) -> int | None`** liefert die `message_id` aus dem
  Antwort-Body. Das bestehende `send_message` bleibt unangetastet (Contract `-> bool`,
  Chunk-Splitting, Markdown-Fallback) — es liest den Body heute nicht und darf Erfolg/Fehler nicht
  mit der id vermischen. Nur die Assistenten-Prompts nutzen `send_message_id`.
- Gilt für **alle** mehrstufigen Flows. Reihenfolge nach kritischem Review: zuerst der Bug-Fix
  (getippte Übergänge + Entry-Prompts über `show_step`), **danach separat** die Konvergenz der
  bereits sauberen Button-Ketten auf `show_step` (ohne den Fix zu gefährden). Zeitplan-Wizard zuerst
  als Referenz.

## Konsequenzen

- Keine toten Inline-Keyboards mehr in mehrstufigen Flows; einheitliches Muster, an **einer** Stelle
  verwaltet (SRP/DRY).
- Baut auf ADR 0038 (Inline-Keyboard-Aufräumen) auf und erweitert es um die Assistenten-Übergänge.
  Feature 0033 bleibt gültig; `show_step` nutzt denselben `edit_message_reply_markup`-Mechanismus.
- Rein präsentationsseitig (`ui/telegram_ui.py`, `ui/telegram_client.py`); keine Core-/Adapter-
  Änderung.
- **Nicht abgedeckt:** TTL-/Timeout-Aufräumen abgebrochener Assistenten ohne Nutzer-Interaktion
  (die `prompt_msg_id` bleibt bis zum Ablauf im State; separate spätere Verfeinerung).
