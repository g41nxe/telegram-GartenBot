# 44. Update-Benachrichtigung beim Daemon-Start

Wenn eine neue Version live geht, meldet sich die Steuerzentrale von selbst — und ebenso,
wenn ein Update scheitern und zurückgerollt werden musste. Ausgelöst wird die Meldung
beim **Daemon-Start**, nicht im Update-Skript.

## Kontext

Ein erfolgreiches Update blieb bisher stumm: `update.sh` schickte zwar eine „✅ installiert"-
Meldung, aber (a) nur beim **manuell** über `/update` angestoßenen Pfad — ein automatisch
über `git push … release` ausgeliefertes Release meldete sich **nie** —, und (b) direkt nach
`systemctl restart`, also **während** der Daemon noch hochfuhr (Race, die Meldung konnte
verpuffen). In der Diagnose vom 22.07. war deshalb aus dem Journal nicht ablesbar, welche
Version läuft (der Start-Banner nennt keine Version).

Der Auslöser gehört an den einen Punkt, an dem beides gleichzeitig wahr ist — „die neue
Version läuft" **und** „der Bot ist bereit": den Daemon-Start.

## Entscheidung

- **Ausgelöst beim Daemon-Start**, nicht in `update.sh`. Am Ende des Starts (nachdem der
  Telegram-Transport oben ist) entscheidet der Daemon, ob und was zu melden ist.

- **Erfolg über Versions-Diff.** Ein persistierter Schlüssel `announced_version` in
  `system_metadata` hält die zuletzt gemeldete Version. Ist `read_version()` davon
  verschieden, gilt eine neue Version als live. Ein *nicht*-Versions-Neustart (Absturz,
  Config-Änderung, Reboot) hat gleiche Werte → **keine** Meldung. Der Erststart nach
  Einführung meldet die laufende Version einmal; `"unbekannt"` (keine `VERSION`-Datei, z. B.
  Simulation) wird übersprungen.

- **Rollback über Marker.** Ein Rollback ist **kein** Versionswechsel (zurück auf die alte
  Version) — der Versions-Diff kann ihn nicht sehen. Deshalb schreibt `update.sh` im
  Rollback-Zweig eine Marker-Datei mit der gescheiterten Ziel-Version; der Daemon-Start liest
  sie, meldet den Fehlschlag und löscht sie.

- **`update.sh` sendet selbst nichts mehr.** Das bisherige `tg_notify`/`curl` (Erfolg **und**
  Rollback) entfällt komplett — ein Meldeweg statt zweier, der gesicherte Bot statt eines
  zweiten Bash-`curl`. `update.sh` wird dadurch einfacher und braucht keinen Bot-Token mehr.

- **Höchstens einmal: Zustand schreiben, dann melden.** Zuerst `announced_version`
  fortschreiben bzw. den Marker löschen, **dann** publizieren. Stürzt der Daemon dazwischen
  ab, wird beim nächsten Start **nicht** erneut gemeldet. Preis: ist Telegram ausgerechnet
  beim Boot nicht erreichbar, geht *diese eine* Meldung verloren — bewusst „höchstens einmal"
  statt „mindestens einmal", um Neustart-Spam auszuschließen.

- **Regelkonforme Aufteilung (Regeln 2, 3, 5):**
  - `core/version_announce.py` — pure Entscheidung: (aktuelle Version, gemeldete Version,
    Rollback-Ziel) → auszulösendes Ereignis + neuer `announced_version`-Wert. Kein I/O.
  - Ein Start-Adapter macht das I/O (`read_version`, `system_metadata`, Marker-Datei) und
    **publiziert Ereignisse** auf den Ereignis-Kanal — er ruft die UI nicht direkt (Regel 2).
  - Neue Ereignisse in `core/system_events.py`: `SoftwareUpdateActivated(version)` und
    `SoftwareUpdateRolledBack(target_version, current_version)`.
  - Die Telegram-UI abonniert beide in `subscribe_event_handlers()` (Regel 5) und formuliert
    die Texte (`🚀 Update aktiv …` / `❌ Update fehlgeschlagen …`) — Meldungstext liegt dort,
    wo aller Meldungstext liegt.

## Konsequenzen

- Automatische **und** manuelle Releases melden sich beim Start; kein Race mehr.
- Die laufende Version wird sichtbar (löst die Beobachtbarkeits-Lücke aus der 22.07.-Diagnose).
- Neuer `system_metadata`-Schlüssel (`announced_version`) und eine Marker-Datei; `update.sh`
  verliert seinen Telegram-Code.
- **Nachtrag (Ticket eor, geschlossen):** Der Auto-Fehlerpfad *vor* dem Rollback ist jetzt
  abgedeckt — vorrangig durch **Recovery statt bloßer Meldung**:
  - **Automatischer Rollback bei jedem Fehler.** `update.sh` setzt ab der ersten Änderung am
    Live-Verzeichnis `UPDATE_STARTED=true` und hängt einen `trap … ERR`. Schlägt danach *irgendeine*
    Anweisung fehl (Kopierfehler, `tar`, `npm ci` für Zigbee2MQTT, misslungener `restart`), wird
    automatisch aus dem Backup zurückgerollt — derselbe `do_rollback`, der bisher nur den
    fehlgeschlagenen Health-Check bediente. Der Rollback startet sofort neu, der Daemon meldet den
    Fehlschlag über den (unmittelbar gelesenen) Rollback-Marker → `SoftwareUpdateRolledBack`
    („❌ Update fehlgeschlagen, läuft weiter auf …"). Das deckt die zuvor stillen Abbrüche ab,
    inklusive „VERSION schon geflippt, aber `npm ci` scheitert" und „Live-Verzeichnis halb kopiert".
  - **Versuchs-Marker als Best-effort-Rückfall.** Für den *nicht* abfangbaren Fall (Stromausfall,
    `SIGKILL` — kein Trap feuert) legt `update.sh` zusätzlich `/tmp/garden-ota-attempt` an. Bootet
    der Daemon danach noch und läuft die Zielversion nicht, meldet der Start
    `SoftwareUpdateFailed` → „⚠️ Update unterbrochen". `core/version_announce.decide()` bekommt dazu
    `attempt_target`; der Race „Daemon startet, während der Health-Check noch läuft" (Zielversion
    läuft bereits) wird als Erfolg gewertet.
  - **Bewusst nicht abgedeckt:** Bricht ein Update so hart ab, dass der Daemon gar nicht mehr
    startet *und* der Rollback nicht griff (z. B. Stromausfall mitten im Kopieren), kann keine
    Meldung aus dem Daemon kommen und `/tmp` ist nach einem Reboot leer. Das wäre nur extern
    (systemd `OnFailure`/Watchdog) zu schließen — eigenes, kleineres Thema.
