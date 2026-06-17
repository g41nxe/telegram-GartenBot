# Telegram-Nachrichten: Design-System &amp; Referenz

Zwei Dokumente in `docs/reference/` steuern die Telegram-Nachrichten:

- [`telegram-design-system.html`](../../docs/reference/telegram-design-system.html) — **SOLL / verbindliche Regeln**: Anrede, Ton-Register, Markdown-Konvention, Einheiten-/Datumsformate, Emoji-Semantik, Garten-Ampel, Progressive Disclosure. Grundlage ist ADR 0029.
- [`telegram-nachrichten.html`](../../docs/reference/telegram-nachrichten.html) — **IST-Stand**: originalgetreue Referenz aller heute versendeten Nachrichten.

## Regel: Design-System einhalten

Jede neue oder geänderte benutzersichtbare Nachricht MUSS dem Design-System (`telegram-design-system.html` / ADR 0029) entsprechen — insbesondere:

- Legacy-Markdown: Fett `*einfach*`, Kursiv `_unterstrich_`. **Nie** `**doppelt**`.
- Anrede durchgängig „du"; korrektes Ton-Register je Nachrichtentyp (verspielt / neutral-freundlich / sachlich-klar).
- Überschrift `*<Emoji> Titel*` (ein Emoji, kein Doppelpunkt); Einheiten mit Leerzeichen (`22.4 °C`); Zeiten ohne Sekunden mit „Uhr".
- Emoji nach fester Semantik; Ampelfarben 🟢/🟡/🔴 nur für Gesundheits-Status.

## Regel: IST-Referenz synchron halten

Wenn du eine benutzersichtbare Telegram-Nachricht **hinzufügst, änderst oder entfernst**, MUSST du `telegram-nachrichten.html` im selben Arbeitsschritt aktualisieren. Das betrifft insbesondere Änderungen in:

- `src/daemon/ui/telegram_ui.py` (Befehls-Handler, Assistenten-Texte, `_on_*`-Benachrichtigungs-Handler, Tastaturen)
- `src/daemon/adapters/daily_report.py` (Tagesbericht-Bausteine)

Beim Aktualisieren:

1. **Originalgetreu bleiben:** Setze realistische Beispieldaten in die echten Textvorlagen ein — keine erfundenen Felder, keine Platzhalter wie `<...>`.
2. **Quelle annotieren:** Jede Sprechblase trägt im `.src`-Label die zuständige Funktion bzw. den Event-Typ (z. B. `_on_watering_completed · WateringCycleCompleted`).
3. **In die passende Sektion einordnen:** Befehle & Menüs / Assistenten / Ereignis-Benachrichtigungen / Fehler & Hinweise.
4. **Varianten dokumentieren:** Statusabhängige Textbausteine (z. B. Batterie-Stufen, Tagesbericht-Zweige) in einer `ul.variants`-Liste festhalten.

## Hinweis für Feature-Arbeit

Plant ein Feature neue Benachrichtigungen, gehört die Aktualisierung dieser Referenz zur Definition of Done — analog zur Pflege von `CONTEXT.md` und den ADRs.
