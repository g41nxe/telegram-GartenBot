# 8. Modulare und ereignisgesteuerte Architektur des Bewässerungs-Daemons

Wir restrukturieren den Bewässerungs-Daemon grundlegend in ein modulares, entkoppeltes und ereignisgesteuertes Design (Inversion of Control) und führen klare Schnittstellen (Seams) ein.

## Kontext

Der bisherige Bewässerungs-Daemon ist in einigen Modulen sehr stark gekoppelt. Insbesondere die Guss-Steuerung (`scheduler.py`), die Netzwerkkommunikation (`mqtt_client.py`, `pairing.py`) und die Benutzeroberfläche (`telegram_bot.py`) weisen architektonische Reibungspunkte auf:
1. **Mangelnde Locality:** Die Guss-Steuerung (Threads, Locks, Timer) ist mit der Zeitplan-Überwachung und den Datenbank-/Telegram-Zugriffen in einem Modul verflochten.
2. **Duplizierte Netzwerkverbindungen:** Der Koppelprozess (`pairing.py`) baut mangels generischer MQTT-Schnittstellen eine eigene, redundante Verbindung zum Mittelweg-Dienst auf. Dadurch ist der Koppelprozess in Tests/Simulationen nicht testbar.
3. **Mischung von Business-Logik und Präsentation:** Core-Komponenten formatieren direkt benutzerbezogene deutsche Telegram-Markdown-Strings.
4. **Schwere Testbarkeit:** Ein isoliertes Testen der Guss-Zustände oder des Koppelvorgangs ohne echte Netzwerkanbindung oder Mocking von Bibliotheken ist kaum möglich.

## Entscheidung

Wir implementieren vier wesentliche architektonische Entscheidungen:

1. **Extraktion der Guss-Steuerung (`WateringController`):**
   * Die Kern-Steuerungslogik für den Kombinierten Guss (zeit- und volumenbasierte Grenzüberwachung, Threading, Locks, Timer) wird in ein deepes, zustandsbehaftetes Modul ausgelagert.
   * Der Controller nutzt Inversion of Control (IoC) und bekommt seine Ports (MqttClient, Ereignis-Kanal) über den Konstruktor injiziert.
   * Der Scheduler (`scheduler.py`) wird auf einen reinen Zeitplan-Watcher reduziert, der stündlich das Wetter prüft und bei Fälligkeit die Guss-Steuerung aufruft.

2. **Einführung des Ereignis-Kanals (Event Bus):**
   * Zur vollständigen Entkopplung des Kerns von Infrastruktur und UI kommuniziert die Guss-Steuerung ausschließlich über fachliche Ereignisse (z. B. `WateringCycleStarted`, `WateringCycleCompleted`, `WateringCycleFailed`).
   * Ein einfacher, synchroner systeminterner Ereignis-Kanal verteilt diese Ereignisse an registrierte Listener (z. B. einen `DatabaseLoggerAdapter` für das SQL-Archiv und einen `TelegramUiController` für Push-Meldungen).

3. **Einheitliche MqttClient-Schnittstelle mit Simulation:**
   * Wir etablieren eine einheitliche, dauerhafte `MqttClient`-Schnittstelle.
   * Es gibt zwei konkrete Implementierungen (Adapter): den `PahoMqttAdapter` (Produktion) und den `SimulatedMqttAdapter` (für den simulationsgestützten Offline-Betrieb).
   * Die Integration der Durchflussmengen und Zeit-Deckelungen wandert vom MQTT-Client in den fachlichen Controller.
   * Der Koppelprozess nutzt dieselbe MQTT-Verbindung und reagiert auf die vom Client übersetzten `DeviceJoined`-Events. Dadurch kann die gesamte Ventil-Kopplung vollautomatisiert in Unit-Tests simuliert und offline geprüft werden.

4. **Entkopplung der Präsentationsschicht (Telegram):**
   * Wir trennen die Präsentationsschicht in zwei Rollen auf:
     * `TelegramClient`: Kapselt rein das API-Handling (Polling-Schleife, ausgehende HTTP-Requests, Whitelist-Sicherheitscheck).
     * `TelegramUiController`: Verwaltet die Benutzeroberfläche, die Zustandsmaschinen der Assistenten (Wizards), abonniert Daemon-Ereignisse und übersetzt diese in lokalisierte deutsche Benachrichtigungen.

## Konsequenzen

- **Vorteile:**
  - **100% Testbarkeit:** Die gesamte Guss-Logik, die Volumen-Integration und der Kopplungsprozess können in extrem schnellen In-Memory-Unit-Tests ohne reale Hardware, Broker oder Telegram-Verbindungen simuliert und verifiziert werden.
  - **Hervorragende Locality & Cohesion:** Änderungen an der UI, der Netzwerk-Infrastruktur oder den Domänenregeln sind strikt auf ihre jeweiligen Dateien isoliert.
  - **Sicherheit:** Reduzierung des Socket-Overheads auf dem ressourcenbeschränkten Raspberry Pi Zero W.
  - **Austauschbarkeit:** Zukünftige Erweiterungen (z. B. ein zusätzliches Web-Cockpit oder ein anderer Messenger) können einfach als neue Ereignis-Abonnenten hinzugefügt werden, ohne eine Zeile Core-Code anzufassen.

- **Nachteile:**
  - Höhere Anzahl an Python-Dateien im Projekt (feingranularer modularer Aufbau).
  - Einbindung eines einfachen, synchronen Event-Dispatchers im In-Process-Bereich.
