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
- Ausführung: `python -m unittest discover -s tests`
- Jede neue Domain-Logik-Funktion benötigt mindestens einen Test.
- Externe Abhängigkeiten (MQTT, Datenbank, Wetter-API) werden mit `unittest.mock` gemockt.
- `mqtt_client.HAS_PAHO = False` muss in Tests gesetzt sein.

## Commit Messages

- Prefix `RALPH:` für Agenten-Commits.
- Inhalt: erledigte Aufgabe, geänderte Dateien, Entscheidungen, ggf. Blocker.
