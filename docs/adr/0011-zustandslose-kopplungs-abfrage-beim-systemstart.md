# 11. Zustandslose Kopplungs-Abfrage beim Systemstart

Wir fragen den Kopplungs- und Ventilzustand beim Systemstart zustandslos über MQTT ab, anstatt ihn in der lokalen Datenbank zu speichern.

## Kontext

Der **Bewässerungs-Daemon** benötigt den Zustand des **Ventils** (Kopplungs-Zeitstempel, Batterie, Signalstärke, Ventilzustand), um im **Telegram-Bot** den korrekten Status anzuzeigen und die manuelle oder automatisierte Bewässerung freizugeben.

Nach einem Neustart des Bewässerungs-Daemons gingen diese flüchtigen Zustandsdaten im Arbeitsspeicher verloren, wodurch das System fälschlicherweise meldete, das Ventil sei nicht gekoppelt, obwohl es im **Mittelweg-Dienst** (Zigbee2MQTT) weiterhin ordnungsgemäß registriert war.

Zudem traten beim Senden der Koppelungsfreigabe (`permit_join`) API-Kompatibilitätsprobleme mit neueren Versionen des Mittelweg-Dienstes auf, da das alte Format (`{"value": true}`) nicht mehr akzeptiert wurde.

## Entscheidung

1. **Zustandslose MQTT-Abfrage beim Start:**
   Der Bewässerungs-Daemon persistiert den aktuellen Kopplungszustand absichtlich *nicht* in der lokalen SQLite-Datenbank. Stattdessen sendet der MQTT-Adapter bei jeder neuen Verbindung zum Broker automatisch eine Zustandsabfrage (`get`-Befehl) an das Status-Topic des Ventils (`zigbee2mqtt/garden_valve/get`). Der Mittelweg-Dienst antwortet darauf sofort mit den letzten bekannten Cached-Werten des Ventils, wodurch der Kopplungsstatus im Daemon sofort wiederhergestellt wird.

2. **Aktualisiertes permit_join-Payload-Format:**
   Die Ansteuerung des Koppelmodus (`permit_join`) wird auf das von modernen Zigbee2MQTT-Versionen erwartete zeitbasierte Format umgestellt (`{"time": PAIRING_TIMEOUT}` zum Aktivieren bzw. `{"time": 0}` zum Deaktivieren).

3. **Robustheit im Simulationsmodus:**
   Der Simulated-MQTT-Adapter wird dahingehend erweitert, dass er sowohl das alte als auch das neue Format transparent verarbeiten kann, um Offline-Tests ohne Code-Duplikation zu unterstützen.

## Konsequenzen

- **Single Source of Truth:** Der Mittelweg-Dienst bleibt die alleinige Quelle für Kopplungsdaten. Wir vermeiden Konsistenzprobleme zwischen der lokalen Datenbank und dem echten Zigbee-Netzwerk.
- **Nahtlose System-Restarts:** Ein Neustart des Bewässerungs-Daemons erfordert kein erneutes Anlernen des Ventils mehr; das System ist sofort nach dem Hochfahren wieder voll einsatzbereit.
- **API-Kompatibilität:** Das System ist kompatibel mit aktuellen Zigbee2MQTT-Versionen.
