# Feature: OTA-Update-System

## Problemstellung (Problem Statement)

Das Deployment der Software auf die Steuerzentrale (Raspberry Pi Zero W) erfordert heute direkten LAN-Zugang: `deploy.ps1` überträgt Dateien per SCP und führt Setup-Befehle per SSH aus. Ist der Benutzer nicht im lokalen Netzwerk, ist kein Deployment möglich. Außerdem fehlt ein automatischer Rollback-Mechanismus — ein fehlgeschlagenes Update hinterlässt die Steuerzentrale in einem unbekannten Zustand.

## Lösung (Solution)

Eine CI-Pipeline (GitHub Actions) kompiliert den Mittelweg-Dienst auf einem Ubuntu-Runner und veröffentlicht ein signiertes Release-Archiv auf GitHub. Die Steuerzentrale lädt das Archiv auf Befehl des Benutzers über den Telegram-Bot herunter, wendet das Update an und rollt bei Fehler automatisch auf die vorherige Version zurück. Der Benutzer erhält eine Telegram-Benachrichtigung sobald ein neues Build verfügbar ist.

## User Stories

1. Als Benutzer möchte ich per `git push origin main:release` ein neues Deployment auslösen, ohne manuell Dateien übertragen zu müssen.
2. Als Benutzer möchte ich per Telegram benachrichtigt werden, sobald ein neues Build bereit ist, damit ich den richtigen Zeitpunkt für das Update wählen kann.
3. Als Benutzer möchte ich per `/update`-Befehl im Telegram-Bot das Update bewusst starten und bestätigen.
4. Als Benutzer möchte ich, dass bei einem fehlgeschlagenen Update automatisch die vorherige Version wiederhergestellt wird, damit die Steuerzentrale betriebsfähig bleibt.
5. Als Benutzer möchte ich, dass meine `.env`-Datei auf der Steuerzentrale bei keinem Update überschrieben wird, damit Produktions-Secrets sicher bleiben.

## Implementierungs-Entscheidungen (Implementation Decisions)

### CI-Pipeline (`.github/workflows/release.yml`)

- **Trigger:** Push auf `release`-Branch via `git push origin main:release`
- **Runner:** Ubuntu (latest) mit Node.js für Zigbee2MQTT-TypeScript-Kompilierung
- **Archiv-Inhalt:** `src/`, `scripts/`, `tools/`, kompiliertes Zigbee2MQTT (ohne `node_modules/`, ohne `.git/`), `VERSION`, `Z2M_VERSION`
- **Versionsdateien:**
  - `VERSION` — Git-Tag (`v1.2.3`) oder Commit-SHA als Fallback
  - `Z2M_VERSION` — Zigbee2MQTT-Paketversion aus `vendor/zigbee2mqtt/package.json`
- **GitHub Release:** wird automatisch mit dem Archiv als Asset angelegt
- **Telegram-Benachrichtigung:** letzter CI-Step sendet via `curl` an Telegram API: „🌱 Build `vX.Y.Z` fertig — bereit zum Installieren. Tippe `/update` zum Starten."
- **GitHub Secrets:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

### Update-Skript (`scripts/update.sh`, Bash)

Läuft auf der Steuerzentrale, gestartet als Subprocess des Bewässerungs-Daemons.

**Ablauf:**

1. GitHub API abfragen (`GITHUB_PAT` + `GITHUB_REPO` aus `.env`) → neueste Release-Asset-URL und Tag-Name
2. Lokale `~/garden/VERSION` mit Release-Tag vergleichen → bei Gleichstand abbrechen
3. Archiv nach `/tmp/garden-update.tar.gz` herunterladen
4. Backup anlegen: `~/garden-backup/` ← Snapshot von `src/`, `scripts/`, `tools/`, Zigbee2MQTT-Verzeichnis (`.env` und `garden.db` werden nie gesichert oder überschrieben)
5. Archiv entpacken nach `~/garden/` — `.env` und `garden.db` explizit ausschließen
6. `Z2M_VERSION` vergleichen: `npm ci --production` nur wenn unterschiedlich (~3–5 Min)
7. `sudo systemctl restart garden-irrigation`
8. 15 Sekunden warten → `systemctl is-active garden-irrigation`
9a. **Erfolg:** `VERSION` und `Z2M_VERSION` aktualisieren, `/tmp/`-Archiv aufräumen
9b. **Fehler → Rollback:** `~/garden-backup/` zurückkopieren, ggf. `npm ci`, Service neu starten, Exit-Code 1

**sudo-Berechtigung** (in `/etc/sudoers.d/garden`):
```
pi ALL=(ALL) NOPASSWD: /bin/systemctl restart garden-irrigation
```

**Selektives `npm ci`:** verhindert unnötige ~3-5 Min Wartezeit bei reinen Python-Updates. Zigbee2MQTT-Updates sind selten.

### Telegram-Bot `/update`-Befehl (`src/daemon/ui/telegram_bot.py`)

- Lokale `~/garden/VERSION` lesen + GitHub API abfragen → aktuelle und verfügbare Version anzeigen
- Inline-Keyboard: „✓ Jetzt installieren" / „✗ Abbrechen"
- Bei Bestätigung: `subprocess.Popen(['bash', 'scripts/update.sh'])` + sofortige Antwort „⏳ Update gestartet. Bitte 3–5 Minuten warten, dann `/status` prüfen."
- Kein automatisches Abschluss-Feedback vom Skript — Ergebnis via `/status` oder `journalctl` prüfen

### Konfiguration

**`.env.prod` (neu, nur auf Windows-Entwicklungsmaschine):**

Trennung zwischen lokaler Testumgebung und Produktion:

| Datei | Ort | Zweck |
|---|---|---|
| `.env` | Windows | Entwicklung & lokale Tests |
| `.env.prod` | Windows | Produktions-Secrets — wird nie committed |
| `.env` | Raspberry Pi | Produktionskonfiguration — unangetastet bei OTA-Updates |

`deploy.ps1` wird angepasst: kopiert `.env.prod` als `.env` auf den Pi (statt `.env`). Beide Dateien sind durch `.gitignore`-Regel `.env.*` bereits abgedeckt.

**Neue Einträge in `.env.prod` und `.env.template`:**
```env
# OTA-Update
GITHUB_PAT=github_pat_...        # Fine-grained PAT, nur contents:read auf garden-Repo
GITHUB_REPO=username/garden      # Für GitHub API-Aufrufe
```

**Fine-grained PAT:** GitHub → Settings → Developer settings → Fine-grained tokens → New token, Repository: nur `garden`, Permissions: `Contents: Read-only`

### Versionstracking auf der Steuerzentrale

| Datei | Inhalt | Wann aktualisiert |
|---|---|---|
| `~/garden/VERSION` | `v1.2.3` | Nach erfolgreichem Update |
| `~/garden/Z2M_VERSION` | `1.36.0` | Nach erfolgreichem Update mit Z2M-Änderung |

Beide Dateien werden beim ersten Deployment via `deploy.ps1` einmalig angelegt.

## Test-Entscheidungen (Testing Decisions)

- `update.sh` wird mit einem Mock-GitHub-Server (einfacher `python3 -m http.server`) getestet, der ein Test-Archiv ausliefert
- Getestete Szenarien: bereits aktuell (kein Download), Python-only-Update (kein `npm ci`), Z2M-Update (mit `npm ci`), fehlgeschlagener Health-Check (Rollback), unterbrochener Download
- Der `/update`-Handler im Telegram-Bot wird mit bestehenden Mocking-Mustern aus `tests/ui/` getestet (gemockter `subprocess.Popen`, gemockter GitHub-API-Aufruf)

## Nicht im Leistungsumfang (Out of Scope)

- Automatisches Update ohne Benutzerbestätigung
- Rollback-Befehl via Telegram (manueller Rollback bleibt SSH-Sache)
- Differentielles Update (nur geänderte Dateien übertragen)
- Mehrere Rollback-Generationen (nur eine Generation Backup)
- Benachrichtigung bei Rollback via Telegram (Benutzer prüft selbst)

## Weitere Anmerkungen (Further Notes)

- `deploy.ps1` bleibt für initiale Einrichtung und Notfälle erhalten
- Ein neues ADR wird benötigt: Entscheidung für GitHub Actions + Release als Deployment-Kanal (ersetzt/ergänzt ADR 0010 zur vorkompilierten Bereitstellung des Mittelweg-Dienstes)
- `node_modules/` werden bewusst nicht im Release-Archiv gebündelt — native Module (z.B. `serialport`) müssen für ARMv6 auf dem Pi selbst kompiliert werden
