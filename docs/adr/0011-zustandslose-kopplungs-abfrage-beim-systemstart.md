# 11. Zustandslose Kopplungs-Abfrage und gerätespezifische Sicherheitskonfiguration beim Systemstart

Wir fragen den Kopplungs- und Ventilzustand beim Systemstart zustandslos über MQTT ab und konfigurieren das Sicherheits-Timeout gerätespezifisch.

## Kontext

Der **Bewässerungs-Daemon** benötigt den Zustand des **Ventils** (Kopplungs-Zeitstempel, Batterie, Signalstärke, Ventilzustand), um im **Telegram-Bot** den korrekten Status anzuzeigen und die manuelle oder automatisierte Bewässerung freizugeben.

Nach einem Neustart des Bewässerungs-Daemons gingen diese flüchtigen Zustandsdaten im Arbeitsspeicher verloren, wodurch das System fälschlicherweise meldete, das Ventil sei nicht gekoppelt, obwohl es im **Mittelweg-Dienst** (Zigbee2MQTT) weiterhin ordnungsgemäß registriert war.

Zudem traten beim Senden der Koppelungsfreigabe (`permit_join`) API-Kompatibilitätsprobleme mit neueren Versionen des Mittelweg-Dienstes auf, da das alte Format (`{"value": true}`) nicht mehr akzeptiert wurde. Das generische Sicherheits-Timeout via `inching_control` war ebenfalls inkompatibel mit dem Sonoff Hydro ONE Ventil, was zu Fehlermeldungen/Warnungen in den Logs des Mittelweg-Dienstes führte.

## Entscheidung

1. **Zustandslose MQTT-Abfrage beim Start:**
   Der Bewässerungs-Daemon persistiert den aktuellen Kopplungszustand absichtlich *nicht* in der lokalen SQLite-Datenbank. Stattdessen sendet der MQTT-Adapter bei jeder neuen Verbindung zum Broker automatisch eine Zustandsabfrage (`get`-Befehl) an das Status-Topic des Ventils (`zigbee2mqtt/garden_valve/get`). Der Mittelweg-Dienst antwortet darauf sofort mit den letzten bekannten Cached-Werten des Ventils, wodurch der Kopplungsstatus im Daemon sofort wiederhergestellt wird.

2. **Aktualisiertes permit_join-Payload-Format:**
   Die Ansteuerung des Koppelmodus (`permit_join`) wird auf das von modernen Zigbee2MQTT-Versionen erwartete zeitbasierte Format umgestellt (`{"time": PAIRING_TIMEOUT}` zum Aktivieren bzw. `{"time": 0}` zum Deaktivieren).

3. **Robustheit im Simulationsmodus:**
   Der Simulated-MQTT-Adapter wird dahingehend erweitert, dass er sowohl das alte als auch das neue Format transparent verarbeiten kann, um Offline-Tests ohne Code-Duplikation zu unterstützen.

4. **Gerätespezifische Sicherheits-Timeout-Konfiguration (Sonoff Hydro ONE):**
   Da das Sonoff Hydro ONE Ventil die generische `inching_control` Option des Mittelweg-Dienstes nicht unterstützt, steuern wir das Hardware-Sicherheits-Timeout (30 Minuten) direkt über das gerätespezifische Feld `manual_default_settings.fail_safe` (in Minuten) an, um Warnungen im Log des Mittelweg-Dienstes zu vermeiden.

## Konsequenzen

- **Single Source of Truth:** Der Mittelweg-Dienst bleibt die alleinige Quelle für Kopplungsdaten. Wir vermeiden Konsistenzprobleme zwischen der lokalen Datenbank und dem echten Zigbee-Netzwerk.
- **Nahtlose System-Restarts:** Ein Neustart des Bewässerungs-Daemons erfordert kein erneutes Anlernen des Ventils mehr; das System ist sofort nach dem Hochfahren wieder voll einsatzbereit.
- **API-Kompatibilität:** Das System ist vollkompatibel mit aktuellen Zigbee2MQTT-Versionen und konfiguriert das Sicherheits-Timeout fehlerfrei für das spezifische Ventilmodell.
