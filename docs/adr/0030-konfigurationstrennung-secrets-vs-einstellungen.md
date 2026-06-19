# 30. Konfigurationstrennung: Secrets vs. fachliche Einstellungen

Fachliche Konfigurationsparameter werden in `config/garden.conf` (versioniert)
getrennt von Secrets in `.env` (gitignored) verwaltet.

## Kontext

Alle Konfiguration lag bisher in `.env` (gitignored). Da `.env` beim OTA-Update
nie überschrieben wird (ADR 0023), mussten fachliche Parameterwerte wie
`RAIN_THRESHOLD_MM` manuell auf dem Pi angepasst werden — fehleranfällig und
nicht nachvollziehbar im Git-Verlauf.

## Entscheidung

Zwei Konfigurationsdateien mit klarer Trennlinie:

- **`config/garden.conf`** (versioniert, wird bei Deploy und OTA-Update
  überschrieben): alle Parameter ohne Geheimniswert — Koordinaten, Schwellwerte,
  Timeouts, MQTT-Topics, Kamera-Einstellungen.
- **`.env`** (gitignored, nie überschrieben): ausschließlich Secrets —
  Telegram-Token, User-IDs, GitHub-PAT, Deploy-Zugangsdaten.

**Lade-Reihenfolge in `config.py`:** Shell-Env > `.env` > `garden.conf`

Umsetzung: `garden.conf` wird mit `setdefault` geladen (Shell-Env gewinnt);
`.env` wird mit direktem Assignment geladen, schützt aber Shell-Env-Schlüssel
(`_SHELL_ENV_KEYS` wird beim Modulstart einmalig erfasst).

**Format:** `KEY=VALUE` — identisch zu `.env`, keine neue Abhängigkeit.

## Konsequenzen

- Fachliche Parameterwerte kommen automatisch per OTA-Update auf die
  Steuerzentrale (Feature 0011).
- `config/garden.conf` dient als kanonische, lebendige Referenz aller
  Non-Secret-Parameter mit Standardwerten und Kommentaren.
- Ein neuer Entwickler braucht nur `.env` mit Secrets anlegen; alle anderen
  Werte kommen aus `garden.conf`.
- `.env.template` wird auf reine Secret-Vorlage reduziert.
- `deploy.ps1` überträgt `config/` zusammen mit `src/`; `.env` nur via
  `-CopyEnv`-Flag (Erstsetup).
- Neue Non-Secret-Konfigurationsvariablen werden direkt in `garden.conf`
  eingecheckt — kein manuelles Eingreifen auf der Steuerzentrale.
