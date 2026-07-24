# Umsetzungsplan — Update-Benachrichtigung beim Daemon-Start (ADR 0044, Ticket 2e8)

Neue Version live → Steuerzentrale meldet sich beim Start; Rollback ebenso. Vorgehen je
Schritt: **roter Test zuerst → minimal grün → Refactor → committen**. Begriffe: `CONTEXT.md`
(*Software-Update (OTA)*, *Gemeldete Version*).

---

## Schritt 1 — Kern: Entscheidungslogik (pure)

**Ziel:** Aus (aktuelle Version, gemeldete Version, Rollback-Ziel) wird die Entscheidung —
ohne I/O.

- **Implementieren:** `core/version_announce.py` mit `decide(current, announced, rollback_target)
  -> (event | None, new_announced)`.
- **Test:** Versionswechsel → `SoftwareUpdateActivated`; gleiche Version, kein Marker → **keine**
  Meldung, `new_announced == current`; Rollback-Ziel gesetzt → `SoftwareUpdateRolledBack`;
  `current == "unbekannt"` → keine Meldung, `announced` unverändert; Erststart
  (`announced == ""`) → meldet einmal.

## Schritt 2 — Ereignisse

- **Implementieren:** `core/system_events.py` mit `SoftwareUpdateActivated(version)` und
  `SoftwareUpdateRolledBack(target_version, current_version)`.
- **Test:** Felder korrekt gesetzt.

## Schritt 3 — Start-Adapter (I/O + Publikation)

**Ziel:** Der Start liest den Zustand, entscheidet, schreibt **zuerst** fort, publiziert dann.

- **Implementieren:** `adapters/version_announce_adapter.py`: `announce_on_start(event_bus)`
  liest `read_version()`, `announced_version` aus `system_metadata`, den Rollback-Marker
  (`/tmp/garden-ota-rollback`); ruft den Kern; schreibt `announced_version` fort / löscht den
  Marker; publiziert das Ereignis. In `main.py` nach dem Bot-Start aufgerufen (Regel 6: Smoke-Test).
- **Test:** Reihenfolge „Zustand-vor-Publikation"; Marker wird gelöscht; reiner Neustart
  (gleiche Version, kein Marker) publiziert nichts.

## Schritt 4 — UI: Meldungen

- **Implementieren:** `telegram_ui` abonniert beide Ereignisse in `subscribe_event_handlers()`;
  `🚀 *Update aktiv* — jetzt auf \`vX\`` und `❌ *Update fehlgeschlagen* — \`vZiel\` ließ sich
  nicht installieren, läuft weiter auf \`vAktuell\``.
- **Test:** Formatierung beider Meldungen.
- **Pflicht:** `docs/design/telegram-nachrichten.html` nachziehen (Regel `telegram_messages.md`).

## Schritt 5 — update.sh entschlacken

**Ziel:** `update.sh` sendet nichts mehr selbst; Rollback schreibt nur noch den Marker.

- **Implementieren:** `tg_notify`/`curl` entfernen (Erfolg **und** Rollback); im Rollback-Zweig
  `echo "$RELEASE_TAG" > /tmp/garden-ota-rollback`. Die manuelle Notify-Datei
  (`/tmp/garden-ota-notify`) entfällt, ebenso ihr Schreiben in `telegram_ui`.
- **Verifikation:** `bash -n scripts/update.sh` (Syntax); Pfade konsistent.

## Schritt 6 — Verifikation

- Volle Testsuite grün, Coverage nicht regressiert.
- Smoke: `announce_on_start` gegen eine temporäre DB mit gesetztem/leerem `announced_version`
  und mit/ohne Marker — erwartete Ereignisse.

---

**Nicht im Umfang:** Vollständige Absicherung des *automatischen* Update-Fehlerpfads
(Ticket `eor`) und das Guss-Skip-Logging (Ticket `06v`) — eigene Tickets.
