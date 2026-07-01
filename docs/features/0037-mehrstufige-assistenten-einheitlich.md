# Feature: Mehrstufige Assistenten vereinheitlichen (eine lebende Prompt-Nachricht)

Referenz: ADR 0039 · ADR 0038 (Inline-Keyboard-Aufräumen, Feature 0033) · CONTEXT.md (Assistent)

## Problemstellung (Problem Statement)

Die mehrstufigen **Assistenten** des Telegram-Bots (Zeitplan anlegen, Nebel-Intervall,
Kamera-Kopplung, Ventil-Kopplung, manueller Guss) verhalten sich uneinheitlich:

- **Button-Schritte** editieren dieselbe Nachricht in place (`edit_message_text`) — sauberes
  Morphing.
- **Getippte Schritte** (Name, Custom-Dauer/-Menge, Kamera-Name/-Intervall) laufen in
  `_process_message` ohne die `message_id` des aktiven Prompts. Sie **senden eine neue** Nachricht
  und lassen den vorherigen Prompt samt Inline-Keyboard stehen — **tote, klickbare Buttons**.

Konkret beobachtet: Beim Anlegen eines Zeitplans wird nur der letzte Schritt aktualisiert; der
Namens-Prompt bleibt mit seinem „❌ Abbrechen" im Verlauf hängen. Ein versehentlicher Druck löst
einen bereits beendeten Schritt aus.

## Lösung (Solution)

Alle Assistenten führen über genau **eine lebende Prompt-Nachricht**: zu jedem Zeitpunkt gibt es
höchstens ein aktives Inline-Keyboard. Beim Schritt-Wechsel wird das Keyboard des vorherigen
Prompts abgeräumt.

Der Verlauf bleibt ein **aufgeräumter Gesprächsverlauf** (nicht eine gelöschte Einzelkarte):
Getippte Nutzer-Eingaben bleiben sichtbar; der nächste Schritt erscheint nach einer getippten
Eingabe als **frische** Nachricht unten (gute Sichtbarkeit — Editieren verschiebt eine Nachricht in
Telegram nicht). Button-Ketten morphen weiter dieselbe Nachricht.

Mechanisch übernimmt das ein einziger Renderer `show_step`, der die Invariante hält; er nutzt für
das Abräumen den in Feature 0033 eingeführten `edit_message_reply_markup`-Mechanismus.

## User Stories

1. Als Bot-Nutzer möchte ich, dass beim Durchlaufen eines Assistenten keine alten Auswahl-Buttons
   im Verlauf hängen bleiben, damit ich sie nicht versehentlich erneut drücke.
2. Als Bot-Nutzer möchte ich, dass der **aktuelle** Schritt immer unten im Chat sichtbar ist, auch
   nachdem ich etwas getippt habe.
3. Als Bot-Nutzer möchte ich, dass meine getippten Eingaben (Name, Menge) **sichtbar bleiben**,
   damit der Verlauf nachvollziehbar ist — der Bot löscht meine Nachrichten nicht.
4. Als Bot-Nutzer möchte ich dasselbe aufgeräumte Verhalten in **allen** Assistenten (Zeitplan,
   Nebel, Kamera-Kopplung, Ventil-Kopplung, manueller Guss).
5. Als Bot-Nutzer möchte ich, dass ein **Abbruch** mitten im Assistenten das aktive Keyboard
   entfernt (wie in Feature 0033), unabhängig davon, in welchem Schritt ich bin.
6. Als Entwickler möchte ich **einen** einheitlichen Weg, einen Assistenten-Schritt zu rendern,
   damit künftige Flows das Verhalten ohne Sonderlogik erben und die Prompt-Lebensdauer an einer
   Stelle verwaltet wird.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Ein Renderer `show_step(chat_id, state, text, keyboard=None, *, message_id=None)`** in
  `ui/telegram_ui.py` hält die Invariante „`state['prompt_msg_id']` zeigt auf die lebende
  Prompt-Nachricht":
  - `message_id` gesetzt (Button-Schritt) → `edit_message_text` in place; `prompt_msg_id = message_id`.
  - `message_id` None (getippter Schritt) → altes `prompt_msg_id`-Keyboard via
    `edit_message_reply_markup(..., None)` abräumen, frischen Prompt senden, `prompt_msg_id` neu setzen.
- **`send_message` gibt die `message_id` zurück** (statt nur `bool`), damit der Renderer den frischen
  Prompt merken kann. Rückwärtskompatibel für bestehende Aufrufer (Rückgabe wird dort ignoriert).
- **Alle Assistenten-Schritte** rufen künftig `show_step(...)` statt direkt `edit_message_text`/
  `send_message`. Button-Ketten übergeben die Callback-`message_id`, getippte Schritte lassen sie weg.
- **Betroffene Flows** (alle in diesem Feature, inkrementell umgesetzt): Zeitplan-Wizard (Referenz
  zuerst), Nebel-Wizard, Kamera-Kopplung, Ventil-Kopplung, manueller Guss.
- **Eingabe-Validierungsfehler** (z. B. „Name darf nicht leer sein", „Zahl 1–25") sind **kein**
  Schritt-Wechsel — sie re-prompten und lassen das aktive Keyboard stehen (der Flow läuft weiter).
- **Architektur:** rein präsentationsseitig (`ui/telegram_ui.py`, `ui/telegram_client.py`); keine
  Core-/Adapter-Änderung. Baut auf ADR 0038/0039.

## Test-Entscheidungen (Testing Decisions)

- **Nahtstelle (höchste vorhandene):** Dispatcher-Ebene über `_process_message` /
  `_process_callback_query` mit gemocktem `telegram_client`/`database` — Muster aus
  `tests/ui/test_ux_redesign.py`.
- **Invariante geprüft:** Nach einem getippten Übergang wird das Keyboard des vorherigen Prompts
  entfernt (`edit_message_reply_markup(chat_id, <alt>, None)`) und der neue Prompt gesendet;
  `prompt_msg_id` zeigt danach auf den neuen Prompt. Button-Übergänge editieren in place, ohne ein
  Keyboard liegen zu lassen.
- **Pro Flow** ein Durchlauf-Test, der belegt: kein toter Prompt bleibt aktiv (genau eine lebende
  Prompt-Nachricht), getippte Eingaben werden nicht gelöscht.
- **Client:** `send_message` gibt die `message_id` aus der Telegram-Antwort zurück (Test mit
  gemocktem HTTP, analog zu bestehenden `telegram_client`-Tests).
- **Regression:** bestehende Wizard-/UX-Tests bleiben grün; Feature-0033-Abbruch-Tests unberührt.
- **Coverage** darf nicht regredieren.

## Nicht im Leistungsumfang (Out of Scope)

- **Löschen der getippten Nutzer-Eingaben** (Einzelkarten-Look) — bewusst verworfen (der Bot löscht
  keine Nutzernachrichten).
- **TTL-/Timeout-Aufräumen** abgebrochener Assistenten ohne Nutzer-Interaktion — die `prompt_msg_id`
  bleibt bis zum Ablauf im State; spätere Verfeinerung.
- **Inhaltliche Neugestaltung** der Prompt-Texte — es geht nur um die Nachrichten-Mechanik.
- **Reply-Keyboard-Bestätigungen** (ADR 0013) — anderer Mechanismus, unberührt.

## Weitere Anmerkungen (Further Notes)

- **Kern-Fund aus dem Grilling:** Editieren verschiebt eine Nachricht in Telegram nicht. Ein rein
  editierender „Einzelkarten"-Ansatz hätte den Prompt über die getippte Eingabe nach oben driften
  lassen (schlechte Sichtbarkeit). Deshalb der aufgeräumte Gesprächsverlauf statt der Einzelkarte.
- Dieses Feature verallgemeinert Feature 0033: dort wurde das Keyboard-Aufräumen für Abbruch/Fehler
  eingeführt; hier wird es zur durchgängigen Assistenten-Mechanik.
