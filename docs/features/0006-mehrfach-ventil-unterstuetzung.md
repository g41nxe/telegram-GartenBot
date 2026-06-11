# Feature: Mehrfach-Ventil-Unterstützung und flexible Zeitpläne

## Problemstellung (Problem Statement)

Als Besitzer eines Gartens mit mehreren Bewässerungsbereichen (z. B. Rasen, Hochbeet und Gewächshaus) kann ich aktuell nur ein einziges physisches Ventil steuern und überwachen. Zeitpläne und manuelle Bewässerungsbefehle sind starr auf das Standard-Ventil ausgelegt. Ich kann nicht flexibel entscheiden, welche Bewässerungszonen über welche Zeitpläne oder bei einer manuellen Bewässerung angesteuert werden sollen, und ich sehe im Status sowie im täglichen Bericht keine Details über den Zustand aller meiner Ventile.

## Lösung (Solution)

Wir führen die Unterstützung für mehrere Ventile (Multi-Valve Support) im System ein. Über den Telegram-Bot können neue Ventile mit einem Wunschnamen gekoppelt werden. Bei der Erstellung von Zeitplänen sowie beim manuellen Starten einer Bewässerung kann der Benutzer festlegen, welche Ventile angesteuert werden sollen. Das System unterstützt sowohl eine sequentielle Ausführung (nacheinander, um den Wasserdruck zu schonen) als auch eine parallele Ausführung (gleichzeitig, mit individuellen Grenzwerten für den Kombinierten Guss). Alle Systemberichte, der Live-Status und die Bewässerungshistorie werden ventilgenau aufbereitet.

## User Stories

1. Als Benutzer möchte ich beim Hinzufügen eines Ventils (`/setup`) vorab einen verständlichen Wunschnamen (z. B. "Hochbeet") vergeben können, damit ich es später im Bot eindeutig identifizieren kann.
2. Als Benutzer möchte ich, dass ein neu gekoppeltes Ventil in Zigbee2MQTT automatisch eine eindeutige systeminterne Kennung erhält, um Namenskollisionen im Zigbee-Netzwerk auszuschließen.
3. Als Benutzer möchte ich beim Erstellen eines Zeitplanzwecks eine Liste meiner gekoppelten Ventile sehen und eines oder mehrere davon auswählen können.
4. Als Benutzer möchte ich bei der Zuweisung mehrerer Ventile zu einem Zeitplan entscheiden können, ob diese nacheinander (sequentiell) oder gleichzeitig (parallel) bewässert werden sollen.
5. Als Benutzer möchte ich, dass im parallelen Modus eines Zeitplans die eingestellte Dauer und Wassermenge als individuelles Limit für jedes einzelne Ventil gelten, um eine bedarfsgerechte Bewässerung sicherzustellen.
6. Als Benutzer möchte ich, dass im sequentiellen Modus eines Zeitplans die Grenzwerte nacheinander für jedes Ventil separat angewendet werden, um den Wasserdruck im System optimal zu nutzen.
7. Als Benutzer möchte ich beim Auslösen einer manuellen Bewässerung über den Bot mehrere Ventile auswählen und deren Ausführungsmodus (sequentiell oder parallel) bestimmen können.
8. Als Benutzer möchte ich im Live-Statusbericht (`/status`) den Verbindungsstatus, den Batteriestand, die Signalqualität (LQI) und den aktuellen Zustand (offen/geschlossen/Durchfluss) für jedes gekoppelte Ventil separat einsehen können.
9. Als Benutzer möchte ich im täglichen Statusbericht um 08:00 Uhr eine detaillierte Zusammenfassung der Bewässerungs-Statistiken (erfolgreiche/fehlgeschlagene Zyklen, Liter) pro Ventil erhalten.
10. Als Benutzer möchte ich bei Fehlern (z. B. einer Ventil-Anomalie oder einem schwachen Batteriestand) eine präzise Warnung erhalten, die angibt, welches konkrete Ventil betroffen ist.
11. Als Benutzer möchte ich, dass jeder Bewässerungslauf ventilgenau in der Historie protokolliert wird, damit ich den genauen Wasserverbrauch jeder einzelnen Zone nachvollziehen kann.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Datenbank-Schema**:
  - Eine neue Tabelle `valves` speichert alle gekoppelten Ventile (ID, benutzerdefinierter Name, eindeutiger MQTT-Name, Koppelungsstatus, Batteriestand, Signalstärke, letzter Signal-Zeitstempel und Anomalie-Zustand).
  - Eine n-zu-m Verknüpfungstabelle `schedule_valves` verknüpft Zeitpläne (`schedules`) mit den zugewiesenen Ventilen (`valves`).
  - Die Tabelle `schedules` erhält die Spalte `execution_mode` (Werte: `'sequential'` oder `'parallel'`).
  - Die Tabelle `watering_history` erhält die Spalte `valve_id` zur eindeutigen Zuordnung von Protokolleinträgen zu physischen Ventilen.
- **MQTT-Infrastruktur**:
  - Der MQTT-Adapter verwaltet den Zustand aller Ventile dynamisch in einer Key-Value-Struktur, indiziert nach dem MQTT-Topictitel.
  - Beim Starten des Daemons werden alle registrierten Ventile geladen und deren Status- sowie Steuerungs-Topics (z. B. `zigbee2mqtt/valve_<ieee_address>`) abonniert.
- **Guss-Steuerung (Watering Controller)**:
  - Der Kern-Controller wird so angepasst, dass er mehrere aktive Guss-Zyklen (Kombinierter Guss aus Zeit- und Volumenbegrenzung) gleichzeitig in einer internen Datenstruktur (`_active_cycles`) verwalten kann.
  - Im sequentiellen Modus steuert der Controller eine Warteschlange an Ventilen: Nach Abschluss des aktuellen Ventils wird das nächste in der Liste geöffnet.
  - Domain-Events werden um die ID oder den Namen des betroffenen Ventils erweitert, um die Ereignis-Kanal-Meldungen zu personalisieren.
- **Abwärtskompatibilität**:
  - Die Datenbankinitialisierung migriert bestehende Datenbanken automatisch: Sie legt ein Standardventil (`id=1`, Name `"garden_valve"`) an, verknüpft alle bestehenden Zeitpläne mit diesem Ventil und setzt die historische Bewässerung auf dieses Standardventil um.

## Test-Entscheidungen (Testing Decisions)

- **Testbare Nahtstellen (Seams)**:
  - Der `WateringController` wird als primäre funktionale Nahtstelle verwendet. Wir testen das sequentielle und parallele Starten/Stoppen von Guss-Zyklen unter Übergabe verschiedener Ventil-IDs und kontrollieren, ob die richtigen MQTT-Publish-Befehle generiert werden.
  - Der `EventBus` dient als Nahtstelle, um das Feuern der ventilgenauen Events (`WateringCycleStarted`, `WateringCycleCompleted`, etc.) bei Zeit- oder Volumenüberschreitung abzufangen und zu verifizieren.
  - Die Datenbank-Schnittstelle (`database.py`) dient als Nahtstelle zur Verifizierung der n-zu-m Abfragen und der korrekten Einzelprotokollierung in `watering_history`.
- **Referenzen**:
  - Existierende Integrationstests in `tests/test_irrigation.py` (z. B. Volumenlimit-Tests und Mock-Simulationen) werden als Vorlage verwendet und um Multi-Ventil-Testszenarien erweitert.

## Nicht im Leistungsumfang (Out of Scope)

- Dynamische Gruppierung von Ventilen in Zonen außerhalb des Zeitplan-Assistenten.
- Ein grafisches Dashboard zur Visualisierung der Flussraten-Diagramme mehrerer Ventile.
- Hardwareseitige Installation oder Funk-Reichweiten-Optimierung für zusätzliche Ventile.

## Weitere Anmerkungen (Further Notes)

- Das Aufwecken der Ventile vor dem täglichen Statusbericht (um aktuelle Werte abzufragen) erfolgt nacheinander für alle registrierten Ventile. Die Wartezeiten im Bot und Scheduler werden so optimiert, dass alle Antworten eingelesen werden können, bevor der Bericht generiert wird.
- **Ein-Ventil-Kompatibilität**: Wenn nur ein einziges Ventil im System registriert ist, verhält sich die Anwendung für den Endbenutzer identisch zum ursprünglichen Zustand. Im Telegram-Bot-Assistenten werden Auswahlschritte für Ventile und Ausführungsmodi übersprungen, sodass das System schlank und ohne unnötige Klicks bedient werden kann.

