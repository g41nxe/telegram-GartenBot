# Telegram-Nachrichten &amp; Navigation: Design-System, Referenz &amp; Sitemap

Drei Dokumente in `docs/design/` steuern die Telegram-Oberfläche:

- [`telegram-design-system.html`](../../docs/design/telegram-design-system.html) — **SOLL / verbindliche Regeln**: Anrede, Ton-Register, Markdown-Konvention, Einheiten-/Datumsformate, Emoji-Semantik, Garten-Ampel, Progressive Disclosure. Grundlage ist ADR 0029.
- [`telegram-nachrichten.html`](../../docs/design/telegram-nachrichten.html) — **IST-Stand der Nachrichten**: originalgetreue Referenz aller heute versendeten Nachrichten.
- [`telegram-sitemap.html`](../../docs/design/telegram-sitemap.html) — **Navigations-Übersicht**: alle Slash-Befehle (registriert vs. dispatcher-only), Haupttastatur und Untermenü-/Flow-Ebenen mit ihren `callback_data`.

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

## Regel: Sitemap synchron halten

Wenn du die **Navigationsstruktur** des Bots änderst — also einen Slash-Befehl, einen Tastatur-Button, ein Untermenü, einen Flow-Schritt oder einen `callback_data`-Eintrag **hinzufügst, umbenennst, verschiebst oder entfernst** — MUSST du `telegram-sitemap.html` im selben Arbeitsschritt aktualisieren. Das betrifft insbesondere Änderungen in:

- dem Dispatcher in `src/daemon/ui/telegram_ui.py` (`_process_message` / `_process_callback_query`),
- `get_main_keyboard()` und den Untermenü-Handlern (`handle_kamera_menu`, `handle_einstellungen_menu`, …),
- der registrierten Befehlsliste in `src/daemon/main.py` (`register_telegram_commands`).

Beim Aktualisieren:

1. **Registriert vs. dispatcher-only:** Befehle korrekt einordnen — ins registrierte `/`-Menü kommt nur, was `register_telegram_commands` listet; alles andere unter „Dispatcher-only".
2. **Callbacks annotieren:** Jede Ebene trägt ihr `callback_data`; situative Schritte (z. B. „>1 Ventil") als `.pill`-Bedingung markieren.
3. **Abgrenzung zur Nachrichten-Referenz:** Reine Textänderungen ohne Struktur-/Routing-Wirkung gehören in `telegram-nachrichten.html`; die Sitemap ändert sich nur, wenn sich **Befehle, Buttons, Menü-Ebenen oder Callbacks** ändern.

## Regel: Keine redundanten Slash-Befehle (De-dup Menü ↔ Tastatur)

Das registrierte `/`-Menü (`register_telegram_commands` in `main.py`) und die permanente Haupttastatur (`get_main_keyboard`) sind zwei Wege zur selben Funktion. Um Redundanz zu vermeiden, gilt für **jeden** Slash-Befehl:

Ein Slash-Befehl wird nur im Dispatcher (`_process_message`) geführt — und nur dann ggf. ins `/`-Menü aufgenommen — wenn er **mindestens eines** erfüllt:

1. **Eigene Logik / einziger Zugang:** Es gibt keinen gleichwertigen Reply-Keyboard-Button (z. B. `/tagesbericht`, `/start`).
2. **Separat verlinkt:** Eine Bot- oder CI-Nachricht fordert den Nutzer auf, ihn zu **tippen** (z. B. `/status` — Kopplungs-, OTA- und Unbekannt-Hinweise; `/update` — CI-Build-Benachrichtigung in `.github/workflows/release.yml`).

Ein Befehl, der **nur einen Tastatur-Button dupliziert** und **nirgends verlinkt** ist, wird **komplett entfernt** — weder registriert noch im Dispatcher. Der Button ist dann der einzige Zugang (so geschehen mit `/zeitplaene`, `/einstellungen`, `/stopp`).

Weitere Leitplanken:

- **Registriertes `/`-Menü ⊂ Dispatcher:** Es enthält nur Befehle, die ohnehin im Dispatcher leben, und davon nur die für Tippen/Auffindbarkeit sinnvollen. `/start` bleibt dispatcher-only (Telegram-Konvention).
- **Bewusste Ausnahmen benennen:** Ein registrierter Befehl, der einen Button dupliziert (derzeit nur `/status`), MUSS als ausdrückliche Ausnahme dokumentiert sein (häufigster Befehl + mehrfach in Nachrichten verlinkt).
- **Verlinkung mitpflegen:** Wer einen verlinkten Befehl entfernt oder umbenennt, MUSS auch die verweisende Nachricht (Bot-Text oder CI-Workflow) anpassen — sonst zeigt sie ins Leere.

Grundlage: ADR 0034 (Bot-Navigation). Jede Änderung am Befehls-/Menü-Satz aktualisiert zusätzlich die Sitemap (siehe oben).

## Regel: Befehls-Referenzen in der Prosa-Doku synchron halten

Slash-Befehle werden nicht nur in den `docs/design/`-HTMLs dokumentiert, sondern auch in **erzählender, benutzersichtbarer Doku**. Wenn du einen Slash-Befehl **hinzufügst, umbenennst oder entfernst** (siehe De-dup-Regel oben), MUSST du im selben Arbeitsschritt diese **lebenden** Dateien angleichen:

- [`README.md`](../../README.md) — Abschnitte „✨ Highlights", „🤖 Bedienung im Telegram-Bot", Schnellstart und Troubleshooting.
- [`CONTEXT.md`](../../CONTEXT.md) — Glossar-Einträge, die einen Befehl in Klammern nennen.
- [`docs/assets/bot_description.md`](../../docs/assets/bot_description.md) — die bei @BotFather hinterlegte Bot-Beschreibung.

Maßgeblich (Single Source of Truth) ist der **Code**: der Dispatcher (`_process_message` in `telegram_ui.py`) plus `register_telegram_commands` in `main.py`. Es existiert nur, was dort vorkommt — derzeit `/start`, `/status`, `/tagesbericht`, `/update`, `/diagnose`. Alles andere ist ein Tastatur-Button.

Beim Angleichen:

1. **Entfernte Befehle raus:** Ist ein Befehl zum Button geworden, nenne ihn beim **Button-Label** (z. B. „💧 Gießcheck"), nicht mehr als `/befehl`. Verwaiste `/befehl`-Erwähnungen ersatzlos streichen.
2. **Nur gültige Befehle als `/...`:** In der Prosa darf ein `` `/befehl` `` nur stehen, wenn er im Dispatcher existiert.
3. **Schnell prüfen:** `grep -rnoE '`/[a-z_]+`' README.md CONTEXT.md docs/assets/bot_description.md` — jeder Treffer außer `/start`, `/status`, `/tagesbericht`, `/update`, `/diagnose` ist ein Fehler.

**NICHT anfassen** (historische bzw. eigenständig gepflegte Quellen — diese spiegeln bewusst den Stand ihrer Entstehung):

- `docs/adr/*` und `docs/**/completed/*` — Architektur- bzw. Feature-/Plan-Aufzeichnungen.
- `CHANGELOG.md` — Release-Historie.
- `.beads/issues.jsonl` — Tracker-Daten.
- Die `docs/design/`-HTMLs sind die **Soll-Quelle** und werden über die Sitemap-/Nachrichten-Regeln oben gepflegt, nicht über diese.

## Hinweis für Feature-Arbeit

Plant ein Feature neue Benachrichtigungen oder ändert es die Navigation, gehört die Aktualisierung **beider** Referenzen (`telegram-nachrichten.html` und `telegram-sitemap.html`) **sowie der Prosa-Doku** (`README.md`, `CONTEXT.md`, `docs/assets/bot_description.md`, sofern dort Befehle genannt sind) zur Definition of Done — analog zur Pflege von `CONTEXT.md` und den ADRs.
