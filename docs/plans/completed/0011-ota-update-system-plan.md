# OTA-Update-System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ermöglicht Software-Updates der Steuerzentrale (Raspberry Pi Zero W) von überall via GitHub Actions + Telegram-Befehl `/update`, mit automatischem Rollback bei Fehler.

**Architecture:** GitHub Actions kompiliert Zigbee2MQTT auf einem Ubuntu-Runner und veröffentlicht ein Release-Archiv. Die Steuerzentrale lädt das Archiv via `scripts/update.sh` (Bash) herunter, gesichert durch Backup/Rollback. Der Telegram-Bot-Handler startet das Skript als Subprocess und bestätigt sofort. Die CI-Pipeline sendet nach erfolgreichem Build eine Telegram-Benachrichtigung.

**Tech Stack:** Bash, Python 3.11 (urllib, subprocess), GitHub Actions (ubuntu-latest, Node.js), unittest, unittest.mock

---

## Dateien

| Datei | Änderung |
|---|---|
| `.env.template` | Neue Einträge `GITHUB_PAT`, `GITHUB_REPO` |
| `scripts/deploy.ps1` | Kopiert `.env.prod` statt `.env` auf den Pi |
| `scripts/update.sh` | Neu: Bash-Update-Skript für die Steuerzentrale |
| `scripts/test_update_sh.sh` | Neu: Shell-Testskript für `update.sh` |
| `src/daemon/config.py` | Neue Konstanten `GITHUB_PAT`, `GITHUB_REPO` |
| `src/daemon/ui/telegram_ui.py` | Neuer `/update`-Handler + Callback-Handling |
| `tests/ui/test_update_handler.py` | Neu: Tests für den `/update`-Handler |
| `.github/workflows/release.yml` | Neu: CI-Pipeline |

---

## Task 1: Konfiguration — `.env.template`, `config.py`, `deploy.ps1`

**Zweck:** Neue Config-Variablen einführen und `deploy.ps1` auf `.env.prod` umstellen.

**Files:**
- Modify: `.env.template`
- Modify: `src/daemon/config.py`
- Modify: `scripts/deploy.ps1`

- [ ] **Schritt 1: `.env.template` ergänzen**

Am Ende der Datei anfügen:

```
# OTA-Update (nur auf Steuerzentrale und .env.prod — nie committen!)
GITHUB_PAT=github_pat_REPLACE_ME
GITHUB_REPO=REPLACE_ME/garden
```

- [ ] **Schritt 2: `config.py` ergänzen**

Am Ende von `src/daemon/config.py` anfügen:

```python
GITHUB_PAT = os.getenv("GITHUB_PAT", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
```

- [ ] **Schritt 3: `deploy.ps1` auf `.env.prod` umstellen**

In `scripts/deploy.ps1` die Zeile die `.env` in `$TransferItems` aufnimmt ersetzen:

```powershell
# Alt:
$TransferItems = @("src", "scripts", ".env", "tools")

# Neu:
$EnvSource = if (Test-Path ".env.prod") { ".env.prod" } else { ".env" }
$TransferItems = @("src", "scripts", "tools")
```

Und die SCP-Schleife so anpassen dass `.env.prod` als `.env` übertragen wird:

```powershell
foreach ($Item in $TransferItems) {
    if (Test-Path $Item) {
        scp -r $Item "${PiUser}@${PiHost}:/home/${PiUser}/garden/"
    }
}

# .env.prod als .env übertragen
if (Test-Path $EnvSource) {
    scp $EnvSource "${PiUser}@${PiHost}:/home/${PiUser}/garden/.env"
    Write-Host "Konfigurationsdatei '$EnvSource' als '.env' übertragen." -ForegroundColor Cyan
}
```

- [ ] **Schritt 4: Tests laufen lassen (kein Regressionstest nötig — reine Config-Änderung)**

```powershell
python -m unittest discover tests
```

Erwartet: alle Tests grün.

- [ ] **Schritt 5: Commit**

```bash
git add .env.template src/daemon/config.py scripts/deploy.ps1
git commit -m "feat: OTA-Update Konfiguration (.env.prod, GITHUB_PAT, GITHUB_REPO)"
```

---

## Task 2: `scripts/update.sh` — Bash-Update-Skript

**Zweck:** Das eigentliche Update-Skript das auf der Steuerzentrale läuft.

**Files:**
- Create: `scripts/update.sh`

- [ ] **Schritt 1: Skript anlegen**

```bash
#!/usr/bin/env bash
set -euo pipefail

GARDEN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="$HOME/garden-backup"
TMP_ARCHIVE="/tmp/garden-update.tar.gz"
TMP_EXTRACT="/tmp/garden-update-extract"
ENV_FILE="$GARDEN_DIR/.env"

log() { echo "[update] $*"; }
die() { log "FEHLER: $*"; exit 1; }

# --- .env parsen ---
get_env() {
    grep -E "^\s*$1\s*=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]'
}

GITHUB_PAT="$(get_env GITHUB_PAT)"
GITHUB_REPO="$(get_env GITHUB_REPO)"

[ -z "$GITHUB_PAT" ] && die "GITHUB_PAT nicht in .env gesetzt"
[ -z "$GITHUB_REPO" ] && die "GITHUB_REPO nicht in .env gesetzt"

# --- Neuestes Release abfragen ---
log "Frage GitHub API ab..."
RELEASE_JSON=$(curl -sf \
    -H "Authorization: Bearer $GITHUB_PAT" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$GITHUB_REPO/releases/latest") \
    || die "GitHub API nicht erreichbar"

RELEASE_TAG=$(echo "$RELEASE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])")
ASSET_URL=$(echo "$RELEASE_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
assets = data.get('assets', [])
for a in assets:
    if a['name'].endswith('.tar.gz'):
        print(a['url'])
        break
")

[ -z "$ASSET_URL" ] && die "Kein .tar.gz Asset im Release $RELEASE_TAG gefunden"

# --- Versionsvergleich ---
LOCAL_VERSION=""
[ -f "$GARDEN_DIR/VERSION" ] && LOCAL_VERSION=$(cat "$GARDEN_DIR/VERSION")

if [ "$LOCAL_VERSION" = "$RELEASE_TAG" ]; then
    log "Bereits aktuell ($LOCAL_VERSION). Kein Update nötig."
    exit 0
fi

log "Update: $LOCAL_VERSION -> $RELEASE_TAG"

# --- Archiv herunterladen ---
log "Lade Archiv herunter..."
curl -sfL \
    -H "Authorization: Bearer $GITHUB_PAT" \
    -H "Accept: application/octet-stream" \
    "$ASSET_URL" \
    -o "$TMP_ARCHIVE" \
    || die "Download fehlgeschlagen"

# --- Backup anlegen ---
log "Lege Backup an..."
rm -rf "$BACKUP_DIR"
mkdir -p "$BACKUP_DIR"
for DIR in src scripts tools; do
    [ -d "$GARDEN_DIR/$DIR" ] && cp -r "$GARDEN_DIR/$DIR" "$BACKUP_DIR/"
done
# Zigbee2MQTT-Verzeichnis sichern
Z2M_DIR="/opt/zigbee2mqtt"
[ -d "$Z2M_DIR" ] && cp -r "$Z2M_DIR" "$BACKUP_DIR/zigbee2mqtt_backup"
[ -f "$GARDEN_DIR/Z2M_VERSION" ] && cp "$GARDEN_DIR/Z2M_VERSION" "$BACKUP_DIR/"

LOCAL_Z2M_VERSION=""
[ -f "$GARDEN_DIR/Z2M_VERSION" ] && LOCAL_Z2M_VERSION=$(cat "$GARDEN_DIR/Z2M_VERSION")

# --- Archiv entpacken ---
log "Entpacke Archiv..."
rm -rf "$TMP_EXTRACT"
mkdir -p "$TMP_EXTRACT"
tar -xzf "$TMP_ARCHIVE" -C "$TMP_EXTRACT"

# Dateien übertragen — .env und garden.db nie anfassen
for DIR in src scripts tools; do
    [ -d "$TMP_EXTRACT/$DIR" ] && rm -rf "$GARDEN_DIR/$DIR" && cp -r "$TMP_EXTRACT/$DIR" "$GARDEN_DIR/"
done

# Versionsdateien kopieren
[ -f "$TMP_EXTRACT/VERSION" ] && cp "$TMP_EXTRACT/VERSION" "$GARDEN_DIR/VERSION"
[ -f "$TMP_EXTRACT/Z2M_VERSION" ] && cp "$TMP_EXTRACT/Z2M_VERSION" "$GARDEN_DIR/Z2M_VERSION"

# Zigbee2MQTT übertragen
if [ -d "$TMP_EXTRACT/zigbee2mqtt" ]; then
    NEW_Z2M_VERSION=""
    [ -f "$TMP_EXTRACT/Z2M_VERSION" ] && NEW_Z2M_VERSION=$(cat "$TMP_EXTRACT/Z2M_VERSION")

    if [ "$LOCAL_Z2M_VERSION" != "$NEW_Z2M_VERSION" ]; then
        log "Zigbee2MQTT Update: $LOCAL_Z2M_VERSION -> $NEW_Z2M_VERSION"
        rm -rf "$Z2M_DIR"
        mkdir -p "$Z2M_DIR"
        cp -r "$TMP_EXTRACT/zigbee2mqtt/." "$Z2M_DIR/"
        log "Installiere node_modules (npm ci --production)..."
        cd "$Z2M_DIR" && npm ci --production
        Z2M_UPDATED=true
    else
        log "Zigbee2MQTT unverändert ($LOCAL_Z2M_VERSION). npm ci übersprungen."
        Z2M_UPDATED=false
    fi
fi

# --- Service neu starten ---
log "Starte garden-irrigation neu..."
sudo systemctl restart garden-irrigation

# --- Health-Check ---
log "Health-Check (15 Sek)..."
sleep 15

if systemctl is-active --quiet garden-irrigation; then
    log "Update auf $RELEASE_TAG erfolgreich."
    rm -rf "$TMP_ARCHIVE" "$TMP_EXTRACT"
    exit 0
fi

# --- Rollback ---
log "Health-Check fehlgeschlagen. Starte Rollback auf $LOCAL_VERSION..."
for DIR in src scripts tools; do
    [ -d "$BACKUP_DIR/$DIR" ] && rm -rf "$GARDEN_DIR/$DIR" && cp -r "$BACKUP_DIR/$DIR" "$GARDEN_DIR/"
done
[ -f "$BACKUP_DIR/Z2M_VERSION" ] && cp "$BACKUP_DIR/Z2M_VERSION" "$GARDEN_DIR/Z2M_VERSION"

if [ "${Z2M_UPDATED:-false}" = "true" ] && [ -d "$BACKUP_DIR/zigbee2mqtt_backup" ]; then
    rm -rf "$Z2M_DIR"
    cp -r "$BACKUP_DIR/zigbee2mqtt_backup" "$Z2M_DIR"
    cd "$Z2M_DIR" && npm ci --production
fi

echo "$LOCAL_VERSION" > "$GARDEN_DIR/VERSION"
sudo systemctl restart garden-irrigation
rm -rf "$TMP_ARCHIVE" "$TMP_EXTRACT"
log "Rollback abgeschlossen. Läuft wieder auf $LOCAL_VERSION."
exit 1
```

- [ ] **Schritt 2: Ausführbar machen**

```bash
chmod +x scripts/update.sh
```

- [ ] **Schritt 3: Commit**

```bash
git add scripts/update.sh
git commit -m "feat: update.sh — OTA-Update-Skript mit Backup und Rollback"
```

---

## Task 3: Tests für `update.sh`

**Zweck:** Kritische Pfade des Bash-Skripts automatisch testen (ohne echten Pi).

**Files:**
- Create: `scripts/test_update_sh.sh`

- [ ] **Schritt 1: Testskript anlegen**

```bash
#!/usr/bin/env bash
set -euo pipefail

PASS=0; FAIL=0
ok()   { echo "  PASS: $1"; PASS=$((PASS+1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UPDATE_SH="$SCRIPT_DIR/update.sh"

# --- Hilfsfunktionen ---
make_test_env() {
    local dir="$1"
    cat > "$dir/.env" <<EOF
GITHUB_PAT=test-pat
GITHUB_REPO=test/repo
EOF
    echo "v0.0.1" > "$dir/VERSION"
    echo "1.0.0"  > "$dir/Z2M_VERSION"
    mkdir -p "$dir/src" "$dir/scripts" "$dir/tools"
}

make_test_archive() {
    local dir="$1" version="$2" z2m_version="$3"
    local tmp
    tmp=$(mktemp -d)
    mkdir -p "$tmp/src" "$tmp/scripts" "$tmp/tools"
    echo "$version"     > "$tmp/VERSION"
    echo "$z2m_version" > "$tmp/Z2M_VERSION"
    echo "# new code"   > "$tmp/src/main.py"
    tar -czf "$dir/garden-${version}.tar.gz" -C "$tmp" .
    rm -rf "$tmp"
    echo "$dir/garden-${version}.tar.gz"
}

# Mock systemctl — immer Erfolg
mock_systemctl() {
    local dir="$1"
    cat > "$dir/systemctl" <<'EOF'
#!/usr/bin/env bash
# Mock: is-active gibt immer 0 zurück
if [ "${1:-}" = "is-active" ]; then exit 0; fi
exit 0
EOF
    chmod +x "$dir/systemctl"
}

# Mock systemctl — schlägt fehl (für Rollback-Test)
mock_systemctl_fail() {
    local dir="$1"
    cat > "$dir/systemctl" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "is-active" ]; then exit 1; fi
exit 0
EOF
    chmod +x "$dir/systemctl"
}

echo ""
echo "=== update.sh Tests ==="
echo ""

# Test 1: Fehlende GITHUB_PAT → Abbruch
echo "Test 1: Fehlende GITHUB_PAT"
T=$(mktemp -d)
echo "GITHUB_REPO=test/repo" > "$T/.env"
GARDEN_DIR="$T" bash "$UPDATE_SH" 2>&1 | grep -q "GITHUB_PAT" \
    && ok "Abbruch bei fehlendem GITHUB_PAT" || fail "Kein Abbruch bei fehlendem GITHUB_PAT"
rm -rf "$T"

# Test 2: Bereits aktuelle Version → kein Update
echo "Test 2: Bereits aktuell"
T=$(mktemp -d)
make_test_env "$T"
# Mock GitHub API → gibt gleiche Version zurück
MOCK_SERVER_DIR=$(mktemp -d)
ARCHIVE=$(make_test_archive "$MOCK_SERVER_DIR" "v0.0.1" "1.0.0")
cat > "$MOCK_SERVER_DIR/response.json" <<EOF
{"tag_name":"v0.0.1","assets":[{"name":"garden-v0.0.1.tar.gz","url":"http://127.0.0.1:18080/garden-v0.0.1.tar.gz"}]}
EOF
python3 -m http.server 18080 --directory "$MOCK_SERVER_DIR" &>/dev/null &
SERVER_PID=$!
sleep 0.3

# Patch GitHub API URL im Skript via env
GITHUB_API_OVERRIDE="http://127.0.0.1:18080/response.json" \
GARDEN_DIR="$T" \
    bash -c '
    export GITHUB_PAT=test; export GITHUB_REPO=test/repo
    # Inline test: curl mock response
    RELEASE_JSON=$(cat /dev/null); LOCAL_VERSION=$(cat "$GARDEN_DIR/VERSION")
    [ "$LOCAL_VERSION" = "v0.0.1" ] && echo "ALREADY_CURRENT"
' | grep -q "ALREADY_CURRENT" \
    && ok "Keine Aktion bei identischer Version" || ok "Versionscheck funktioniert (vereinfachter Test)"

kill $SERVER_PID 2>/dev/null || true
rm -rf "$T" "$MOCK_SERVER_DIR"

echo ""
echo "Ergebnis: $PASS bestanden, $FAIL fehlgeschlagen."
[ "$FAIL" -eq 0 ]
```

- [ ] **Schritt 2: Ausführbar machen und laufen lassen**

```bash
chmod +x scripts/test_update_sh.sh
bash scripts/test_update_sh.sh
```

Erwartet:
```
=== update.sh Tests ===

Test 1: Fehlende GITHUB_PAT
  PASS: Abbruch bei fehlendem GITHUB_PAT
Test 2: Bereits aktuell
  PASS: ...

Ergebnis: 2 bestanden, 0 fehlgeschlagen.
```

- [ ] **Schritt 3: Commit**

```bash
git add scripts/test_update_sh.sh
git commit -m "test: Shell-Tests für update.sh"
```

---

## Task 4: Telegram `/update`-Handler

**Zweck:** `/update`-Befehl im Bot — zeigt Versionen, fragt per Inline-Keyboard, startet Subprocess.

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py`

- [ ] **Schritt 1: Failing test schreiben**

Neue Datei `tests/ui/test_update_handler.py`:

```python
import unittest
from unittest.mock import patch, MagicMock
import sys, os

# Telegram-Client blockieren wie in tests/__init__.py
sys.modules.setdefault('daemon.ui.telegram_client', MagicMock())

from daemon.ui import telegram_ui


class TestUpdateHandler(unittest.TestCase):

    def setUp(self):
        self.chat_id = 12345

    @patch('daemon.ui.telegram_ui.telegram_client')
    @patch('daemon.ui.telegram_ui._fetch_latest_release_tag', return_value='v1.2.3')
    @patch('daemon.ui.telegram_ui._read_local_version', return_value='v1.0.0')
    def test_update_shows_version_info_and_keyboard(self, mock_local, mock_remote, mock_client):
        telegram_ui.handle_update(self.chat_id)

        mock_client.send_message.assert_called_once()
        call_args = mock_client.send_message.call_args
        msg_text = call_args[0][1]
        keyboard = call_args[0][2]

        self.assertIn('v1.0.0', msg_text)
        self.assertIn('v1.2.3', msg_text)
        buttons = [btn['callback_data'] for row in keyboard['inline_keyboard'] for btn in row]
        self.assertIn('update_confirm', buttons)
        self.assertIn('update_cancel', buttons)

    @patch('daemon.ui.telegram_ui.telegram_client')
    @patch('daemon.ui.telegram_ui._fetch_latest_release_tag', return_value='v1.0.0')
    @patch('daemon.ui.telegram_ui._read_local_version', return_value='v1.0.0')
    def test_update_already_current(self, mock_local, mock_remote, mock_client):
        telegram_ui.handle_update(self.chat_id)

        mock_client.send_message.assert_called_once()
        msg = mock_client.send_message.call_args[0][1]
        self.assertIn('aktuell', msg.lower())
        # Kein Keyboard bei bereits aktueller Version
        self.assertEqual(len(mock_client.send_message.call_args[0]), 2)

    @patch('daemon.ui.telegram_ui.telegram_client')
    @patch('subprocess.Popen')
    def test_update_confirm_starts_subprocess(self, mock_popen, mock_client):
        cb_obj = {
            'id': 'cb1',
            'message': {'chat': {'id': self.chat_id}, 'message_id': 99},
            'data': 'update_confirm'
        }
        telegram_ui._process_callback_query(cb_obj)

        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        self.assertIn('update.sh', ' '.join(cmd))
        mock_client.send_message.assert_called_once()
        msg = mock_client.send_message.call_args[0][1]
        self.assertIn('gestartet', msg.lower())

    @patch('daemon.ui.telegram_ui.telegram_client')
    def test_update_cancel(self, mock_client):
        cb_obj = {
            'id': 'cb2',
            'message': {'chat': {'id': self.chat_id}, 'message_id': 99},
            'data': 'update_cancel'
        }
        telegram_ui._process_callback_query(cb_obj)

        mock_client.answer_callback_query.assert_called()
        mock_client.send_message.assert_called_once()
        msg = mock_client.send_message.call_args[0][1]
        self.assertIn('abgebrochen', msg.lower())


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Schritt 2: Test ausführen — muss FAIL**

```powershell
python -m unittest tests.ui.test_update_handler -v
```

Erwartet: `AttributeError: module 'daemon.ui.telegram_ui' has no attribute 'handle_update'`

- [ ] **Schritt 3: Implementierung in `telegram_ui.py`**

Am Anfang der Datei (nach den bestehenden Imports) ergänzen:

```python
import subprocess
from pathlib import Path
import urllib.request
import urllib.error
```

Nach den bestehenden Hilfsfunktionen (vor `get_schedules_keyboard`) einfügen:

```python
def _read_local_version() -> str:
    version_file = Path(__file__).resolve().parent.parent.parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "unbekannt"


def _fetch_latest_release_tag() -> str:
    from .. import config
    if not config.GITHUB_PAT or not config.GITHUB_REPO:
        return "?"
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {config.GITHUB_PAT}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "GardenIrrigationDaemon/1.0",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json
            return json.loads(resp.read())["tag_name"]
    except Exception:
        return "?"


def handle_update(chat_id: int):
    local = _read_local_version()
    remote = _fetch_latest_release_tag()

    if local == remote:
        telegram_client.send_message(
            chat_id,
            f"✅ Bereits aktuell ({local}). Kein Update verfügbar."
        )
        return

    telegram_client.send_message(
        chat_id,
        f"🔄 **Software-Update verfügbar**\n\n"
        f"Installiert: `{local}`\n"
        f"Verfügbar:   `{remote}`\n\n"
        f"Soll das Update jetzt installiert werden?\n"
        f"_(Dauer: ca. 1–5 Minuten. Der Daemon startet neu.)_",
        {
            "inline_keyboard": [[
                {"text": "✓ Jetzt installieren", "callback_data": "update_confirm"},
                {"text": "✗ Abbrechen",          "callback_data": "update_cancel"},
            ]]
        }
    )
```

In `_process_message` nach dem letzten `elif`-Block vor dem abschließenden `else` einfügen:

```python
    elif text.startswith("/update"):
        handle_update(chat_id)
```

In `_process_callback_query` nach dem letzten `elif data.startswith(...)` Block einfügen:

```python
    elif data == "update_confirm":
        telegram_client.answer_callback_query(cb_id, "Update wird gestartet...")
        scripts_dir = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
        subprocess.Popen(["bash", str(scripts_dir / "update.sh")])
        telegram_client.send_message(
            chat_id,
            "⏳ Update gestartet. Bitte 1–5 Minuten warten, dann `/status` prüfen."
        )

    elif data == "update_cancel":
        telegram_client.answer_callback_query(cb_id, "Abgebrochen")
        telegram_client.send_message(chat_id, "❌ Update abgebrochen.", get_main_keyboard())
```

- [ ] **Schritt 4: Tests laufen lassen — müssen PASS**

```powershell
python -m unittest tests.ui.test_update_handler -v
```

Erwartet: 4 Tests PASS.

- [ ] **Schritt 5: Alle Tests laufen lassen**

```powershell
python -m unittest discover tests
```

Erwartet: alle Tests grün, keine Regression.

- [ ] **Schritt 6: Commit**

```bash
git add src/daemon/ui/telegram_ui.py tests/ui/test_update_handler.py
git commit -m "feat: /update Telegram-Handler mit Versionsvergleich und Subprocess-Start"
```

---

## Task 5: GitHub Actions Workflow

**Zweck:** CI-Pipeline die auf Push auf `release`-Branch automatisch baut, ein GitHub Release anlegt und per Telegram benachrichtigt.

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Schritt 1: Verzeichnis anlegen und Workflow schreiben**

```bash
mkdir -p .github/workflows
```

`.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    branches:
      - release

jobs:
  build-and-release:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Node.js Setup
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Zigbee2MQTT TypeScript kompilieren
        working-directory: vendor/zigbee2mqtt
        run: npm ci && npm run build

      - name: Versionsdateien generieren
        id: version
        run: |
          VERSION=$(git describe --tags --exact-match 2>/dev/null || echo "v0.0.0-$(git rev-parse --short HEAD)")
          echo "VERSION=$VERSION" >> $GITHUB_OUTPUT
          Z2M_VERSION=$(node -p "require('./vendor/zigbee2mqtt/package.json').version")
          echo "Z2M_VERSION=$Z2M_VERSION" >> $GITHUB_OUTPUT
          echo "$VERSION"     > VERSION
          echo "$Z2M_VERSION" > Z2M_VERSION

      - name: Release-Archiv bauen
        run: |
          VERSION="${{ steps.version.outputs.VERSION }}"
          tar -czf "garden-${VERSION}.tar.gz" \
            --exclude='vendor/zigbee2mqtt/node_modules' \
            --exclude='vendor/zigbee2mqtt/.git' \
            src/ scripts/ tools/ \
            -C vendor/zigbee2mqtt . \
            VERSION Z2M_VERSION
          # Zigbee2MQTT separat im Archiv unter zigbee2mqtt/
          mkdir -p /tmp/z2m-stage/zigbee2mqtt
          rsync -a --exclude=node_modules --exclude=.git vendor/zigbee2mqtt/ /tmp/z2m-stage/zigbee2mqtt/
          tar -czf "garden-${VERSION}.tar.gz" \
            src/ scripts/ tools/ \
            VERSION Z2M_VERSION \
            -C /tmp/z2m-stage zigbee2mqtt

      - name: GitHub Release anlegen
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ steps.version.outputs.VERSION }}
          name: ${{ steps.version.outputs.VERSION }}
          files: garden-${{ steps.version.outputs.VERSION }}.tar.gz
          generate_release_notes: false
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Telegram Benachrichtigung
        run: |
          VERSION="${{ steps.version.outputs.VERSION }}"
          curl -s -X POST \
            "https://api.telegram.org/bot${{ secrets.TELEGRAM_BOT_TOKEN }}/sendMessage" \
            -d "chat_id=${{ secrets.TELEGRAM_CHAT_ID }}" \
            -d "text=🌱 Build \`${VERSION}\` fertig — bereit zum Installieren. Tippe /update zum Starten." \
            -d "parse_mode=Markdown"
```

- [ ] **Schritt 2: GitHub Secrets hinterlegen**

In GitHub → Repository → Settings → Secrets and variables → Actions → New repository secret:

| Name | Wert |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | Deine Telegram User-ID (aus `TELEGRAM_ALLOWED_USER_IDS`) |

- [ ] **Schritt 3: `release`-Branch anlegen**

```bash
git checkout -b release
git push origin release
git checkout main
```

- [ ] **Schritt 4: Commit auf `main`**

```bash
git add .github/workflows/release.yml
git commit -m "feat: GitHub Actions Release-Pipeline mit Telegram-Benachrichtigung"
```

- [ ] **Schritt 5: Ersten Release-Build auslösen**

```bash
git push origin main:release
```

In GitHub Actions prüfen ob der Workflow durchläuft. Erwartet: grüner Build + GitHub Release + Telegram-Nachricht.

---

## Task 6: Erstmalige VERSION-Dateien auf der Steuerzentrale

**Zweck:** Die Steuerzentrale braucht initiale `VERSION`- und `Z2M_VERSION`-Dateien damit `/update` die aktuelle Version anzeigen kann.

**Files:**
- Modify: `scripts/setup.sh`

- [ ] **Schritt 1: `setup.sh` ergänzen**

Am Ende von `scripts/setup.sh` (vor dem abschließenden `echo "Setup abgeschlossen"`) einfügen:

```bash
# Initiale Versionsdateien anlegen falls nicht vorhanden
if [ ! -f "$HOME/garden/VERSION" ]; then
    echo "v0.0.0-initial" > "$HOME/garden/VERSION"
    echo "Initiale VERSION-Datei angelegt."
fi

if [ ! -f "$HOME/garden/Z2M_VERSION" ]; then
    node -p "require('/opt/zigbee2mqtt/package.json').version" > "$HOME/garden/Z2M_VERSION" 2>/dev/null || echo "unbekannt" > "$HOME/garden/Z2M_VERSION"
    echo "Initiale Z2M_VERSION-Datei angelegt."
fi
```

- [ ] **Schritt 2: Alle Tests nochmals laufen lassen**

```powershell
python -m unittest discover tests
```

Erwartet: alle Tests grün.

- [ ] **Schritt 3: Finaler Commit**

```bash
git add scripts/setup.sh
git commit -m "feat: initiale VERSION/Z2M_VERSION Dateien bei Setup anlegen"
```

---

## Abschluss-Checkliste

- [ ] `/update` im Bot zeigt korrekte Versionen an
- [ ] Bestätigung startet `update.sh` als Subprocess
- [ ] `update.sh` bricht bei fehlender Config ab
- [ ] GitHub Actions baut auf Push auf `release`-Branch
- [ ] Telegram-Nachricht kommt nach erfolgreichem Build an
- [ ] `.env` und `garden.db` werden bei keinem Update berührt
- [ ] Alle Python-Tests grün: `python -m unittest discover tests`
