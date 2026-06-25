# 32. Unerwartete Ventilöffnung: melden statt schließen

Wir erkennen zur Laufzeit, wenn ein Ventil geöffnet wird, ohne dass die Guss-Steuerung
einen aktiven Guss dafür führt (**Unerwartete Ventilöffnung**), und **benachrichtigen den
Benutzer per Telegram-Bot — ohne das Ventil automatisch zu schließen**.

## Kontext

Wird ein Ventil am Bewässerungs-Daemon vorbei geöffnet (Knopf am Ventil, Hersteller-App,
anderer MQTT-Client), bleibt das im laufenden Betrieb bisher unbemerkt. Die einzige
bestehende Erkennung ist die Sicherheits-Schließung beim Daemon-Start (ADR 0007), die genau
einmal beim Hochfahren greift.

Naheliegend wäre, das Verhalten der Start-Sicherheit (automatisch schließen) auch auf den
Laufzeitfall zu übertragen. Dagegen sprechen drei Punkte:

1. **Es existiert bereits ein Hardware-Flutschutz.** Das Sonoff-Ventil schließt über das
   Fail-Safe (`SAFETY_TIMEOUT_MINUTES`, Standard 30 Min, via
   `manual_default_settings.fail_safe`, ADR 0005) physisch von selbst — ganz ohne Daemon.
   Eine versehentlich offene Leitung läuft also ohnehin höchstens diese Schutzdauer.
2. **Die Start-Sicherheit hat einen anderen Grund.** Beim Start kennt der Daemon die
   Vorgeschichte nicht (Crash, Stromausfall — Ventil evtl. lange offen), daher ist „auf
   sicher zurücksetzen" dort richtig. Zur Laufzeit schaut der Daemon zu und die Hardware
   deckelt — ein Reset ist nicht nötig.
3. **Automatisches Schließen würde absichtliche Handbedienung sabotieren.** Bewusstes
   Gießen direkt am Gerät würde in Sekunden unterbunden.

## Entscheidung

- **Nur melden, nicht schließen.** Bei einer unerwarteten Ventilöffnung veröffentlicht die
  Guss-Steuerung das Ereignis `UnexpectedValveOpened`; der Telegram-Bot benachrichtigt. Beim
  Wieder-Schließen folgt `UnexpectedValveResolved` (Entwarnung). Der Hardware-Sicherheits-Timeout
  bleibt der Flutschutz.
- **Erkennung in der Guss-Steuerung (Core).** Sie kennt die aktiven Zyklen und verarbeitet
  `ValveStatusReported` bereits. Sie sendet keine Telegram-Nachrichten, sondern publiziert
  nur die Ereignisse über den Ereignis-Kanal (Architektur-Regel: ereignisgesteuerte
  Seiteneffekte). Der `wish_name` wird erst in der UI-Schicht aufgelöst; die Ereignisse
  tragen nur den `mqtt_name`.
- **Flankenerkennung statt Karenzzeit.** Gemeldet wird nur beim echten Übergang
  *Nicht-ON → ON* ohne aktiven Zyklus. Da der Daemon beim regulären Schließen erst `OFF`
  sendet und dann den Zyklus entfernt, das Ventil aber noch kurz `ON` nachmeldet, verhindert
  die Flanke (letzter Zustand war `ON`) den Fehlalarm — ohne getunte Konstante.
- **Cold-Start-Regel.** Ist der zuletzt bekannte Zustand unbekannt (noch kein Report
  gesehen), wird **nicht** gemeldet, sondern nur aufgezeichnet. Das verhindert ein
  Doppelfeuer mit der Start-Sicherheitsprüfung beim Boot. Die Start-Sicherheit bleibt
  unverändert.
- **Zustand im Speicher.** Der Episode-/Zustands-Merker liegt pro Ventil im Speicher der
  Guss-Steuerung (nicht in der DB persistiert wie der Inaktivitäts-Watchdog) — eine offene
  Leitung ist eine „Jetzt"-Bedingung, und der Boot-Zustand ist durch die Start-Sicherheit
  abgedeckt.
- **Abschaltbar.** Ein Schalter `UNEXPECTED_VALVE_ALERT_ENABLED` (garden.conf, Default an)
  erlaubt das Deaktivieren für Nutzer, die regelmäßig von Hand gießen.

## Konsequenzen

- Flutschutz bleibt durch die Hardware gewährleistet; die Software informiert nur, damit der
  Benutzer schneller als die Schutzdauer reagieren kann.
- Bewusstes Handgießen am Gerät wird nicht unterbunden.
- Inkonsistenz zur Start-Sicherheit (die schließt) ist bewusst und durch die unterschiedliche
  Ausgangslage begründet.
- Automatisches Schließen mit Bestätigungs-Button („Wieder öffnen") bleibt eine spätere
  Option, sobald aktionsfähige Benachrichtigungen (Feature 0018) verfügbar sind.
- Bei Funk-Flackern (ON/OFF/ON) kann die Episode mehrfach anschlagen; ein Debounce auf die
  Entwarnung ist als spätere Verfeinerung vorgemerkt.
