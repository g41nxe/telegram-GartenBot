# 15. Unterstützung mehrerer Ventile und flexible Zeitpläne

Wir erweitern das System zur Steuerung mehrerer Ventile (Multi-Valve Support), ermöglichen die Zuweisung mehrerer Ventile zu einem Zeitplan (n-zu-m Beziehung) mit sequentieller oder paralleler Ausführung und passen den Status und die Berichte entsprechend an.

## Kontext

Bisher unterstützte das System nur ein einzelnes physisches Ventil mit dem festen MQTT-Topic `zigbee2mqtt/garden_valve`. Die Statusabfragen, Zeitpläne und die manuelle Bewässerung waren fest auf dieses eine Ventil ausgelegt. Um größere Gärten mit verschiedenen Bewässerungszonen (z. B. Rasen, Hochbeet, Gewächshaus) zu versorgen, müssen mehrere Ventile unabhängig oder gemeinsam gesteuert, protokolliert und überwacht werden können.

## Entscheidung

1. **Datenbank-Erweiterungen**:
   * Wir führen eine neue Tabelle `valves` ein, um gekoppelte Ventile dynamisch zu speichern (mit Spalten für `id`, `name`, `mqtt_name`, `is_paired`, `battery`, `linkquality`, `last_update`, `valve_abnormal_state`).
   * Wir führen eine n-zu-m Beziehung zwischen Zeitplänen und Ventilen über die neue Verknüpfungstabelle `schedule_valves` (mit `schedule_id` und `valve_id`) ein.
   * Die Tabelle `schedules` wird um die Spalten `execution_mode` (TEXT: 'sequential' oder 'parallel') ergänzt.
   * In der Tabelle `watering_history` ergänzen wir die Spalte `valve_id` (FOREIGN KEY), um jeden Bewässerungslauf ventilgenau zu protokollieren.

2. **Koppelungs-Ablauf (Pairing)**:
   * Bei `/setup` (bzw. "Ventil koppeln") fragen wir den Benutzer zuerst nach einem Wunschnamen (z. B. "Rasen").
   * Nach erfolgreichem Join benennen wir das Ventil in Zigbee2MQTT auf den eindeutigen Systemnamen `valve_<ieee_address>` um.
   * Das Ventil wird mit seinem Wunschnamen und dem MQTT-Topic `zigbee2mqtt/valve_<ieee_address>` in der Datenbank registriert.

3. **Guss-Steuerung (Watering Controller)**:
   * Der `WateringController` wird so erweitert, dass er mehrere aktive Bewässerungszyklen parallel verwalten kann (z. B. in einem Dictionary `self._active_cycles: Dict[int, Dict[str, Any]]`, indiziert nach `valve_id`).
   * Im **sequentiellen Modus** werden die Ventile nacheinander geschaltet. Nach Beendigung des einen Ventils startet der Controller automatisch das nächste Ventil der Sequenz.
   * Im **parallelen Modus** werden alle zugewiesenen Ventile gleichzeitig geöffnet. Die Grenzwerte des Kombinierten Gusses (Dauer und Volumen) gelten individuell pro Ventil.

4. **Präsentationsschicht (Telegram-Bot)**:
   * Die `/status`- und `/report`-Nachrichten zeigen den Zustand, die Batterie, Signalstärke und das letzte Update für jedes registrierte Ventil übersichtlich an.
   * Der manuelle Bewässerungs-Assistent erlaubt die Auswahl mehrerer Ventile und fragt nach dem Ausführungsmodus (sequentiell/parallel) sowie den Grenzwerten (Dauer/Volumen).
   * **Ein-Ventil-Fallstrick/Vereinfachung**: Befindet sich nur ein einziges Ventil im System, werden die Schritte zur Ventilauswahl und zum Ausführungsmodus im Dialog-Assistenten des Telegram-Bots automatisch übersprungen (Auto-Selektion), sodass der Dialog für den Benutzer genauso kurz und einfach bleibt wie zuvor.

## Konsequenzen

* Höhere Flexibilität und Skalierbarkeit für größere Gartenlayouts.
* Abwärtskompatibilität und Einfachheit: Existierende Datenbanken werden migriert. Es wird ein Standardventil `garden_valve` angelegt, und bestehende Zeitpläne werden diesem zugeordnet.
* Befindet sich nur ein Ventil im System, läuft die Anwendung komplett ohne Mehraufwand oder zusätzliche Abfrageschritte im Bot-Interface.
* Erhöhte Komplexität im `WateringController` zur Verwaltung mehrerer paralleler oder sequentieller Abläufe.
