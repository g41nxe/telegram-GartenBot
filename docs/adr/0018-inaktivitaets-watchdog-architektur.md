# 18. Inaktivitäts-Watchdog — Modulstruktur und sofortige Entwarnung via Ereignis-Kanal

Der Inaktivitäts-Watchdog wird als eigenständiges Adapter-Modul implementiert. Die Entwarnung erfolgt sofort über eine dauerhafte Modulsubscription auf `ValveStatusReported` — nicht erst beim nächsten stündlichen Prüflauf.

## Kontext

Der Inaktivitäts-Watchdog erfüllt zwei zeitlich verschiedene Aufgaben:

1. **Alarm auslösen:** Stündliche Prüfung, ob ein Ventil seit mehr als `WATCHDOG_VALVE_TIMEOUT_HOURS` Stunden kein Signal gesendet hat.
2. **Entwarnung geben:** Sofortige Benachrichtigung, sobald ein zuvor inaktives Ventil wieder ein MQTT-Signal sendet.

Beide Aufgaben haben unterschiedliche Auslösemechanismen. Die Frage war, wie die Entwarnung ohne Polling-Verzögerung und ohne Architekturverletzung realisiert werden kann.

**Verworfene Alternative — Entwarnung im stündlichen Check:**
Der stündliche `run_watchdog_check()` hätte auch die Entwarnung erkennen können (aktives Flag + frischer `last_update`-Zeitstempel). Dies wäre einfacher, würde aber eine Verzögerung von bis zu einer Stunde bedeuten und widerspricht der Anforderung sofortiger Benachrichtigung.

**Verworfene Alternative — Entwarnung im MQTT-Adapter:**
Der MQTT-Adapter könnte nach jedem Ventil-Update `system_metadata` prüfen und `InactivityAlertResolved` publizieren. Dies verletzt jedoch das Prinzip stateless adapters (ADR-0014) und bringt Alarm-Logik in einen Transport-Adapter.

## Entscheidung

### 1. Eigenständiges Modul `adapters/watchdog.py`

Die Watchdog-Logik lebt in einem dedizierten Adapter-Modul, nicht inline im Scheduler. Gründe:

- Der `_scheduler_loop` enthält bereits drei periodische Aufgaben (Tagesbericht, Wetter-Pre-Poll, Zeitpläne). Weitere Inline-Logik erschwert Lesbarkeit und Testbarkeit.
- `adapters/watchdog.py` ist isoliert testbar ohne den gesamten Scheduler aufzubauen.
- Das Modul selbst ist zustandslos — persistenter Zustand liegt ausschließlich in `system_metadata`.

Das Modul stellt zwei öffentliche Funktionen bereit:

```python
def initialize(event_bus: EventBus) -> None:
    """Registriert die dauerhaften Ereignis-Kanal-Abonnements. Einmalig beim Daemon-Start aufrufen."""

def run_watchdog_check(event_bus: EventBus) -> None:
    """Stündliche Aktivitätsprüfung aller registrierten Ventile."""
```

### 2. Event-Typen in `core/watchdog_events.py`

```python
class InactivityAlertTriggered(Event):
    def __init__(self, device_name: str, valve_id: int, hours_silent: float, timeout_hours: int): ...

class InactivityAlertResolved(Event):
    def __init__(self, device_name: str, valve_id: int): ...
```

Platzierung in `core/` folgt dem Muster von `core/valve_events.py` (ADR-0017): `telegram_ui.py` kann Events abonnieren, ohne einen Adapter zu importieren. Die Abhängigkeitsrichtung bleibt `adapters → core`.

### 3. Sofortige Entwarnung via dauerhafter Modulsubscription

`initialize()` registriert auf Modulebene einen Listener auf `ValveStatusReported`:

```python
def initialize(event_bus: EventBus) -> None:
    if not config.WATCHDOG_ENABLED:
        return

    def on_valve_status(event: ValveStatusReported) -> None:
        valve = database.get_valve_by_mqtt_name(event.mqtt_name)
        if valve is None:
            return
        flag_key = f"watchdog_alert_active_valve_{valve['id']}"
        if database.get_metadata(flag_key) == "1":
            database.set_metadata(flag_key, "0")
            event_bus.publish(InactivityAlertResolved(valve["wish_name"], valve["id"]))

    event_bus.subscribe(ValveStatusReported, on_valve_status)
    # Kein unsubscribe() — Modulebene-Listener laufen für die gesamte Daemon-Laufzeit (ADR-0016).
```

### 4. Verhalten bei `last_update IS NULL`

Ventile ohne empfangenes Signal (frisch per Ventil-Kopplung registriert) werden in `run_watchdog_check()` übersprungen. Die Überwachung beginnt erst nach dem ersten eingehenden `ValveStatusReported`-Event.

### 5. Sichtbarkeit im Tagesbericht

Der Tagesbericht liest alle `watchdog_alert_active_valve_*`-Schlüssel mit Wert `"1"` aus `system_metadata` und ergänzt für jedes betroffene Ventil eine Warnzeile. Dies erweitert ADR-0012 (Täglicher Statusbericht) um Watchdog-Zustand ohne Änderung des Mechanismus.

## Konsequenzen

- **Sofortige Entwarnung** ohne Polling-Verzögerung, vollständig entkoppelt vom MQTT-Adapter.
- **Einhaltung von ADR-0014** (stateless adapters): `watchdog.py` hält keinen Zustand im Speicher.
- **Einhaltung von ADR-0016** (Abonnement-Lebenszyklus): Der Listener ist ein Modulebene-Listener ohne erforderliches `unsubscribe()`.
- **Einhaltung von ADR-0017** (Abhängigkeitsrichtung): Events in `core/`, Adapter importieren aus `core/`, niemals umgekehrt.
- **Erweiterbarkeit:** Der Füllstandssensor (Feature 0003) kann nachträglich in `initialize()` und `run_watchdog_check()` integriert werden, sobald die entsprechende Tabelle und Events existieren.
