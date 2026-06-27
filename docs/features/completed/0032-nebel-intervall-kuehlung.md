# Feature: Nebel-Intervall (Terrassen-Kühlung)

## Problemstellung (Problem Statement)

An heißen Tagen wird es auf der Terrasse unangenehm warm. Der Benutzer möchte eine
Nebeldüse betreiben, die in regelmäßigen Abständen kurz Wasser abgibt und so die Umgebung
abkühlt. Das bestehende System kann ausschließlich **bewässern** (Kombinierter Guss: ein
einmaliger Lauf, begrenzt durch Zeit *und* Volumen, mit Regen-Überspringlogik und
Defekterkennung). Für eine intermittierende Kühl-Nebelung passt dieses Modell nicht:
Volumen ist bedeutungslos, „zu wenig Durchfluss = Defekt" würde dauernd fehlschlagen, und
gebraucht wird kein einmaliger Guss, sondern ein über Stunden wiederholter, sekundenkurzer
Stoß.

## Lösung (Solution)

Ein neues **Nebel-Intervall**: eine wiederkehrende Kühlfunktion, die ein **eigenes zweites
Ventil** in regelmäßigen Abständen sekundenkurz öffnet (**Nebelstoß**) und dazwischen
pausiert. Es ist mechanisch ein neuer **Zeitplan-Modus** (`mode = "nebel"`), läuft aber über
eine eigene Engine (**Nebel-Steuerung**) und ist begrifflich klar von der Bewässerung
getrennt — ohne Volumenlimit, ohne Regen-Überspringlogik, ohne Mindest-Flussrate-Defekterkennung.

Der Benutzer steuert es auf zwei Wegen über den Telegram-Bot:
1. **Geplant** über ein **Nebel-Fenster** (Start- bis Endzeit an gewählten Wochentagen).
2. **Sofort-Nebel** — ein manuell gestartetes Nebel-Intervall mit gewählter Laufzeit und
   konfigurierter Maximaldauer als Backstop.

Siehe ADR 0033 für die Entscheidungsbegründung; CONTEXT.md für die Begriffe.

## User Stories

1. Als Benutzer möchte ich ein zweites Ventil für die Nebeldüse über `/setup` koppeln, damit
   die Nebel-Funktion eine eigene Hardware ansteuert, unabhängig vom Garten-Ventil.
2. Als Benutzer möchte ich einen geplanten Nebel-Zeitplan anlegen (Wochentage, Startzeit,
   Endzeit, ON-Sekunden je Nebelstoß, Pause in Minuten), damit die Terrasse an heißen
   Nachmittagen automatisch gekühlt wird.
3. Als Benutzer möchte ich, dass das Nebel-Intervall innerhalb seines Fensters den
   ON/Pause-Takt automatisch wiederholt, ohne dass ich eingreifen muss.
4. Als Benutzer möchte ich, dass der Nebel zur konfigurierten Endzeit zuverlässig stoppt,
   damit nach Sonnenuntergang nicht weiter genebelt wird.
5. Als Benutzer möchte ich einen Nebel-Zeitplan ansehen, bearbeiten, aktivieren/deaktivieren
   und löschen können — analog zu den bestehenden Bewässerungs-Zeitplänen.
6. Als Benutzer möchte ich einen **Sofort-Nebel** per Telegram starten und dabei eine
   Laufzeit wählen (z. B. 30/60/120 Min), damit ich spontan kühlen kann, wenn es heiß ist.
7. Als Benutzer möchte ich einen laufenden Sofort-Nebel jederzeit manuell stoppen können.
8. Als Benutzer möchte ich, dass ein Sofort-Nebel nach Ablauf der gewählten Laufzeit — oder
   spätestens nach der konfigurierten Maximaldauer — automatisch stoppt, damit ein vergessener
   Nebel nicht stundenlang läuft.
9. Als Benutzer möchte ich, dass das Nebel-Ventil bei einem Daemon-Absturz mitten im Stoß
   durch einen kurzen Hardware-Sicherheits-Timeout (statt 30 Min) schnell schließt, damit kein
   Dauernebel entsteht.
10. Als Benutzer möchte ich, dass ein laufendes geplantes Nebel-Fenster nach einem
    Daemon-Neustart von selbst wieder aufnimmt (zustandslos aus dem Zeitplan abgeleitet).
11. Als Benutzer möchte ich, dass ein Sofort-Nebel bei einem Daemon-Neustart verfällt (nicht
    persistiert), weil er eine spontane „Jetzt"-Aktion ist.
12. Als Benutzer möchte ich, dass das System einen Nebelstoß **nicht** als Unerwartete
    Ventilöffnung meldet, damit ich nicht bei jedem Stoß einen Fehlalarm bekomme.
13. Als Benutzer möchte ich, dass Regen das Nebel-Intervall **nicht** unterbricht, weil die
    Steuerung rein über das Zeitfenster erfolgt.
14. Als Benutzer möchte ich im Tagesbericht eine kompakte Zusammenfassung sehen, ob/wann und
    wie lange genebelt wurde (Fenster, Dauer, Anzahl Stöße), ohne dass jeder einzelne Stoß
    den Bericht flutet.
15. Als Benutzer möchte ich, dass eine laufende Bewässerung (Garten-Ventil) und ein
    Nebel-Intervall (Nebel-Ventil) gleichzeitig laufen können, da es zwei getrennte Ventile sind.
16. Als Benutzer möchte ich eine Telegram-Benachrichtigung bei Beginn und Ende eines
    Nebel-Fensters, damit ich den Betrieb nachvollziehen kann.
17. Als Benutzer möchte ich die Standard-ON-Sekunden, Standard-Pause und Sofort-Nebel-Maximaldauer
    in der Konfiguration anpassen können.

## Implementierungs-Entscheidungen (Implementation Decisions)

**Hardware & Begriffe**
- Das Nebel-Intervall steuert ein eigenes Sonoff-Hydro-ONE-Ventil (eigene IEEE-ID/Wunschname,
  regulär per Ventil-Kopplung registriert). Die Durchfluss-Telemetrie wird ignoriert.
- Begriffe gemäß CONTEXT.md: **Nebel-Intervall** (Plan/Modus), **Nebelstoß** (einzelner
  ON-Stoß), **Nebel-Steuerung** (Engine), **Nebel-Fenster** (geplanter Zeitraum),
  **Sofort-Nebel** (manuell). Niemals „Bewässerung"/„Guss" für die Nebel-Aktivität.

**Neue Kernkomponente: Nebel-Steuerung (core/)**
- Pendant zur Guss-Steuerung (`WateringController`): eigene Klasse in `core/`, eigener
  `threading.Timer`-Loop für sekundengenaues Timing, injizierte `publish_fn` (ADR 0017),
  Anbindung an den Ereignis-Kanal. Keine I/O im Core.
- Verantwortung: einen ON/Pause-Burst-Zyklus auf einem Ventil fahren, bis ein Endzeitpunkt
  (Fenster-Ende oder Sofort-Nebel-Laufzeit) erreicht ist; danach Ventil sicher schließen.
- Sie „beansprucht" das bediente Ventil für die gesamte Laufzeit (inkl. Pausen) und stellt
  diese Beanspruchung der Guss-Steuerung bereit, damit deren Unerwartete-Ventilöffnung-Erkennung
  (ADR 0032) den Nebelstoß nicht als Fehlalarm wertet.
- Schnittstelle (Prosa): Starten eines Intervalls (Ventil, ON-Sekunden, Pause-Minuten,
  Endzeitpunkt, Quelle), Stoppen, Abfrage des aktiven Zustands.

**Kopplung Nebel-Steuerung ↔ Guss-Steuerung**
- Die Guss-Steuerung erhält eine schmale Schnittstelle, um eine Menge „beanspruchter" Ventile
  von der Unerwartete-Ventilöffnung-Erkennung auszunehmen. Dies ist die einzige Kopplung
  zwischen beiden Engines. Die Beanspruchung gilt für die volle Fensterdauer, damit auch der
  Flankenwechsel OFF→ON des nächsten Stoßes nicht anschlägt.

**Datenbank-Schema (schedules)**
- Erweiterung der Tabelle `schedules` um:
  - `mode TEXT DEFAULT 'watering'` — `'watering'` | `'nebel'`.
  - `end_time TEXT` — Endzeit des Nebel-Fensters (Format `HH:MM`).
  - `on_seconds INTEGER` — Dauer eines Nebelstoßes in Sekunden.
  - `pause_minutes INTEGER` — Pause zwischen Nebelstößen in Minuten.
- Migration via `ALTER TABLE … ADD COLUMN` in `database.init_db()`, gewickelt in
  `try/except OperationalError` (kein Migrations-Framework). Bestehende Zeitpläne sind
  implizit `mode = 'watering'`.
- Ventil-Zuordnung erfolgt über den bestehenden `schedule_valves`-Mechanismus; ein
  Nebel-Zeitplan referenziert sein Nebel-Ventil darüber.
- CRUD-Funktionen (`add_schedule`/`update_schedule`/`get_schedules`) werden um die neuen Felder
  erweitert; die Volumen-Felder bleiben für Nebel-Zeitpläne ungenutzt (0).

**Scheduler**
- Der Scheduler-Loop unterscheidet beim Auslösen nach `mode`:
  - `watering`: bestehender Pfad (`_trigger_scheduled_watering`, unverändert).
  - `nebel`: Start eines Nebel-Fensters über die Nebel-Steuerung; **kein** Wetter-Check, **keine**
    Volumen-/Skalierungslogik.
- Das Nebel-Fenster wird **zustandslos** behandelt: Der Scheduler prüft je Minute, ob die
  aktuelle Zeit innerhalb `[time, end_time)` eines aktiven Nebel-Zeitplans liegt, und stellt
  sicher, dass die Nebel-Steuerung für dieses Fenster läuft (idempotentes Anstoßen). So nimmt
  ein laufendes Fenster nach einem Neustart von selbst wieder auf. Zur `end_time` wird das
  Fenster beendet.

**Telegram-UI**
- Zeitplan-Wizard: neuer Verzweigungspunkt „Bewässerung" vs. „Nebel". Im Nebel-Zweig werden
  Endzeit, ON-Sekunden und Pause-Minuten abgefragt (statt Dauer/Volumen).
- Zeitplan-Liste/-Bearbeitung kennzeichnet Nebel-Zeitpläne sichtbar und zeigt die passenden
  Felder.
- **Sofort-Nebel**: neuer Befehl/Button zum Starten mit Laufzeit-Auswahl (Buttons, z. B.
  30/60/120 Min) und ein Stopp-Button. Standard-Takt aus der Konfiguration.
- Benachrichtigungen bei Fenster-Start und Fenster-Ende.
- Alle neuen/änderten Nachrichten sind in `docs/design/telegram-nachrichten.html` zu pflegen
  (Regel `telegram_messages.md`).

**Ereignisse & Protokollierung**
- Neue Ereignisse für Fenster-Beginn und Fenster-Ende (Quelle z. B. `"nebel"` /
  `"nebel_manual"`), veröffentlicht über den Ereignis-Kanal. Einzelne Nebelstöße erzeugen
  **kein** Ereignis und werden **nicht** protokolliert.
- Der `DatabaseLoggerAdapter` schreibt pro Fenster je einen Beginn/Ende-Eintrag (kompakt; ggf.
  in `watering_history` mit eigenem `source`-Tag oder einer dedizierten Ablage — Detail im Plan).
- Der Tagesbericht erhält eine Zusammenfassungszeile, wenn im Berichtszeitraum genebelt wurde.

**Konfiguration (garden.conf)**
- Neue Werte: Standard-`on_seconds`, Standard-`pause_minutes`, Sofort-Nebel-Maximaldauer
  (Backstop), Nebel-Ventil-Fail-Safe-Dauer. Konkrete Defaults werden im Plan festgelegt
  (Vorschläge: 20 s ON, 5 min Pause, 120 min Sofort-Cap, 90 s Fail-Safe).
- Der kurze Hardware-Fail-Safe wird über den Mittelweg-Dienst pro Gerät gesetzt
  (`manual_default_settings.fail_safe`); Detail/Verdrahtung im Plan.

## Test-Entscheidungen (Testing Decisions)

Ein guter Test prüft hier **externes Verhalten** an der höchstmöglichen Nahtstelle, nicht
Implementierungsdetails (Timer-Interna, private Felder).

- **Nebel-Steuerung (höchste Unit-Nahtstelle):** Referenzmuster ist
  `tests/core/test_watering_controller.py` — `EventBus` + `SimulatedMqttAdapter` +
  Komponente unter Test. Verifiziert über den simulierten Ventilzustand und veröffentlichte
  Ereignisse: Ventil geht ON beim Stoß, OFF in der Pause, Fenster endet zur Endzeit, Ventil
  ist danach sicher OFF. Das sekundengenaue Timing wird über eine injizierbare/abstrahierte
  Zeit- bzw. Timer-Nahtstelle deterministisch getrieben (analog zu `_integrate_flow`, das im
  Test direkt aufgerufen wird, statt echte Sekunden zu warten) — keine `sleep`-basierten Tests.
- **Ventil-Beanspruchung / kein Fehlalarm:** Test, dass ein Nebelstoß (ON ohne aktiven
  Guss-Zyklus) **kein** `UnexpectedValveOpened` auslöst, solange das Ventil beansprucht ist —
  erweitert die bestehenden Unerwartete-Ventilöffnung-Tests in
  `tests/core/test_watering_controller.py`.
- **Scheduler-Integration:** `tests/test_irrigation.py` ist die Integrationsnahtstelle
  (Setup der Verdrahtung in `setUpClass` als Referenz). Verifiziert: ein Nebel-Zeitplan löst
  ein Nebel-Fenster aus (kein Wetter-Check), ein Bewässerungs-Zeitplan bleibt unberührt, und
  die zustandslose Wiederaufnahme („Zeit liegt im Fenster" → Nebel-Steuerung läuft).
- **Datenbank:** `tests/adapters/test_database.py` — neue Felder werden korrekt
  geschrieben/gelesen; Migration auf einer Alt-DB ohne die Spalten schlägt nicht fehl
  (`mode` defaultet auf `'watering'`).
- **Telegram-UI:** `tests/ui/test_telegram_ui.py` (Wizard-Verzweigung, Sofort-Nebel-Buttons,
  Stopp) — Referenz: bestehende Wizard-Tests. Es wird das erzeugte Nachrichten-/Button-Verhalten
  geprüft, nicht der HTTP-Transport.
- **Tagesbericht:** `tests/adapters/test_daily_report.py` — die Zusammenfassungszeile erscheint
  nur, wenn im Zeitraum genebelt wurde.

**TDD-Regel:** Vor jeder neuen Logik ein fehlschlagender Test; Coverage darf nicht regredieren.

## Nicht im Leistungsumfang (Out of Scope)

- **Temperatur-Gating** (nur nebeln, wenn eine Mindesttemperatur überschritten ist) — bewusst
  verschoben; im Fenster wird unbedingt genebelt.
- **Regen-Pause** des Nebel-Intervalls — bewusst entkoppelt; Regen beeinflusst den Nebel nicht.
- **Persistenz eines Sofort-Nebels** über einen Daemon-Neustart hinweg.
- **Volumen-/Durchfluss-Auswertung** für die Nebeldüse (Telemetrie wird ignoriert).
- **Eigenständige Defekt-/Verstopfungserkennung** der Nebeldüse.
- **Mehrere Nebel-Ventile pro Fenster / parallele Nebel-Düsen** — zunächst ein Nebel-Ventil je
  Zeitplan (technisch über `schedule_valves` später erweiterbar).

## Weitere Anmerkungen (Further Notes)

- Entscheidungsbasis: ADR 0033 (`docs/adr/0033-nebel-intervall-kuehlung-als-zeitplan-modus.md`).
- Begriffe: CONTEXT.md (Nebel-Intervall, Nebelstoß, Nebel-Steuerung, Nebel-Fenster, Sofort-Nebel).
- Architektur-Leitplanken: zustandslose Adapter, ereignisgesteuerte Seiteneffekte (ADR 0008),
  Callable-Port-Injektion (ADR 0017), zustandsloser Start (ADR 0011).
- Die konkreten Default-Zahlenwerte (ON-Sekunden, Pause, Sofort-Cap, Fail-Safe) werden im
  Implementierungsplan finalisiert.
