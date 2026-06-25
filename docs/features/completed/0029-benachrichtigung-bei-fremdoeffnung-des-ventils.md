# Feature: Benachrichtigung bei unerwarteter Ventilöffnung (Laufzeit)

> Grundsatzentscheidungen siehe ADR 0032. Begriff „Unerwartete Ventilöffnung" siehe CONTEXT.md.

## Problemstellung (Problem Statement)

Wird ein Ventil **am Bewässerungs-Daemon vorbei** geöffnet — über den Knopf am Ventil,
die Hersteller-App oder einen anderen MQTT-Client — erfährt der Benutzer das im laufenden
Betrieb **nicht**. Der Daemon empfängt zwar die Zustandsmeldung (`ValveStatusReported`
mit `state="ON"`), aber kein Abonnent reagiert darauf, wenn dazu kein aktiver Guss
existiert. Die einzige bestehende Erkennung ist die Sicherheits-Schließung beim
Daemon-Start (ADR 0007), die genau einmal beim Hochfahren greift. Läuft der Daemon
bereits, bleibt eine Fremd-Öffnung unbemerkt.

## Lösung (Solution)

Eine **kontinuierliche Laufzeit-Erkennung**: Meldet ein Ventil `ON`, obwohl die
Guss-Steuerung keinen aktiven Zyklus dafür führt, wird dies als **Unerwartete
Ventilöffnung** erkannt und der Benutzer per Telegram-Bot benachrichtigt. Der Daemon
**schließt das Ventil nicht** — der hardwareseitige Sicherheits-Timeout (Standard 30 Min)
ist der Flutschutz, und absichtliches Handgießen soll nicht sabotiert werden (ADR 0032).
Die Meldung erfolgt **flankengesteuert** (einmal pro Episode), beim Wieder-Schließen folgt
eine Entwarnung.

## User Stories

1. Als Benutzer möchte ich eine Telegram-Benachrichtigung, wenn ein Ventil ohne aktiven
   Guss geöffnet wird, um Fremd-Öffnungen sofort zu bemerken.
2. Als Benutzer möchte ich, dass diese Meldung pro Öffnungs-Episode nur **einmal** kommt,
   um nicht von wiederholten Statusmeldungen zugespammt zu werden.
3. Als Benutzer möchte ich eine **Entwarnung**, sobald das Ventil wieder geschlossen ist.
4. Als Benutzer mit mehreren Ventilen möchte ich die Meldung **pro Ventil** mit dessen
   Wunschnamen erhalten.
5. Als Benutzer möchte ich, dass ein regulär durch den Daemon gestarteter (geplanter oder
   manueller) Guss **keine** Meldung auslöst.
6. Als Benutzer möchte ich, dass das normale Schließen eines Gusses **keinen** Fehlalarm
   erzeugt, auch wenn das Ventil danach noch kurz `ON` nachmeldet.
7. Als Benutzer möchte ich, dass beim Daemon-Start **kein** Doppelfeuer aus
   Start-Sicherheit und Laufzeit-Erkennung entsteht.
8. Als Benutzer, der regelmäßig von Hand gießt, möchte ich die Meldung per Konfiguration
   abschalten können.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Verhalten: nur melden, nicht schließen** (ADR 0032). Der Hardware-Sicherheits-Timeout
  bleibt der Flutschutz.
- **Erkennung in der Guss-Steuerung (Core).** Sie kennt `_active_cycles` und verarbeitet
  `ValveStatusReported` bereits. Neue Zustands-Merker pro Ventil (zuletzt bekannter
  Ventilzustand, Episode-Flag) reihen sich neben `_latest_device_volume` /
  `_last_flow_update_time` ein — **im Speicher**, nicht DB-persistiert.
- **Neue Domänen-Ereignisse** in `core/valve_events.py`, entkoppelt über den Ereignis-Kanal:
  - `UnexpectedValveOpened(mqtt_name)` — Alarm ausgelöst
  - `UnexpectedValveResolved(mqtt_name)` — Ventil wieder zu / Episode beendet
  - Die Ereignisse tragen nur `mqtt_name`; den `wish_name` löst die **UI-Schicht** beim
    Formatieren aus der DB auf (Core bleibt I/O-frei). Telegram-Bot abonniert beide.
- **Flankenerkennung statt Karenzzeit.** Gemeldet wird nur beim Übergang *Nicht-ON → ON*
  ohne aktiven Zyklus. Das vom Daemon ausgelöste Schließen (erst `OFF`, dann Zyklus
  entfernen, Ventil meldet kurz `ON` nach) erzeugt keinen Übergang → kein Fehlalarm. Ein
  Episode-Flag pro Ventil steuert die einmalige Meldung und die `Resolved`-Entwarnung.
- **Cold-Start-Regel.** Bei unbekanntem letztem Zustand (noch kein Report) wird **nicht**
  gemeldet, nur aufgezeichnet → verhindert Doppelfeuer mit `check_startup_safety()` beim
  Boot. Die Start-Sicherheit bleibt **unverändert** (schließt beim Start, eigener Grund).
- **Konfigurierbar:** `UNEXPECTED_VALVE_ALERT_ENABLED` in `config/garden.conf` (Default
  `true`), in `config.py` als `os.getenv(..., "true").lower() == "true"` — analog zu
  `WATCHDOG_ENABLED` (versioniert, nicht-secret, ADR 0030).
- **Nachrichtentexte** (Werte dynamisch beim Senden via `config.get_setting`):
  - Auslösung: `⚠️ *Ventil von außen geöffnet* — „{wish_name}" wurde ohne aktiven Guss
    geöffnet. Warst das nicht du, prüf die Leitung — das Hardware-Sicherheits-Timeout
    schließt spätestens nach {SAFETY_TIMEOUT_MINUTES} Min.`
  - Entwarnung: `✅ *Ventil wieder geschlossen* — „{wish_name}" ist wieder zu.`

## Test-Entscheidungen (Testing Decisions)

- **Was ein guter Test hier ist**: beobachtbares Außenverhalten — welches Ereignis bzw.
  welche Meldung bei welcher Ventil-Zustandsfolge entsteht —, nicht interne Zustandsfelder.
- **Unit-Ebene (Guss-Steuerung)**: `ValveStatusReported`-Folgen einspeisen und die
  veröffentlichten `UnexpectedValveOpened`/`UnexpectedValveResolved` beobachten:
  - Echter Übergang OFF→ON ohne Zyklus → genau **ein** `UnexpectedValveOpened`.
  - Wiederholte ON-Reports → **kein** erneutes Feuern.
  - Regulärer Guss (ON mit aktivem Zyklus) → **kein** Ereignis.
  - Daemon schließt per Limit, Ventil meldet danach kurz ON → **kein** Fehlalarm.
  - OFF nach Episode → `UnexpectedValveResolved`.
  - **Cold-Start**: erster je gesehener Report ist ON → **kein** Ereignis (nur aufzeichnen).
  - Mehrere Ventile → Erkennung pro `mqtt_name`.
  - `UNEXPECTED_VALVE_ALERT_ENABLED=false` → kein Ereignis.
- **Höchstgelegene Nahtstelle (bestehend)**: Integrationstest in `tests/test_irrigation.py`
  (erzwingt `SimulatedMqttAdapter` via `HAS_PAHO=False` in `setUpClass`) für den Pfad
  Ventilmeldung → Ereignis → Benachrichtigung.
- **Telegram-Handler**: Test des neuen `_on_*`-Handlers inkl. `wish_name`-Auflösung, analog
  zu bestehenden Benachrichtigungs-Tests in `tests/ui/test_telegram_ui.py`.
- **Referenzen**: `check_startup_safety`-Test (`test_irrigation.py`), Inaktivitäts-Watchdog-
  und Regen-Flankenmuster.
- **Pflege**: Beide Texte in `docs/design/telegram-nachrichten.html` nachziehen (Regel
  `.claude/rules/telegram_messages.md`). Coverage darf nicht regredieren; TDD.

## Nicht im Leistungsumfang (Out of Scope)

- **Automatisches Schließen** bei Fremd-Öffnung (ADR 0032: bewusst nur melden). Auto-Schließen
  mit Bestätigungs-Button bleibt Option, sobald Feature 0018 (aktionsfähige
  Benachrichtigungen) steht.
- **Separate DB-Protokollierung** des Ereignisses / Zählung im Tagesbericht — der rohe
  Ventil-Status wird via `device_status_log` ohnehin geloggt.
- **Debounce gegen Funk-Flackern** (mehrfaches Anschlagen bei ON/OFF/ON) — spätere
  Verfeinerung.
- **Erfassung der bei einer Fremd-Öffnung geflossenen Wassermenge** — eigenes Feature, baut
  auf `_latest_device_volume` (ADR 0007) auf.
- Unterscheidung *welcher* externe Akteur geöffnet hat — technisch nicht zuverlässig.

## Weitere Anmerkungen (Further Notes)

- Entstanden aus der Beobachtung, dass manuelles Gießen ohne den Daemon keinerlei
  Benachrichtigung auslöst (Grill-Diskussion zum Guss-Volumen-Bugfix, ADR 0007).
- Hebt den Schutz der Start-Sicherheits-Schließung sinngemäß auf den Dauerbetrieb — mit
  bewusst anderem Verhalten (melden statt schließen, ADR 0032).
- Mit `/to-feature` synthetisiert und per `/grill-with-docs` geschärft.
