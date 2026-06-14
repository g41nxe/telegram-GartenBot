# Feature: Architektur-Bereinigung (Refactoring)

## Problemstellung (Problem Statement)

Die Codebasis weist an drei Stellen architektonische Reibungspunkte und unnötige Kopplungen auf, die die Wartbarkeit erschweren und Tests künstlich verlangsamen:
1. **Verlangsamte Tests im Tagesbericht-Adapter:** Der Adapter `daily_report.py` enthält in `send_daily_report()` einen fest einprogrammierten `time.sleep(5.0)` sowie den Aufruf von `mqtt_client.request_valve_status()`. Jeder Unit-Test dieses Adapters benötigt dadurch echte 5 Sekunden Wartezeit. Die Wartezeit und die MQTT-Interaktion gehören nicht in den Adapter, sondern in den Scheduler-Hintergrund-Thread.
2. **Unnötige Scheduler-Fassade:** Das Modul `scheduler.py` dient als rein delegierende Fassade über die Guss-Steuerung (`WateringController`). Aufrufe wie `scheduler.start_watering()` leiten lediglich an den Controller weiter. Dies verschleiert die wahren Abhängigkeiten und verkompliziert den Datenfluss.
3. **Pass-Through-Modul für Telegram:** Das Modul `telegram_bot.py` besteht nur aus zwei Delegierungsfunktionen, die die UI mit dem Client verdrahten. Es hat keinen eigenen Nutzen und bläht die UI-Schicht und die Code-Komplexität unnötig auf.

## Lösung (Solution)

Wir führen ein technisches Refactoring durch, um diese Reibungspunkte zu entfernen:
1. **Entkopplung des Tagesberichts:** Der `time.sleep` und der MQTT-Prefetch werden in einen privaten Helper `_send_daily_report_with_prefetch()` im Scheduler verschoben. `send_daily_report()` im Adapter wird zustandslos und frei von blockierendem I/O, was blitzschnelle Tests ermöglicht.
2. **Auflösung der Scheduler-Fassade:** Die UI (`telegram_ui.py`) und Tests kommunizieren direkt mit der Guss-Steuerung (`WateringController`). Die Guss-Steuerung wird sauber über `main.py` an `telegram_ui.py` und `scheduler.py` injiziert.
3. **Inlining der Telegram-Verdrahtung:** Das überflüssige Modul `telegram_bot.py` wird gelöscht. Die Initialisierung und Verdrahtung des Bots erfolgt direkt in `main.py`.

## User Stories (Entwickler-Perspektive)

1. Als Entwickler möchte ich, dass die Testsuite schnell und ohne künstliche Blockaden (sleep) ausgeführt wird, um beim Entwickeln zügiges Feedback zu erhalten.
2. Als Entwickler möchte ich eine klare Trennung der Zuständigkeiten sehen, bei der UI-Komponenten direkt auf die Guss-Steuerung zugreifen, statt über eine Scheduler-Fassade umgeleitet zu werden.
3. Als Entwickler möchte ich ein sauber verdrahtetes System in `main.py` haben, ohne rein delegierende Hilfsmodule wie `telegram_bot.py` instanziieren zu müssen.
4. Als Entwickler möchte ich sicherstellen, dass Änderungen an den Modulschnittstellen (z. B. Umbenennungen von Wiring-Funktionen) durch automatisierte Smoke-Tests in der CI-Pipeline abgefangen werden.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Verschiebung des Prefetchings:** Der Scheduler-Hintergrundthread ruft `_send_daily_report_with_prefetch()` auf, welcher die MQTT-Statusaktualisierung anfordert, 5 Sekunden schläft und dann `send_daily_report()` aufruft.
- **Injektion der Guss-Steuerung:** In `main.py` wird die Guss-Steuerung (`WateringController`) instanziiert und über Setzer-Funktionen (`set_controller()` im Scheduler und `set_watering_controller()` in `telegram_ui`) injiziert.
- **Löschen von `telegram_bot.py`:** Das Modul wird vollständig aus der Codebasis entfernt. Die Registrierung des Callback-Handlers und der Start des Polling-Dienstes werden direkt in `main.py` inlined.
- **Anpassung der Smoke-Tests:** Regel 6 in `ARCHITECTURE.md` wird an die neue Struktur angepasst. Der Smoke-Test prüft fortan die inlined Verdrahtung in `main.py`.

## Test-Entscheidungen (Testing Decisions)

- **Unit-Tests für den Tagesbericht:** Neue Tests in `tests/adapters/test_daily_report.py` prüfen, dass `send_daily_report()` Events korrekt feuert und Metadaten schreibt, dabei aber weder blockiert (`time.sleep`) noch direkt MQTT-Nachrichten sendet.
- **Integrationstests (test_irrigation.py):** Alle Testfälle rufen die Methoden der Guss-Steuerung direkt über `self.watering_ctrl` auf, anstatt über die alte Scheduler-Fassade zu gehen.
- **UI-Tests (test_telegram_ui.py):** Mocking-Aufrufe werden so angepasst, dass sie `_watering_ctrl` anstelle von `scheduler` patchen.
- **Smoke-Test:** Der Wiring-Test wird aktualisiert, um die Initialisierungsschritte in `main.py` zu verifizieren.

## Nicht im Leistungsumfang (Out of Scope)

- Funktionale Änderungen an der Guss-Steuerung, der Zeitplanung oder den Telegram-Befehlen.
- Überarbeitung der Zustandsverwaltung (State Machine) der UI-Wizards.
- Refactoring anderer Adapter (z. B. `weather.py` oder `database.py`).

## Weitere Anmerkungen (Further Notes)

- Dieses Feature ist ein rein technisches Refactoring (Refactoring/Architecture Debt) und hat keine sichtbaren Auswirkungen auf die Benutzeroberfläche des Telegram-Bots.
