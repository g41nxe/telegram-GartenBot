# 16. Lebenszyklusverwaltung von Ereignis-Kanal-Abonnements

Jede Funktion, die sich während ihrer Ausführung beim `EventBus` registriert, muss sich in einem `finally`-Block wieder abmelden. Dauerhaft registrierte Listener auf Modulebene sind davon ausgenommen.

## Kontext

Bei der Analyse des Koppelprozesses (`pairing.py`) wurde ein Referenzleck entdeckt: `_pairing_worker()` registrierte einen `DeviceJoinedEvent`-Listener beim systemweiten `EventBus`, rief jedoch nie `unsubscribe()` auf. Im Normalbetrieb war dies unproblematisch, da der Prozess meist erfolgreich abschloss. Bei einem Timeout oder einer Exception blieb der Listener jedoch dauerhaft registriert. Auf einem langlaufenden Daemon (der Raspberry Pi Zero W läuft u.U. wochenlang ohne Neustart) akkumulieren sich diese toten Closures und feuern bei jedem folgenden `DeviceJoinedEvent` — auch wenn der zugehörige Koppelprozess längst abgeschlossen ist.

Ursache war auch, dass der `EventBus` ursprünglich keine `unsubscribe()`-Methode besaß. Die `subscribe()`-Methode ohne Gegenstück erzeugte eine asymmetrische API.

## Entscheidung

1. **`EventBus.unsubscribe(event_type, callback)` ist ein Pflicht-Gegenstück zu `subscribe()`:**
   - Der `EventBus` stellt eine `unsubscribe()`-Methode bereit, die den Callback aus der Listener-Liste entfernt.
   - Ist der Callback nicht registriert, wird kein Fehler geworfen (idempotente Operation).

2. **Abonnements in Funktionsbereichen müssen in `finally`-Blöcken abgemeldet werden:**
   - Jede Funktion oder Methode, die `event_bus.subscribe()` aufruft und deren Lebenszyklus kürzer ist als der des Daemon-Prozesses, MUSS in einem `finally`-Block `event_bus.unsubscribe()` aufrufen.
   - Beispiel:
     ```python
     def _pairing_worker(event_bus, ...):
         def on_device_joined(event):
             ...
         event_bus.subscribe(DeviceJoinedEvent, on_device_joined)
         try:
             # Koppellogik
             ...
         finally:
             event_bus.unsubscribe(DeviceJoinedEvent, on_device_joined)
     ```

3. **Ausnahmen — Abonnements auf Modulebene:**
   - Listener, die beim Modulstart registriert werden und für die gesamte Daemon-Laufzeit aktiv sein sollen (z. B. `DatabaseLoggerAdapter`, `TelegramUiController`), müssen sich nicht abmelden.
   - Diese sind durch ihre Position auf Modulebene klar von scoped Abonnements unterscheidbar.

## Konsequenzen

- **Vorteile:**
  - Kein Anwachsen toter Callback-Referenzen bei langlaufenden Prozessen.
  - Korrektes Verhalten bei wiederholten Kopplungsvorgängen: Jeder Aufruf von `start_pairing()` registriert genau einen Listener, der nach Abschluss entfernt wird.
  - Die asymmetrische `subscribe()`-only-API des `EventBus` ist behoben.
- **Nachteile:**
  - Entwickler müssen sich bewusst an das `try/finally`-Muster halten. Eine automatische Prüfung (Linting-Regel) ist nicht ohne weiteres umsetzbar; die Code-Reviews und das Architektur-Regelwerk in `.agents/rules/architecture.md` übernehmen diese Rolle.
