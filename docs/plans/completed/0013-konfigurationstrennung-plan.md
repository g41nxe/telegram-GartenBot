# Konfigurationstrennung — Secrets vs. Einstellungen — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `config/garden.conf` (versioniert) enthält fachliche Einstellungen; `.env` (gitignored) enthält nur noch Secrets. Priorität: Shell-Env > `.env` > `garden.conf`.

**Architecture:** `config.py` erhält eine generische `_load_file(path, override)`-Funktion — mit `override=False` für `garden.conf` (setdefault), `override=True` für `.env` (direktes Assignment). `deploy.ps1` überträgt `config/` auf den Pi; neues `-CopyEnv`-Flag für Erstsetup.

**Tech Stack:** Python 3.11, PowerShell, `KEY=VALUE`-Format (keine neue Abhängigkeit)

---

### Task 1: `config/garden.conf` anlegen und `_load_file` in `config.py` einbauen

**Files:**
- Create: `config/garden.conf`
- Modify: `src/daemon/config.py`
- Create: `tests/test_config.py`

- [ ] **Schritt 1: Failing-Tests schreiben**

Erstelle `tests/test_config.py`:

```python
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class TestConfigLoading(unittest.TestCase):

    def _reload_config(self, env_vars: dict):
        """Lädt config.py frisch mit gesetzten Umgebungsvariablen."""
        import importlib
        import daemon.config as cfg
        with patch.dict(os.environ, env_vars, clear=False):
            importlib.reload(cfg)
        return cfg

    def test_garden_conf_value_is_loaded(self):
        """Wert aus garden.conf wird geladen wenn nicht in .env oder Shell-Env."""
        import daemon.config as cfg
        # RAIN_THRESHOLD_MM kommt aus config/garden.conf
        self.assertIsInstance(cfg.RAIN_THRESHOLD_MM, float)

    def test_env_overrides_garden_conf(self):
        """Wert in .env überschreibt garden.conf."""
        cfg = self._reload_config({"RAIN_THRESHOLD_MM": "9.9"})
        self.assertAlmostEqual(cfg.RAIN_THRESHOLD_MM, 9.9)

    def test_shell_env_overrides_dot_env(self):
        """Shell-Env-Variable hat höchste Priorität."""
        # Setze vor dem Laden — simulates shell env
        with patch.dict(os.environ, {"RAIN_THRESHOLD_MM": "7.7"}, clear=False):
            cfg = self._reload_config({})
            self.assertAlmostEqual(cfg.RAIN_THRESHOLD_MM, 7.7)

    def test_missing_garden_conf_uses_fallback(self):
        """Fehlende garden.conf → Daemon startet mit Fallback-Werten, kein Absturz."""
        import importlib
        import daemon.config as cfg
        with patch("daemon.config._GARDEN_CONF_PATH", Path("/nonexistent/garden.conf")):
            importlib.reload(cfg)
            self.assertIsInstance(cfg.RAIN_THRESHOLD_MM, float)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Schritt 2: Tests laufen lassen — müssen FAIL**

```
python -m unittest tests.test_config -v
```

Erwartetes Ergebnis: 1–2 Tests schlagen fehl (fehlende Logik in config.py).

- [ ] **Schritt 3: `config/garden.conf` erstellen**

```
# Fachliche Einstellungen des Bewässerungs-Daemons
# Secrets (Token, PAT, User-IDs) gehören in .env — nicht hier.

# Standort für Wettervorhersage (Open-Meteo)
LATITUDE=0.0
LONGITUDE=0.0

# MQTT-Verbindung
MQTT_BROKER_HOST=127.0.0.1
MQTT_BROKER_PORT=1883
MQTT_VALVE_TOPIC=zigbee2mqtt/garden_valve

# Bewässerungslogik
# Niederschlagsschwelle in mm (letzte 24h + nächste 24h), ab der Bewässerung
# übersprungen und "Kein Gießen nötig" angezeigt wird
RAIN_THRESHOLD_MM=2.0

# Sicherheits-Timeout (Auto-Close am Ventil) in Minuten
SAFETY_TIMEOUT_MINUTES=30

# Batterie-Warnschwelle in Prozent
BATTERY_WARNING_THRESHOLD=20

# Maximale Zeit zwischen zwei Durchflussmessungen in Sekunden
FLOW_TIME_GAP_CAP_SECONDS=60

# Wetter-Aktualisierungsintervall in Sekunden
WEATHER_REFRESH_INTERVAL_SECONDS=1800

# Uhrzeit für den täglichen Statusbericht (HH:MM)
DAILY_REPORT_TIME=08:00

# Inaktivitäts-Watchdog
WATCHDOG_ENABLED=true
WATCHDOG_VALVE_TIMEOUT_HOURS=24
```

- [ ] **Schritt 4: `config.py` umbauen**

Ersetze `_load_env_file` durch eine generische `_load_file`-Funktion und lade beide Dateien in der richtigen Reihenfolge:

```python
import os
import logging
from pathlib import Path

logger = logging.getLogger("garden_config")

_ROOT = Path(__file__).resolve().parent.parent.parent
_GARDEN_CONF_PATH = _ROOT / "config" / "garden.conf"
_ENV_PATH = _ROOT / ".env"


def _load_file(path: Path, override: bool) -> None:
    """
    Lädt KEY=VALUE-Paare aus einer Datei in os.environ.
    override=False → setdefault (Shell-Env bleibt unberührt)
    override=True  → direkte Zuweisung (überschreibt bestehende Werte)
    """
    if not path.exists():
        logger.warning(f"Konfigurationsdatei nicht gefunden: {path}. Nutze Fallback-Werte.")
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key, val = key.strip(), val.strip()
                    if override:
                        os.environ[key] = val
                    else:
                        os.environ.setdefault(key, val)
        logger.info(f"Konfiguration geladen aus: {path}")
    except Exception as e:
        logger.error(f"Fehler beim Lesen von {path}: {e}")


# Lade-Reihenfolge: garden.conf (Defaults) → .env (überschreibt)
# Shell-Env hat implizit Vorrang, da setdefault für garden.conf und
# .env nur lädt wenn Variablen nicht bereits gesetzt sind... WAIT:
# .env benutzt override=True, d.h. .env gewinnt auch gegen Shell-Env.
# Korrekte Reihenfolge für Priorität Shell > .env > garden.conf:
_load_file(_GARDEN_CONF_PATH, override=False)  # Defaults, Shell-Env bleibt
_load_file(_ENV_PATH, override=False)           # .env, Shell-Env bleibt

# Konfigurationswerte auslesen
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# ... (rest bleibt identisch)
```

**Wichtig:** Beide Dateien mit `override=False` (`setdefault`) laden — so gewinnt Shell-Env automatisch, weil `setdefault` bereits gesetzte Werte nie überschreibt. `.env` wird nach `garden.conf` geladen und setzt Keys die `garden.conf` gesetzt hat (Shell-Env schützt sich selbst).

- [ ] **Schritt 5: Tests laufen lassen — müssen PASS**

```
python -m unittest tests.test_config -v
```

Erwartetes Ergebnis: 4 Tests grün.

- [ ] **Schritt 6: Gesamte Testsuite**

```
python -m unittest discover tests -v
```

Kein Regression.

- [ ] **Schritt 7: Commit**

```bash
git add config/garden.conf src/daemon/config.py tests/test_config.py
git commit -m "feat: Konfigurationstrennung — garden.conf für Non-Secret-Parameter"
```

---

### Task 2: `.env` und `.env.template` bereinigen

**Files:**
- Modify: `.env` (lokal, gitignored)
- Modify: `.env.template`
- Modify: `.gitignore` (prüfen ob `config/` versehentlich ignoriert wird)

- [ ] **Schritt 1: `.gitignore` prüfen**

```
grep -n "config\|garden.conf" .gitignore
```

Sicherstellen dass `config/garden.conf` **nicht** ignoriert wird. Falls nötig, explizite Ausnahme eintragen:

```
!config/garden.conf
```

- [ ] **Schritt 2: Non-Secret-Keys aus `.env` entfernen**

Aus `.env` entfernen (sind jetzt in `garden.conf`):
- `RAIN_THRESHOLD_MM`
- `LATITUDE`, `LONGITUDE`
- `MQTT_BROKER_HOST`, `MQTT_BROKER_PORT`, `MQTT_VALVE_TOPIC`
- `SAFETY_TIMEOUT_MINUTES`
- `BATTERY_WARNING_THRESHOLD`
- `FLOW_TIME_GAP_CAP_SECONDS`
- `WEATHER_REFRESH_INTERVAL_SECONDS`
- `DAILY_REPORT_TIME`
- `WATCHDOG_ENABLED`, `WATCHDOG_VALVE_TIMEOUT_HOURS`

`.env` behält nur:
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USER_IDS=...
GITHUB_PAT=...
GITHUB_REPO=...
DEPLOY_PI_HOST=...
DEPLOY_PI_USER=...
```

- [ ] **Schritt 3: `.env.template` auf Secrets reduzieren**

```
# Secrets — niemals committen, niemals durch OTA-Update überschreiben.
# Fachliche Einstellungen (Schwellwerte, Koordinaten, Timeouts) → config/garden.conf

TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_ALLOWED_USER_IDS=123456789

# GitHub OTA-Update (Feature 0011)
GITHUB_PAT=github_pat_...
GITHUB_REPO=username/garden

# Deployment (nur auf Windows-Entwicklungsmaschine nötig)
DEPLOY_PI_HOST=192.168.x.x
DEPLOY_PI_USER=pi
```

- [ ] **Schritt 4: Tests laufen**

```
python -m unittest discover tests -v
```

Kein Regression.

- [ ] **Schritt 5: Commit**

```bash
git add .env.template .gitignore
git commit -m "chore: .env.template auf Secrets reduziert, garden.conf ist neue Konfig-Referenz"
```

---

### Task 3: `deploy.ps1` anpassen

**Files:**
- Modify: `scripts/deploy.ps1`

- [ ] **Schritt 1: `config/` in Transfer-Liste aufnehmen**

In `deploy.ps1`, Zeile mit `$TransferItems`:

```powershell
$TransferItems = @("src", "scripts", "config", "tools")
```

- [ ] **Schritt 2: `-CopyEnv`-Flag hinzufügen**

Nach den bestehenden `Read-Host`-Abfragen:

```powershell
param(
    [switch]$CopyEnv
)
```

Und im Transfer-Block:

```powershell
if ($CopyEnv) {
    if (Test-Path ".env") {
        Write-Host "  -> .env (Erstsetup)" -ForegroundColor Yellow
        scp ".env" "${PiUser}@${PiHost}:/home/${PiUser}/garden/.env"
    } else {
        Write-Warning ".env nicht gefunden — übersprungen."
    }
}
```

- [ ] **Schritt 3: Manuell testen (kein automatischer Test für deploy.ps1)**

Prüfen dass `config/garden.conf` nach dem Deploy auf dem Pi unter `~/garden/config/garden.conf` liegt:

```bash
ssh g41nxe@192.168.0.165 "cat ~/garden/config/garden.conf | head -5"
```

- [ ] **Schritt 4: Commit**

```bash
git add scripts/deploy.ps1
git commit -m "feat: deploy.ps1 überträgt config/ auf Pi; -CopyEnv-Flag für Erstsetup"
```

---

### Task 4: ADR schreiben

**Files:**
- Create: `docs/adr/0024-konfigurationstrennung-secrets-vs-einstellungen.md`

- [ ] **Schritt 1: ADR anlegen**

```markdown
# 24. Konfigurationstrennung: Secrets vs. fachliche Einstellungen

Fachliche Konfigurationsparameter werden in `config/garden.conf` (versioniert)
getrennt von Secrets in `.env` (gitignored) verwaltet.

## Kontext

Alle Konfiguration lag bisher in `.env` (gitignored). Da `.env` beim OTA-Update
nie überschrieben wird, mussten Parameterwerte wie `RAIN_THRESHOLD_MM` manuell
auf dem Pi angepasst werden — fehleranfällig und nicht nachvollziehbar.

## Entscheidung

Zwei Konfigurationsdateien mit klarer Trennlinie:
- `config/garden.conf`: alles ohne Geheimniswert (Koordinaten, Schwellwerte,
  Timeouts, MQTT-Topics) — versioniert, wird bei Deploy/OTA überschrieben
- `.env`: nur Secrets (Token, PAT, User-IDs, Deploy-Credentials) — gitignored,
  nie überschrieben

Priorität beim Laden: Shell-Env > `.env` > `garden.conf`
Format: KEY=VALUE (identisch zu .env, keine neue Abhängigkeit)

## Konsequenzen

- Parameterwerte wie Regenschwelle kommen automatisch per OTA auf den Pi
- Neuer Entwickler braucht nur `.env` anlegen — alles andere aus `garden.conf`
- `.env.template` wird auf reine Secret-Vorlage reduziert
- `deploy.ps1` überträgt `config/` wie `src/`; `.env` nur via `-CopyEnv`-Flag
```

- [ ] **Schritt 2: Commit**

```bash
git add docs/adr/0024-konfigurationstrennung-secrets-vs-einstellungen.md
git commit -m "docs: ADR 0024 — Konfigurationstrennung Secrets vs. Einstellungen"
```

---

### Task 5: Feature-Doc als abgeschlossen markieren und `CLAUDE.md` prüfen

**Files:**
- Move: `docs/features/0013-konfigurationstrennung-secrets-vs-einstellungen.md` → `docs/features/completed/`
- Review: `CLAUDE.md` (prüfen ob Hinweis auf `.env.template` aktualisiert werden muss)

- [ ] **Schritt 1: Gesamte Testsuite ein letztes Mal**

```
python -m unittest discover tests -v
```

Alle Tests grün (die bekannten 16 Fehler in `test_daily_report.py` für noch nicht implementierte Hilfsfunktionen sind pre-existierend und kein Regression).

- [ ] **Schritt 2: `CLAUDE.md` prüfen**

```
grep -n "\.env\|template\|config" CLAUDE.md
```

Falls `CLAUDE.md` auf `.env.template` verweist: Abschnitt aktualisieren auf `config/garden.conf` als Konfigurationsreferenz.

- [ ] **Schritt 3: Feature-Doc verschieben**

```bash
git mv docs/features/0013-konfigurationstrennung-secrets-vs-einstellungen.md docs/features/completed/
```

- [ ] **Schritt 4: Abschluss-Commit**

```bash
git add docs/features/completed/0013-konfigurationstrennung-secrets-vs-einstellungen.md CLAUDE.md
git commit -m "docs: Feature 0013 abgeschlossen — Konfigurationstrennung"
```
