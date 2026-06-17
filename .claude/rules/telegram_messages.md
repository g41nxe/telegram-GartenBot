# Telegram-Nachrichten: Referenz pflegen

Die Datei [`docs/reference/telegram-nachrichten.html`](../../docs/reference/telegram-nachrichten.html) ist die zentrale, originalgetreue Referenz aller Nachrichten, die der Telegram-Bot versendet (Befehle, Assistenten, Ereignis-Benachrichtigungen, Fehlermeldungen). Sie dient der UI-Konsistenz und als Überblick beim Entwurf neuer Features.

## Regel: Referenz synchron halten

Wenn du eine benutzersichtbare Telegram-Nachricht **hinzufügst, änderst oder entfernst**, MUSST du die Referenz-Datei im selben Arbeitsschritt aktualisieren. Das betrifft insbesondere Änderungen in:

- `src/daemon/ui/telegram_ui.py` (Befehls-Handler, Assistenten-Texte, `_on_*`-Benachrichtigungs-Handler, Tastaturen)
- `src/daemon/adapters/daily_report.py` (Tagesbericht-Bausteine)

Beim Aktualisieren:

1. **Originalgetreu bleiben:** Setze realistische Beispieldaten in die echten Textvorlagen ein — keine erfundenen Felder, keine Platzhalter wie `<...>`.
2. **Quelle annotieren:** Jede Sprechblase trägt im `.src`-Label die zuständige Funktion bzw. den Event-Typ (z. B. `_on_watering_completed · WateringCycleCompleted`).
3. **In die passende Sektion einordnen:** Befehle & Menüs / Assistenten / Ereignis-Benachrichtigungen / Fehler & Hinweise.
4. **Varianten dokumentieren:** Statusabhängige Textbausteine (z. B. Batterie-Stufen, Tagesbericht-Zweige) in einer `ul.variants`-Liste festhalten.

## Hinweis für Feature-Arbeit

Plant ein Feature neue Benachrichtigungen, gehört die Aktualisierung dieser Referenz zur Definition of Done — analog zur Pflege von `CONTEXT.md` und den ADRs.
