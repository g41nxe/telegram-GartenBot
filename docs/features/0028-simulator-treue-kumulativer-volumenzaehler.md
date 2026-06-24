# Feature: Simulator-Treue für den kumulativen Gerätezähler (Volumen-Pfad)

## Problemstellung (Problem Statement)

Der Guss-Volumen-Bug (der kumulative Lebensdauer-Zähler des Ventils wurde als
Guss-Volumen interpretiert) ist live gegangen, obwohl die Testsuite grün war. Grund:
Der Simulationsmodus des Bewässerungs-Daemons (`SimulatedMqttAdapter`) bildet ein
**anderes Volumen-Modell** ab als die echte Hardware. Das simulierte Ventil meldet eine
Durchflussrate (`flow_rate`), das echte Sonoff SWV-ZFE meldet hingegen **keine**
Durchflussrate, sondern `real_time_irrigation_volume` — einen geräteweit kumulativen
Zähler, der durch unseren `state:ON`-Befehl nicht zurückgesetzt wird (siehe ADR 0007).

Dadurch lief in allen Tests stets der `_integrate_flow`-Fallback, während der reale
Produktionspfad der Guss-Steuerung (`_apply_device_volume` mit Baseline/Delta-Berechnung)
**null Integrationsabdeckung** hatte. Genau in dieser blinden Stelle saß der Bug.

## Lösung (Solution)

Der Simulationsmodus soll das **echte Geräteverhalten originalgetreu nachbilden**: einen
geräteweit kumulativen `real_time_irrigation_volume`-Zähler, der bei geöffnetem Ventil
hochzählt und über mehrere Güsse hinweg fortläuft (nicht pro Guss zurückgesetzt). Damit
durchlaufen die Integrationstests denselben Volumen-Pfad wie die Produktion — inklusive
der Baseline/Delta-Logik und der korrekten Guss-Volumen-Berechnung.

Das Ziel ist nicht nur Abdeckung, sondern ein **Regressionsnetz**, das genau diese
Bug-Klasse (kumulativer Altbestand wird fälschlich als Guss-Volumen gewertet) am
höchstgelegenen Seam dauerhaft fängt.

## User Stories

1. Als Entwickler möchte ich, dass der Simulationsmodus den kumulativen Gerätezähler des
   echten Ventils nachbildet, damit Tests den realen Volumen-Pfad statt nur des
   flow_rate-Fallbacks ausführen.
2. Als Entwickler möchte ich einen Integrationstest, der zwei aufeinanderfolgende Güsse
   simuliert und sicherstellt, dass der zweite Guss **nicht** sofort durch den
   übernommenen Zählerstand des ersten abgeschlossen wird (Reproduktion des Live-Bugs am
   Integrations-Seam).
3. Als Entwickler möchte ich, dass ein daemon-gesteuerter Guss bei einem vor dem Start
   bereits hohen Gerätezähler beim korrekten **Guss-Volumen (Delta)** abschließt und
   nicht beim Absolutwert.
4. Als Entwickler möchte ich, dass die in der Datenbank protokollierte Wassermenge eines
   simulierten Gusses dem tatsächlich geflossenen Guss-Volumen entspricht, nicht dem
   kumulativen Gerätestand.
5. Als Entwickler möchte ich, dass die bestehenden flow_rate-basierten Tests weiterhin
   grün bleiben, damit der Fallback-Pfad (für künftige Geräte mit echter Durchflussrate)
   abgedeckt bleibt und die Migration risikoarm ist.
6. Als Entwickler möchte ich den Simulationsmodus so steuern können, dass er wahlweise das
   kumulative Geräteverhalten oder das flow_rate-Verhalten zeigt, damit beide Volumen-Pfade
   gezielt testbar sind.
7. Als Betreiber möchte ich, dass `python -m daemon.main` im Offline-Modus möglichst
   realitätsnah arbeitet, damit ich Guss-Abläufe ohne Hardware glaubwürdig durchspielen kann.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Betroffenes Modul**: `SimulatedMqttAdapter` (Adapter-Schicht). Der Simulationsmodus
  emittiert künftig `ValveStatusReported`-Ereignisse mit einem fortlaufenden
  `irrigation_volume`, das bei geöffnetem Ventil mit ~5 L/min wächst und über
  Öffnen/Schließen hinweg **kumulativ** bestehen bleibt (geräteweiter Zustand des
  Simulators, nicht pro Zyklus). Der reale Zustand des Ventils (offen/geschlossen) steuert
  nur, ob der Zähler weiterläuft.
- **Rückwärtskompatibilität als zentrale Entscheidung**: Das echte Gerät meldet keine
  `flow_rate`; ein „voll originalgetreuer" Simulator würde `flow_rate=0` senden und damit
  die bestehenden flow_rate-Integrationstests brechen. Daher wird ein **Modus-Schalter** am
  Simulator eingeführt. Vorgeschlagene Vorgabe: bestehendes flow_rate-Verhalten bleibt
  Default (keine Bruchstelle), der kumulative Modus wird von den neuen Integrationstests
  **opt-in** aktiviert. (Alternative — Default umstellen und Bestandstests migrieren — ist
  bewusst die teurere Option und nur zu wählen, falls die Originaltreue im Offline-Betrieb
  Vorrang vor minimaler Diff-Größe haben soll. Hier abzustimmen.)
- **Keine Änderung der Produktionslogik**: Die Guss-Steuerung (`_apply_device_volume`,
  Baseline/Delta) wurde im vorausgehenden Bugfix bereits korrigiert (ADR 0007). Dieses
  Feature ändert ausschließlich den Simulator und ergänzt Tests — der Produktionspfad
  bleibt unangetastet.
- **Architektur**: Die Änderung bleibt vollständig in der Adapter-Schicht und respektiert
  die Regel, dass Adapter zustandslos bzgl. Domänenzustand sind — der kumulative Zähler ist
  reiner **Geräte-Simulationszustand** (Nachbildung der Hardware), kein Domänenzustand der
  Guss-Steuerung.
- **ADR-Bezug**: ADR 0007 beschreibt die Volumen-Quelle und den flow_rate-Fallback. Der
  Simulator-Abschnitt dort ist nach Umsetzung um den kumulativen Modus zu ergänzen.

## Test-Entscheidungen (Testing Decisions)

- **Was ein guter Test hier ist**: Geprüft wird ausschließlich beobachtbares Außenverhalten
  am höchsten Seam — also „welches Guss-Volumen wurde abgeschlossen / in die Historie
  geschrieben", nicht interne Felder des Zyklus. Der Test treibt den Daemon wie ein Nutzer
  (Guss starten) und beobachtet das Ergebnis über den Ereignis-Kanal bzw. die Datenbank.
- **Höchstgelegene Nahtstelle (bevorzugt, bestehend)**: Die Integrationstests in
  `tests/test_irrigation.py` erzwingen bereits via `mqtt_client.HAS_PAHO = False` in
  `setUpClass` den `SimulatedMqttAdapter` und verdrahten Guss-Steuerung und Scheduler. Diese
  bestehende Naht wird wiederverwendet — keine neue Naht nötig.
- **Zu testende Module**: Verhalten von `SimulatedMqttAdapter` (Emittiert kumulatives
  Volumen) gemeinsam mit der Guss-Steuerung, end-to-end über den Ereignis-Kanal.
- **Kern-Szenarien**:
  - Einzelner Guss mit vor dem Start bereits hohem Zählerstand → Abschluss beim Delta-Ziel,
    Historie protokolliert das Guss-Volumen (Delta), nicht den Absolutwert.
  - Zwei sequentielle Güsse → der zweite Guss startet bei 0 Guss-Volumen trotz hohem
    Altbestand und löst das Volumenlimit nicht sofort aus (direkte Reproduktion des
    Live-Bugs am Integrations-Seam).
- **Vorarbeiten/Referenzen**: Wiring-Muster aus `setUpClass` in `tests/test_irrigation.py`;
  die bereits vorhandenen Unit-Tests des Baseline/Delta-Verhaltens in
  `tests/core/test_watering_controller.py` dienen als fachliche Referenz für die erwarteten
  Werte.
- **Coverage**: Darf nicht regredieren (`scripts/run_coverage.sh` bzw. `.ps1`). TDD:
  Failing Test zuerst.

## Nicht im Leistungsumfang (Out of Scope)

- Die Produktions-Volumenlogik (Baseline/Delta in der Guss-Steuerung) — bereits umgesetzt
  und über Unit-Tests abgesichert (ADR 0007).
- Der flow_rate-Fallback-Pfad selbst — bleibt für potenzielle künftige Geräte erhalten und
  wird weiterhin von den bestehenden flow_rate-Tests abgedeckt.
- Erfassung von manuellem Gießen **ohne** den Bewässerungs-Daemon (Knopf am Ventil,
  Hersteller-App) im Tagesbericht — eigenständiges Feature, baut aber auf dem fortlaufenden
  Zähler-Tracking auf.
- Änderungen an Telegram-Nachrichten — dieses Feature ist rein test-/simulationsseitig.

## Weitere Anmerkungen (Further Notes)

- Dieses Ticket ist das vereinbarte Folge-Issue aus dem Guss-Volumen-Bugfix. Es adressiert
  die **eigentliche Ursache**, warum kein Test den Bug gefangen hat: die Asymmetrie zwischen
  Simulator (flow_rate) und Hardware (kumulatives Volumen).
- Es existiert zusätzlich ein Claude-Code-Hintergrund-Task-Chip mit derselben Aufgabe; dieses
  Feature-Dokument ist die maßgebliche, versionierte Fassung.
- Wurde mit `/to-feature` aus dem Konversationskontext synthetisiert; ein Interview fand
  nicht statt.
