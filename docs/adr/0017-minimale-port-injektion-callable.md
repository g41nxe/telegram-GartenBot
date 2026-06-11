# 17. Minimale Port-Injektion über Callable-Signaturen

Wenn ein Kern-Modul eine I/O-Operation ausführen muss (z. B. eine MQTT-Nachricht senden), wird die kleinstmögliche aufrufbare Signatur (`Callable[[str, str], bool]`) injiziert — keine vollständige Adapter-Klasse.

## Kontext

Der `WateringController` (`core/watering_controller.py`) benötigte die Fähigkeit, MQTT-Nachrichten zu veröffentlichen (Ventil öffnen, schließen, Sicherheitskonfiguration senden). Die ursprüngliche Implementierung löste dies durch direkte Injektion einer `MqttClient`-Instanz aus `adapters/mqtt_client.py`:

```python
# Ursprünglicher Konstruktor — Hexagonal-Architektur-Verletzung
from ..adapters.mqtt_client import MqttClient

def __init__(self, event_bus: EventBus, mqtt_client_instance: MqttClient):
    self.mqtt_client = mqtt_client_instance
```

Dieses Muster verstieß gegen zwei Grundregeln:
1. **Aufwärts-Abhängigkeit:** `core/` importierte direkt aus `adapters/` — die Richtung der Abhängigkeit war invertiert.
2. **Interface Segregation:** Der Controller erhielt die gesamte `MqttClient`-Schnittstelle (subscribe, get_valve_status, request_valve_status, ...), benötigte aber ausschließlich die `publish(topic, payload)` Operation.

Außerdem mussten Tests für `WateringController` eine `SimulatedMqttAdapter`-Instanz aufbauen, obwohl nur das Publish-Verhalten relevant war.

## Entscheidung

1. **Injektion der minimalen Callable-Signatur:**
   - Statt einer Adapter-Instanz wird eine einzelne Funktion injiziert:
     ```python
     def __init__(self, event_bus: EventBus, publish_fn: Callable[[str, str], bool]):
         self.publish_fn = publish_fn
     ```
   - Die Verdrahtung erfolgt ausschließlich in `main.py`:
     ```python
     watering_ctrl = WateringController(
         mqtt_client._global_bus,
         mqtt_client.client_instance.publish  # gebundene Methode
     )
     ```

2. **Domain-Events bleiben in `core/`:**
   - Ereignisse, die `core/` abonniert (z. B. `ValveStatusReported`, `DeviceJoinedEvent`), werden in `core/valve_events.py` definiert.
   - Der MQTT-Adapter importiert sie von dort und re-exportiert sie für externe Verwender (`from ..core.valve_events import ValveStatusReported`).
   - Damit ist die Abhängigkeitsrichtung klar: `adapters` kennt `core`, niemals umgekehrt.

3. **Testdoubles werden trivial:**
   - Unit-Tests für `WateringController` benötigen nur ein Lambda:
     ```python
     ctrl = WateringController(bus, lambda topic, payload: True)
     ```

## Konsequenzen

- **Vorteile:**
  - `grep -r "from ..adapters" src/daemon/core/` liefert keine Treffer mehr — die Abhängigkeitsgrenze ist maschinell prüfbar.
  - Tests für Kern-Module sind vollständig von der Transport-Schicht entkoppelt.
  - Das Interface Segregation Principle wird maximal eingehalten: Der Controller kennt nur `publish`, nicht den gesamten Adapter.
- **Nachteile:**
  - Bei einer zukünftigen Erweiterung, die mehr als eine MQTT-Operation aus dem Kern heraus benötigt, müssen mehrere Callables injiziert werden — oder ein dediziertes `Protocol` (Port-Interface) eingeführt werden. Das `Protocol`-Muster ist dann der natürliche nächste Schritt, sollte aber erst eingeführt werden, wenn mehr als zwei Callables injiziert werden müssen (YAGNI).
