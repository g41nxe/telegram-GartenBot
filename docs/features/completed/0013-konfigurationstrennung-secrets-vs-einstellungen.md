# Feature: Konfigurationstrennung — Secrets vs. Einstellungen

## Problemstellung (Problem Statement)

Alle Konfigurationswerte — sowohl sensible Secrets (Telegram-Token, API-Schlüssel) als auch fachliche Einstellungen (Regenschwelle, Standortkoordinaten, Watchdog-Timeout) — liegen heute in einer einzigen `.env`-Datei. Diese Datei ist gitignored und wird beim OTA-Update bewusst nie überschrieben, um Produktions-Secrets zu schützen.

Das Problem: Wenn sich eine fachliche Einstellung ändert (z.B. `RAIN_THRESHOLD_MM` von 3.0 auf 2.0), muss der Benutzer manuell auf dem Pi eingreifen. Es gibt keinen automatischen Mechanismus, der nicht-sensitive Konfigurationsänderungen auf die Steuerzentrale bringt. Im laufenden Betrieb bleibt der Pi auf veralteten Werten, bis jemand manuell die `.env` editiert.

## Lösung (Solution)

Die Konfiguration wird in zwei Dateien aufgeteilt:

- **`config/garden.conf`** (versioniert, wird bei jedem Deploy/OTA-Update überschrieben): enthält alle fachlichen Einstellungen ohne Geheimniswert — Regenschwelle, Koordinaten, Timeouts, Ventil-Topics, Intervalle.
- **`.env`** (gitignored, nie überschrieben): enthält ausschließlich Secrets und maschinenspezifische Werte — Telegram-Token, erlaubte User-IDs, GitHub-PAT, Deploy-Zugangsdaten.

Der Bewässerungs-Daemon lädt beim Start beide Dateien. Die Priorität ist: Shell-Umgebungsvariablen > `.env` > `garden.conf`. Fachliche Konfigurationsänderungen fließen fortan automatisch via OTA-Update auf die Steuerzentrale — ohne manuelles Eingreifen.

## User Stories

1. Als Benutzer möchte ich, dass Änderungen an fachlichen Einstellungen (z.B. Regenschwelle) automatisch per OTA-Update auf den Pi übertragen werden, damit ich nicht manuell eingreifen muss.
2. Als Benutzer möchte ich, dass mein Telegram-Token und meine User-IDs niemals durch ein Update überschrieben werden, damit meine Produktions-Secrets sicher bleiben.
3. Als Benutzer möchte ich eine einzige `config/garden.conf`-Datei im Repository sehen, die alle nicht-sensitiven Konfigurationsoptionen mit ihren Standardwerten und Kommentaren dokumentiert — als lebendige Referenz statt eines separaten Templates.
4. Als Benutzer möchte ich beim Einrichten eines neuen Pi nur eine minimale `.env`-Datei mit meinen Secrets anlegen müssen; alle anderen Werte sollen aus `garden.conf` kommen.
5. Als Benutzer möchte ich `deploy.ps1` mit einem `-CopyEnv`-Flag aufrufen können, um beim Erstsetup die `.env` auf den Pi zu kopieren — standardmäßig wird sie nicht übertragen.
6. Als Entwickler möchte ich, dass neue Konfigurationsvariablen ohne Geheimniswert direkt in `garden.conf` eingecheckt werden, damit sie beim nächsten Release automatisch auf allen Instanzen ankommen.

## Implementierungs-Entscheidungen (Implementation Decisions)

### Dateiaufteilung

**`config/garden.conf`** (neu, versioniert, `KEY=VALUE`-Format) enthält:
- `RAIN_THRESHOLD_MM`
- `LATITUDE`, `LONGITUDE`
- `MQTT_BROKER_HOST`, `MQTT_BROKER_PORT`, `MQTT_VALVE_TOPIC`
- `SAFETY_TIMEOUT_MINUTES`
- `BATTERY_WARNING_THRESHOLD`
- `FLOW_TIME_GAP_CAP_SECONDS`
- `WEATHER_REFRESH_INTERVAL_SECONDS`
- `DAILY_REPORT_TIME`
- `WATCHDOG_ENABLED`, `WATCHDOG_VALVE_TIMEOUT_HOURS`

**`.env`** (gitignored, unverändert) enthält nur noch:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_IDS`
- `GITHUB_PAT`
- `GITHUB_REPO`
- `DEPLOY_PI_HOST`, `DEPLOY_PI_USER`

### Lade-Reihenfolge in `config.py`

Priorität: **Shell-Env > `.env` > `garden.conf`**

Umsetzung:
1. `garden.conf` mit `os.environ.setdefault` laden (Shell-Env bleibt unberührt)
2. `.env` mit direktem `os.environ[key] = val` laden (überschreibt `garden.conf`, nicht Shell-Env)

Fehlt `garden.conf`: Warnung ins Log, Daemon startet mit eingebauten Fallback-Werten in `config.py` — kein Absturz.

### Format

`KEY=VALUE` — identisch zu `.env`, damit `_load_env_file` mit minimalem Aufwand wiederverwendet bzw. zu einer generischen `_load_file(path, override=False)`-Funktion extrahiert werden kann.

### `.env.template`

Wird auf reine Secrets reduziert — enthält nur noch die Keys aus `.env`. `garden.conf` ist die kanonische Referenz für alle Non-Secret-Parameter.

### Deploy & OTA

- `deploy.ps1`: überträgt `config/garden.conf` zusammen mit `src/` auf den Pi; neues `-CopyEnv`-Flag kopiert `.env` nur auf expliziten Wunsch (Erstsetup)
- `update.sh` (Feature 0011): schließt `config/` ins Update-Archiv ein; schließt `.env` weiterhin explizit aus
- `.gitignore`: `config/garden.conf` wird **nicht** ignoriert; `.env` bleibt ignoriert

### ADR

Ein neues ADR dokumentiert die Entscheidung zur Konfigurationstrennung.

## Test-Entscheidungen (Testing Decisions)

- `test_01_config_defaults` in `tests/test_irrigation.py` bleibt die Hauptnahtstelle: prüft ob Standardwerte korrekt geladen werden (muss auf `garden.conf`-basierte Werte angepasst werden).
- Neuer Test in `tests/test_config.py`: `.env`-Wert überschreibt `garden.conf`-Wert korrekt (Priorität A > B).
- Neuer Test: fehlende `garden.conf` → Daemon startet mit Fallback-Werten, loggt Warnung, kein Absturz.
- Neuer Test: Shell-Env-Variable überschreibt `.env`-Wert (Priorität Shell > `.env`).
- Bestehende Chart-, Wetter- und Scheduler-Tests brauchen keine Anpassung — sie referenzieren `config.RAIN_THRESHOLD_MM` direkt.

## Nicht im Leistungsumfang (Out of Scope)

- Hot-Reload der Konfiguration ohne Neustart des Daemons
- Validierung von Konfigurationswerten zur Laufzeit (Wertebereichsprüfung)
- Verschlüsselung von `garden.conf`-Werten
- Mehrere Umgebungsprofile (dev/staging/prod) über verschiedene `garden.conf`-Dateien

## Weitere Anmerkungen (Further Notes)

- Feature 0011 (OTA-Update-System) muss im `update.sh`-Skript `config/` als zu übertragendes Verzeichnis einschließen — dies ist als Abhängigkeit zu vermerken.
- `setup.sh` sollte einen Hinweis ausgeben wenn `.env` auf dem Pi fehlt und auf `.env.template` verweisen.
