# 14. Statuseinheitliche und datenbankentkoppelte Infrastruktur-Adapter

Wir legen fest, dass Infrastruktur- und Kommunikations-Adapter (wie z.B. der MQTT-Client oder der Wetter-Dienst-Client) vollständig zustandslos bezüglich der Domänenlogik sein müssen und keine direkte Kopplung zur Persistenzschicht (Datenbank) aufweisen dürfen.

## Kontext

Bei der Analyse der Architektur traten folgende Verstöße gegen die modulare Entkopplung (ADR-0008) auf:
1. **Zustandserhaltung im Adapter:** Der MQTT-Adapter (`mqtt_client.py`) hielt globalen Zustand über den laufenden Bewässerungszyklus (`active_cycle_volume`, `last_flow_update_time`) und berechnete die Wassermenge. Die Guss-Steuerung (`WateringController`) manipulierte und las diesen globalen Zustand über die Modulgrenze hinweg.
2. **Direkte DB-Kopplung im API-Client:** Der Wetter-Dienst (`weather.py`) speicherte Wetterdaten direkt in der Datenbank via `database.log_weather` und las bei Netzwerkfehlern direkt Fallback-Werte aus der Datenbank. Dies machte den API-Client schwer testbar und vermischte I/O-Netzwerkkommunikation mit Persistenz.

## Entscheidung

Wir treffen folgende Architekturentscheidungen zur Festigung der Modulgrenzen:

1. **Strikte Zustandslosigkeit von Transport-Adaptern:**
   - Transport-Adapter (z. B. MQTT) dürfen keine Domänen-Zustände (wie aktive Gussvolumina) verwalten oder Berechnungen dazu anstellen.
   - Sie übersetzen lediglich eingehende Rohdaten in typisierte Ereignisse (`ValveStatusReported`) und leiten diese an den systemweiten `EventBus` weiter.
   - Die fachliche Guss-Steuerung (`WateringController`) absorbiert diese Zustände und führt die Berechnungen (z. B. Durchfluss-Integration) intern aus.

2. **Entkopplung externer API-Clients von der Persistenz:**
   - Externe API-Adapter (z. B. Wetter-Dienst) sind reine Funktions-Clients. Sie nehmen Parameter entgegen, führen den Netzwerkaufruf aus, verarbeiten das JSON und geben die Daten zurück oder werfen Fehler.
   - Das Archivieren erfolgreich abgerufener Daten erfolgt über das Feuern eines Ereignisses (z. B. `WeatherDataFetched`), welches asynchron von einem dedizierten `DatabaseLoggerAdapter` empfangen und in die Datenbank geschrieben wird.
   - Die Fehlerbehandlung und das Auslesen von Fallback-Daten aus der Datenbank bei API-Ausfällen wandert in die aufrufende Logik (z. B. im Status-Kommando oder im Scheduler-Bericht-Generator).

## Konsequenzen

- **Vorteile:**
  - **Einfache Testbarkeit:** Sowohl der MQTT-Adapter als auch der Wetter-Dienst können nun ohne jegliche Datenbank-Anbindung oder Mocking von Datenbank-Funktionen in isolation getestet werden.
  - **Saubere Modulgrenzen:** Keine unerwarteten Seiteneffekte (wie unbeabsichtigte Schreibvorgänge in die SQLite-Datei) bei der Benutzung von API-Clients.
  - **Bessere Locality:** Fachliche Zustände der Bewässerung verbleiben ausschließlich im Kern (`WateringController`).
- **Nachteile:**
  - Aufrufer müssen sich explizit um Fehlerbehandlung und DB-Fallback kümmern, statt dies transparent vom Wetter-Modul geliefert zu bekommen.
