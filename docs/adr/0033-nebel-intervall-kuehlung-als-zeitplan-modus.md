# 33. Nebel-Intervall: intermittierende Kühlung als eigener Zeitplan-Modus

Wir führen das **Nebel-Intervall** ein — eine wiederkehrende Kühlfunktion, die ein
dediziertes Ventil in regelmäßigen Abständen sekundenkurz öffnet, um über eine Nebeldüse
die Terrasse abzukühlen. Es ist mechanisch ein neuer **Zeitplan-Modus** (`mode = "nebel"`),
läuft aber über eine eigene Engine (**Nebel-Steuerung**) und ist begrifflich klar vom
Kombinierten Guss getrennt.

## Kontext

Der Wunsch: „In regelmäßigen Abständen für eine definierte Zeit das Wasser angehen lassen",
um eine Nebeldüse zur Abkühlung zu steuern. Das bestehende Modell dreht sich vollständig um
den **Kombinierten Guss** (ADR 0007): ein einmaliger Lauf, begrenzt durch Zeit *und*
Volumen, mit Regen-Überspringlogik, Volumen-Integration und Mindest-Flussrate-Defekterkennung.

Für eine Kühl-Nebelung passt dieses Modell schlecht: Volumen ist bedeutungslos, „zu wenig
Durchfluss = Defekt" würde dauernd fehlschlagen, und der Lauf ist kein einmaliger Guss,
sondern ein über Stunden wiederholter, sekundenkurzer Burst (ON 20 s / Pause 5 min o. ä.).

## Entscheidung

- **Eigene Hardware.** Das Nebel-Intervall steuert ein **eigenes zweites Ventil** (Sonoff
  Hydro ONE, eigene IEEE-ID/Wunschname, regulär über `/setup` gekoppelt). Die
  Durchfluss-Telemetrie des Ventils wird ignoriert.
- **Mechanisch ein Zeitplan-Modus, begrifflich ein eigenes Konzept.** Der Zeitplan erhält
  ein Feld `mode` (`"watering"` | `"nebel"`). Die Sprache trennt aber sauber: Die erzeugte
  Aktivität heißt **Nebel-Intervall** / **Nebelstoß**, nie „Bewässerung"/„Guss" (CONTEXT.md).
  Es gibt **kein** Volumenlimit, **keine** Regen-Überspringlogik, **keine**
  Mindest-Flussrate-Defekterkennung.
- **Sekundengenauer Takt in eigener Engine.** Der 1-Minuten-Scheduler-Takt reicht für
  Sekunden-Bursts nicht. Der ON/Pause-Loop lebt in einer neuen Kernkomponente
  **Nebel-Steuerung** — Pendant zur Guss-Steuerung: eigener `threading.Timer`-Loop,
  injizierte `publish_fn` (ADR 0017), offline über den `SimulatedMqttAdapter` testbar. Der
  Scheduler startet/beendet nur das Fenster; den Burst fährt die Nebel-Steuerung.
- **Tagesfenster aus Start- und Endzeit.** Der Zeitplan erhält neben `time` (Start) eine
  `end_time`, dazu `on_seconds` (Nebelstoß-Dauer) und `pause_minutes`. Während des
  **Nebel-Fensters** wiederholt sich der Takt; zur Endzeit stoppt er.
- **Keine Temperatur-, keine Regenlogik.** Im Fenster wird unbedingt genebelt. Bewusst
  einfach und robust (kein harter Sensor-Zwang): Steuerung allein über die Fensterzeiten.
  Regen beeinflusst das Nebel-Intervall **nicht** — es ist von der Bewässerungs-/Regenlogik
  (RainSensorMeasured → `interrupt_watering`) entkoppelt.
- **Ventil-Beanspruchung statt Fehlalarm.** Jeder Nebelstoß ist eine Flanke *Nicht-ON → ON*
  ohne aktiven Guss-Zyklus und würde sonst als **Unerwartete Ventilöffnung** (ADR 0032)
  gemeldet. Daher „beansprucht" die Nebel-Steuerung das Ventil für die gesamte Fensterdauer;
  die Guss-Steuerung überspringt für beanspruchte Ventile die Unerwartete-Ventilöffnung-
  Erkennung. Die Beanspruchung umfasst auch die Pausen (Ventil OFF), damit der nächste Stoß
  nicht anschlägt.
- **Schlanke Protokollierung.** Einzelne Nebelstöße werden **nicht** protokolliert. Pro
  Fenster wird je ein Ereignis bei Beginn und Ende veröffentlicht; der Tagesbericht zeigt
  eine Zusammenfassungszeile (Fenster, Dauer, Anzahl Stöße).
- **Kurzer Hardware-Fail-Safe fürs Nebel-Ventil.** Da ein Nebelstoß nur Sekunden dauert,
  erhält das Nebel-Ventil einen deutlich kürzeren `manual_default_settings.fail_safe`
  (z. B. 90 s) als die 30-Minuten-Standard-Schutzdauer. Stürzt der Daemon mitten im Stoß ab,
  schließt die Hardware nach Sekunden statt nach 30 Minuten.
- **Manueller Sofort-Nebel mit Cap.** Zusätzlich zu geplanten Fenstern erlaubt der
  Telegram-Bot einen **Sofort-Nebel**: Der Benutzer wählt beim Start eine Laufzeit (Buttons,
  z. B. 30/60/120 Min); eine konfigurierte Maximaldauer begrenzt ihn als Backstop. Danach
  Auto-Stopp.

  _Amendment (ADR 0034):_ Der Sofort-Nebel fragt zusätzlich zur Laufzeit nun **Stoß-Dauer und
  Pause pro Lauf** ab (statt der festen Config-Defaults); die Werte werden nicht persistiert.
  Der Sofort-Nebel zieht in den Einstieg „Bewässern" um (Art → Ventil → Details).
- **Zustandsloser Neustart (ADR 0011).** Geplante Nebel-Fenster werden zustandslos aus dem
  Zeitplan abgeleitet: Nach einem Neustart schließt `check_startup_safety()` ein offenes
  Ventil, anschließend prüft der Scheduler „sind wir in einem Nebel-Fenster?" und nimmt den
  Takt wieder auf. Ein **Sofort-Nebel** wird nicht persistiert und verfällt beim Neustart.

  _Amendment (ADR 0034):_ Ein **manuell gestopptes** Nebel-Fenster wird für den Rest seiner
  Fensterzeit gegen den minütlichen Scheduler-Neustart **unterdrückt** (in-memory
  `NebelController.is_suppressed`, läuft zur `end_time` lazy ab; ein expliziter Start hebt die
  Sperre auf). Bewusst **nicht** über Neustarts hinweg persistiert (C1): Ein Daemon-Neustart
  mitten im Fenster fällt auf die hier beschriebene zustandslose Fensterableitung zurück — das
  Fenster läuft dann wie gehabt wieder an. Damit ist der manuelle Stopp innerhalb des laufenden
  Daemons verlässlich, ohne die Zustandslosigkeit über Neustarts aufzugeben.

- **Querschnittlicher Notfall-Stopp (ADR 0034).** Der Telegram-„🛑 Stopp" ist ein
  einheitlicher Aus-Knopf über **alle** aktiven Aktuierungen — laufende Güsse *und* ein
  laufendes Nebel-Fenster. Die begriffliche Trennung Kühlen ≠ Bewässern gilt im Normalfluss;
  im Notfall-Stopp steht der gemeinsame Aus-Knopf bewusst darüber. Ein gestopptes Nebel-Fenster
  wird dabei wie oben unterdrückt.

## Konsequenzen

- Saubere Begriffstrennung: Kühlen ≠ Bewässern. CONTEXT.md führt Nebel-Intervall,
  Nebelstoß, Nebel-Steuerung, Nebel-Fenster und Sofort-Nebel als eigene Begriffe.
- Eine neue Kernkomponente und neue Ereignisse entstehen; die Guss-Steuerung bleibt
  unverändert in ihrer Verantwortung (Single Responsibility, Linie der ADRs 0008/0017).
- Die Guss-Steuerung erhält eine schmale Schnittstelle, um beanspruchte Ventile von der
  Unerwartete-Ventilöffnung-Erkennung auszunehmen — die einzige Kopplung zwischen den beiden
  Engines.
- Das `schedules`-Schema wächst um `mode`, `end_time`, `on_seconds`, `pause_minutes`
  (Migration via `ALTER TABLE` in `database.init_db()`, try/except OperationalError);
  bestehende Zeitpläne sind implizit `mode = "watering"`.
- Neue Telegram-Nachrichten (Wizard mit Endzeit/ON-Sekunden/Pause, Sofort-Nebel-Buttons,
  Fenster-Start/Ende-Meldungen, Tagesbericht-Zeile) sind in
  `docs/design/telegram-nachrichten.html` zu pflegen (Regel `telegram_messages.md`).
- Neue Konfigurationswerte in `config/garden.conf`: Standard-`on_seconds`,
  Standard-`pause_minutes`, Sofort-Nebel-Maximaldauer, Nebel-Ventil-Fail-Safe.
- Temperatur-Gating (nur kühlen, wenn heiß) und Regen-Pause bleiben bewusst als spätere,
  optionale Verfeinerungen offen.
