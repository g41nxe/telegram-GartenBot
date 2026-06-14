# Feature: OTA Release-Notes und Update-Benachrichtigung

## Problemstellung (Problem Statement)

Das OTA-Update-System (Feature 0011) zeigt dem Benutzer beim `/update`-Befehl nur Versionsnummern — keine Information darüber, was sich geändert hat. Nach dem Update gibt es kein Feedback: der Benutzer weiß nicht, ob das Update erfolgreich war oder ein Rollback stattgefunden hat, ohne manuell `/status` zu prüfen oder in `journalctl` nachzuschauen. Außerdem fehlt ein geführter Workflow für den Entwickler, um einen Release vorzubereiten und auszulösen.

## Lösung (Solution)

Ein `CHANGELOG.md` im Repo-Root dient als einzige Quelle für Release-Notes. Die CI-Pipeline extrahiert den neuesten Eintrag automatisch als Release-Body. Der Telegram-`/update`-Dialog zeigt diese Notes an, damit der Benutzer vor der Bestätigung weiß, was installiert wird. Nach dem Neustart des Daemons erhält der Benutzer automatisch eine Telegram-Nachricht mit Erfolgs- oder Rollback-Status. Ein neuer `/release`-Skill führt den Entwickler durch den gesamten Release-Vorbereitungs-Workflow.

## User Stories

1. Als Benutzer möchte ich im `/update`-Dialog sehen, welche Änderungen das neue Release enthält, damit ich eine informierte Entscheidung treffen kann.
2. Als Benutzer möchte ich nach einem Update automatisch eine Telegram-Nachricht erhalten, die bestätigt, dass der Daemon erfolgreich neu gestartet wurde.
3. Als Benutzer möchte ich nach einem fehlgeschlagenen Update automatisch per Telegram informiert werden, dass ein Rollback durchgeführt wurde, damit ich nicht in Unwissenheit bin.
4. Als Benutzer möchte ich im `/update`-Dialog den Release-Namen mit Datum sehen (z.B. „2026-06-14"), damit ich das Alter des Releases einschätzen kann.
5. Als Benutzer möchte ich, dass lange Release-Notes im Telegram-Dialog auf lesbare Länge gekürzt werden, damit die Nachricht nicht unlesbar wird.
6. Als Entwickler möchte ich einen `/release`-Skill nutzen, der mich durch die Release-Vorbereitung führt, damit ich keinen Schritt vergesse.
7. Als Entwickler möchte ich, dass der Skill die Änderungen seit dem letzten Release (neue Feature-Dokumente, Commit-Messages) analysiert und einen Changelog-Vorschlag macht, damit ich nicht manuell nachdenken muss.
8. Als Entwickler möchte ich, dass der Skill CHANGELOG.md aktualisiert, committet und den Release-Branch pusht, damit der gesamte Release-Prozess aus einem Workflow erfolgt.

## Implementierungs-Entscheidungen (Implementation Decisions)

### CHANGELOG.md (neu, Repo-Root)

- Akkumuliertes Changelog — neue Einträge werden oben vorangestellt
- Trennzeichen zwischen Einträgen: `---` auf eigener Zeile
- Format eines Eintrags:
  ```
  ## YYYY-MM-DD
  
  - Stichpunkt 1
  - Stichpunkt 2
  ```
- Die CI-Pipeline extrahiert alles zwischen dem ersten `##` und dem ersten `---` als Release-Body
- Der Skill legt den ersten Eintrag automatisch an

### CI-Pipeline (`.github/workflows/release.yml`)

- **Release-Name** wird auf `YYYY-MM-DD — vX.Y.Z-sha` gesetzt (statt nur Version)
- **Release-Body** wird aus dem obersten CHANGELOG.md-Abschnitt extrahiert (sed/awk bis zum ersten `---`)
- Kein Breaking Change an bestehenden Steps — nur `name`- und `body`-Felder der `softprops/action-gh-release`-Action werden ergänzt

### GitHub API-Erweiterung (`src/daemon/ui/telegram_ui.py`)

- `_fetch_latest_release_tag()` wird zu `_fetch_latest_release_info()` erweitert
- Rückgabe: `dict` mit `tag`, `name`, `notes` (alle drei aus demselben API-Aufruf — kein zweiter Request)
- Release-Notes werden auf 800 Zeichen gekürzt; bei Kürzung wird `…` angehängt
- `handle_update()` zeigt Notes im Bestätigungs-Dialog an:
  ```
  🔄 Software-Update verfügbar

  Installiert: v0.0.0-initial
  Verfügbar:   v0.1.0-abc1234 (2026-06-14)

  📋 Was ist neu:
  - Feature X
  - Feature Y

  Soll das Update jetzt installiert werden?
  ```

### OTA-Notify-Mechanismus

Drei beteiligte Komponenten schreiben/lesen eine gemeinsame Notify-Datei (`/tmp/garden-ota-notify`):

| Schritt | Komponente | Aktion |
|---|---|---|
| 1 | `update_confirm`-Handler | Schreibt `{chat_id}` in Notify-Datei |
| 2 | `update.sh` | Überschreibt mit `{chat_id}\nsuccess` oder `{chat_id}\nfailed` |
| 3 | `main.py` (Startup) | Liest Datei, sendet Nachricht, löscht Datei |

`main.py` wird nach dem Telegram-Bot-Start um eine einmalige Prüfung ergänzt: Datei vorhanden → `chat_id` und Status lesen → passende Nachricht senden:
- Erfolg: `✅ Update auf \`vX.Y.Z\` erfolgreich installiert.`
- Rollback: `❌ Update fehlgeschlagen — Rollback auf \`vX.Y.Z\` durchgeführt.`

Die Notify-Datei liegt in `/tmp/` — sie überlebt Service-Neustarts, aber nicht Reboots. Das ist akzeptabel, da ein Reboot ein eigenständiges Ereignis ist und nicht dem OTA-Zyklus zuzurechnen ist.

### `/release`-Skill (`.claude/skills/skills/release/SKILL.md`)

Aktiver Skill — Claude führt alle Schritte durch:

1. `git log release..master --oneline` ausführen
2. Neue Dateien in `docs/features/completed/` seit letztem Merge identifizieren
3. Changelog-Vorschlag aus Feature-Titeln + Commit-Messages synthetisieren, Benutzer bestätigen lassen
4. Benutzer nach Release-Name fragen (Vorschlag: heutiges Datum `YYYY-MM-DD`)
5. CHANGELOG.md mit neuem Eintrag voranstellen (Datum-Überschrift + Stichpunkte + `---`)
6. `git add CHANGELOG.md && git commit -m "chore: Release YYYY-MM-DD"`
7. `git push origin master:release`

### `update.sh`

- Nach dem Health-Check: Notify-Datei lesen (falls vorhanden), Status überschreiben
- Pfad der Notify-Datei: `/tmp/garden-ota-notify` (fest kodiert, kein Konfigurationsparameter)
- Datei muss nicht zwingend existieren — `update.sh` prüft vor dem Schreiben

## Test-Entscheidungen (Testing Decisions)

Alle Tests laufen vollständig offline (kein MQTT-Broker, kein Telegram, keine GitHub API).

### `tests/ui/test_update_handler.py` (bestehend, erweitern)

- `_fetch_latest_release_info()` ersetze `_fetch_latest_release_tag()` in allen bestehenden Tests
- Neue Tests: Notes im Update-Dialog vorhanden, Truncation bei > 800 Zeichen, Release-Name mit Datum im Dialog

### `tests/test_main_startup.py` (neu oder in `test_irrigation.py`)

- Notify-Datei mit `chat_id\nsuccess` → Telegram-Nachricht mit „erfolgreich" gesendet, Datei gelöscht
- Notify-Datei mit `chat_id\nfailed` → Telegram-Nachricht mit „fehlgeschlagen" gesendet, Datei gelöscht
- Keine Notify-Datei → keine Telegram-Nachricht gesendet
- Referenzmuster: `setUpClass` aus `tests/test_irrigation.py`

### `scripts/test_update_sh.sh` (bestehend, erweitern)

- Szenario 7: Erfolgreicher Update-Lauf schreibt `success` in Notify-Datei
- Szenario 8: Rollback schreibt `failed` in Notify-Datei

## Nicht im Leistungsumfang (Out of Scope)

- Automatisches Parsen von Commit-Messages nach einem Schema (Conventional Commits)
- Mehrsprachige Release-Notes
- Anzeige vergangener Changelogs im Bot
- Diff-basierte automatische Changelog-Generierung ohne Entwickler-Bestätigung

## Weitere Anmerkungen (Further Notes)

- Die `_fetch_latest_release_info()`-Umbenennung ist ein Breaking Change für bestehende Tests — alle betroffenen Tests in `tests/ui/test_update_handler.py` müssen beim Umstieg mitgeführt werden
- Der `/release`-Skill setzt voraus, dass der Entwickler auf dem `master`-Branch arbeitet und `git push`-Rechte auf `origin` hat
- CHANGELOG.md wird committed und damit Teil des Repos — er darf ausführlich sein, da er nie automatisch ausgewertet wird außer von der CI
