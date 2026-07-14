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

3. **Dauerhaft aktive Abonnements gehören in explizite Setup-Funktionen:**
   - Listener für die gesamte Daemon-Laufzeit (z. B. `telegram_ui`, `watchdog`) DÜRFEN NICHT auf Modulebene registriert werden.
   - Sie werden in eine explizite Funktion ausgelagert (`initialize()`, `subscribe_event_handlers()`), die ausschließlich von `main.py` beim Daemon-Start aufgerufen wird.
   - **Begründung:** Modulebene-Subscriptions feuern beim ersten Import — auch während der Test-Discovery. Kein `unsubscribe()` ist dennoch erforderlich, weil die Lebensdauer dieser Listener identisch mit der des Daemon-Prozesses ist.
   - **Referenzimplementierungen:** `watchdog.initialize()`, `telegram_ui.subscribe_event_handlers()`.

4. **`EventBus.subscribe()` ist idempotent (Ergänzung 2026-07-14):**
   - Derselbe Callback wird pro Ereignis-Typ nur **einmal** registriert; ein zweites `subscribe()`
     ist folgenlos — spiegelbildlich zu Punkt 1, der dasselbe für `unsubscribe()` festhält. Die im
     Kontext beklagte **asymmetrische API** ist damit vollständig behoben.
   - **Begründung:** Ein doppeltes Abonnement stellt jedes Ereignis **zweimal** zu. Für alle
     bisherigen Abonnenten war das folgenlos — sie setzen Flags, und ein Flag zweimal zu setzen
     ändert nichts. Der Verzugs-Zähler der Kamera-Überwachung (ADR 0041) ist der erste **zählende**
     Abonnent: Für ihn ist Doppel-Zustellung ein stiller Rechenfehler, der einen Fehlalarm auslöst.
     Der nächste zählende Abonnent soll diese Zusicherung finden können, statt sie zu entdecken.

## Konsequenzen

- **Vorteile:**
  - Kein Anwachsen toter Callback-Referenzen bei langlaufenden Prozessen.
  - Korrektes Verhalten bei wiederholten Kopplungsvorgängen: Jeder Aufruf von `start_pairing()` registriert genau einen Listener, der nach Abschluss entfernt wird.
  - Die asymmetrische `subscribe()`-only-API des `EventBus` ist behoben.
- **Nachteile:**
  - Entwickler müssen sich bewusst an das `try/finally`-Muster halten. Eine automatische Prüfung (Linting-Regel) ist nicht ohne weiteres umsetzbar; die Code-Reviews und das Architektur-Regelwerk in `.agents/rules/architecture.md` übernehmen diese Rolle.
  - Neue UI-Module, die auf Domain-Events reagieren müssen, brauchen eine explizite Setup-Funktion und einen Aufruf in `main.py`.
