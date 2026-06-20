# Coding Standards

> Architecture rules → see @ARCHITECTURE.md (loaded separately by the agent)
> Domain language  → see @CONTEXT.md (loaded separately by the agent)

## Style

- `snake_case` für Variablen, Funktionen und Module; `PascalCase` für Klassen; `UPPER_CASE` für Konstanten.
- Type hints für alle öffentlichen Funktionen und Methoden.
- Logging über `logging.getLogger("garden_<modul>")` — kein `print()` im Produktionscode.
- Kein auskommentierter Code in Commits.

## Testing

- Tests liegen in `tests/`; Dateiname beginnt mit `test_`.
- Ausführung: `python -m pytest tests` (pytest führt sowohl `unittest.TestCase`- als auch pytest-Stil-Tests aus).
- Jede neue Domain-Logik-Funktion benötigt mindestens einen Test.
- Externe Abhängigkeiten (MQTT, Datenbank, Wetter-API) werden mit `unittest.mock` gemockt.
- `mqtt_client.HAS_PAHO = False` muss in Tests gesetzt sein.

## Telegram-Nachrichten

Gilt für jede benutzersichtbare Nachricht in `src/daemon/ui/telegram_ui.py` und `src/daemon/adapters/daily_report.py`.

- **SOLL einhalten:** Neue/geänderte Nachrichten MÜSSEN dem Design-System (`docs/design/telegram-design-system.html`, ADR 0029) folgen: Anrede durchgängig „du"; Legacy-Markdown (Fett `*einfach*`, Kursiv `_unterstrich_`, **nie** `**doppelt**`); Überschrift `*<Emoji> Titel*` (ein Emoji, kein Doppelpunkt); Einheiten mit Leerzeichen (`22.4 °C`); Zeiten mit „Uhr"; Ampel 🟢/🟡/🔴 nur für Gesundheits-Status.
- **IST synchron halten:** Wer eine benutzersichtbare Nachricht hinzufügt, ändert oder entfernt, MUSS sie im selben Arbeitsschritt in `docs/design/telegram-nachrichten.html` nachziehen — mit realistischen Beispieldaten, `.src`-Label (zuständige Funktion/Event) und Einordnung in die passende Sektion.
- Volle Regel: `.agents/rules/telegram_messages.md`.

## Commit Messages

- Prefix `RALPH:` für Agenten-Commits.
- Inhalt: erledigte Aufgabe, geänderte Dateien, Entscheidungen, ggf. Blocker.
