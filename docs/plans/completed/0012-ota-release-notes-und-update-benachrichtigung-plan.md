# OTA Release-Notes und Update-Benachrichtigung — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release-Notes aus `CHANGELOG.md` im Telegram-`/update`-Dialog anzeigen, automatische Telegram-Benachrichtigung nach Daemon-Neustart (Erfolg oder Rollback), und einen `/release`-Skill für geführten Release-Workflow.

**Feature:** `docs/features/0012-ota-release-notes-und-update-benachrichtigung.md`

**Architecture:** `CHANGELOG.md` ist die einzige Quelle für Release-Notes. CI extrahiert den obersten Abschnitt als Release-Body. Der Telegram-`/update`-Dialog zeigt Notes an (via GitHub API `body`-Feld, kein zweiter Request). Nach dem Daemon-Neustart liest `main.py` eine Notify-Datei und sendet Erfolg- oder Rollback-Nachricht. `update.sh` schreibt den Ausgang in diese Datei.

**Tech Stack:** Python 3.11 (urllib, pathlib), Bash, GitHub Actions (ubuntu-latest), unittest, unittest.mock

---

## Dateien

| Datei | Änderung |
|---|---|
| `CHANGELOG.md` | Neu: akkumuliertes Changelog, `---` als Trennzeichen |
| `.github/workflows/release.yml` | Release-Name mit Datum, Release-Body aus CHANGELOG |
| `src/daemon/ui/telegram_ui.py` | `_fetch_latest_release_info()` statt `_fetch_latest_release_tag()`, Notes im Dialog |
| `src/daemon/main.py` | OTA-Notify beim Start prüfen und senden |
| `scripts/update.sh` | Status (success/failed) in Notify-Datei schreiben |
| `tests/ui/test_update_handler.py` | Tests auf `_fetch_latest_release_info()` umstellen + neue Tests |
| `.claude/skills/skills/release/SKILL.md` | Neu: `/release`-Skill |

---

## Task 1: `CHANGELOG.md` anlegen

**Zweck:** Erste Version der Changelog-Datei mit dem korrekten Format anlegen.

**Files:**
- Create: `CHANGELOG.md`

- [ ] **Schritt 1: Datei anlegen**

```markdown
## 2026-06-14

- Versionsanzeige in /status
- Release-Notes im /update-Dialog
- Automatische Telegram-Benachrichtigung nach Update (Erfolg und Rollback)
- /release-Skill für geführten Release-Workflow

---
```

- [ ] **Schritt 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "chore: CHANGELOG.md anlegen"
```

---

## Task 2: CI-Pipeline erweitern — Release-Name und Release-Body

**Zweck:** CI setzt einen lesbaren Release-Namen mit Datum und befüllt den Release-Body aus `CHANGELOG.md`.

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Schritt 1: Failing test (manuell verifizieren)**

Vor der Änderung: aktueller Release auf GitHub hat `name == VERSION` und leeren Body.

- [ ] **Schritt 2: `Versionsdateien generieren`-Step erweitern**

Das Datum als Output-Variable ergänzen:

```yaml
- name: Versionsdateien generieren
  id: version
  run: |
    VERSION=$(git describe --tags --exact-match 2>/dev/null || echo "v0.0.0-$(git rev-parse --short HEAD)")
    Z2M_VERSION=$(node -p "require('./vendor/zigbee2mqtt/package.json').version")
    RELEASE_DATE=$(date +%Y-%m-%d)
    echo "VERSION=$VERSION"         >> $GITHUB_OUTPUT
    echo "Z2M_VERSION=$Z2M_VERSION" >> $GITHUB_OUTPUT
    echo "RELEASE_DATE=$RELEASE_DATE" >> $GITHUB_OUTPUT
    echo "$VERSION"     > VERSION
    echo "$Z2M_VERSION" > Z2M_VERSION
```

- [ ] **Schritt 3: Release-Body aus `CHANGELOG.md` extrahieren**

Neuen Step nach `Versionsdateien generieren` einfügen:

```yaml
- name: Release-Notes extrahieren
  id: notes
  run: |
    # Alles zwischen erstem ## und erstem --- extrahieren
    NOTES=$(awk '/^## /{found=1; next} found && /^---/{exit} found{print}' CHANGELOG.md | sed '/^[[:space:]]*$/d' | head -50)
    echo "NOTES<<EOF" >> $GITHUB_OUTPUT
    echo "$NOTES"     >> $GITHUB_OUTPUT
    echo "EOF"        >> $GITHUB_OUTPUT
```

- [ ] **Schritt 4: `GitHub Release anlegen`-Step anpassen**

```yaml
- name: GitHub Release anlegen
  uses: softprops/action-gh-release@v2
  with:
    tag_name: ${{ steps.version.outputs.VERSION }}
    name: "${{ steps.version.outputs.RELEASE_DATE }} — ${{ steps.version.outputs.VERSION }}"
    body: ${{ steps.notes.outputs.NOTES }}
    files: garden-${{ steps.version.outputs.VERSION }}.tar.gz
    generate_release_notes: false
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Schritt 5: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "feat: Release-Name mit Datum und Release-Body aus CHANGELOG.md"
```

---

## Task 3: `_fetch_latest_release_info()` — API-Erweiterung

**Zweck:** Einzelner API-Aufruf liefert jetzt Tag, Release-Name und Notes. `handle_update()` zeigt Notes im Dialog an.

**Files:**
- Modify: `src/daemon/ui/telegram_ui.py`
- Modify: `tests/ui/test_update_handler.py`

- [ ] **Schritt 1: Failing tests schreiben**

In `tests/ui/test_update_handler.py` alle Stellen die `_fetch_latest_release_tag` importieren oder mocken auf `_fetch_latest_release_info` umstellen. Neue Testfälle ergänzen:

```python
# _fetch_latest_release_info() gibt dict zurück: {"tag": ..., "name": ..., "notes": ...}

class TestFetchLatestReleaseInfo(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.config")
    @patch("urllib.request.urlopen")
    def test_returns_info_from_api(self, mock_urlopen, mock_config):
        mock_config.GITHUB_PAT = "test-pat"
        mock_config.GITHUB_REPO = "test/garden"
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"tag_name": "v2.0.0", "name": "2026-06-14 — v2.0.0", "body": "- Feature X"}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        info = _fetch_latest_release_info()
        self.assertEqual(info["tag"], "v2.0.0")
        self.assertEqual(info["name"], "2026-06-14 — v2.0.0")
        self.assertIn("Feature X", info["notes"])

    @patch("daemon.ui.telegram_ui.config")
    def test_returns_fallback_on_missing_config(self, mock_config):
        mock_config.GITHUB_PAT = ""
        mock_config.GITHUB_REPO = ""
        info = _fetch_latest_release_info()
        self.assertEqual(info["tag"], "?")
        self.assertEqual(info["notes"], "")


class TestHandleUpdateMitNotes(unittest.TestCase):

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui._fetch_latest_release_info",
           return_value={"tag": "v1.2.0", "name": "2026-06-14 — v1.2.0", "notes": "- Feature X\n- Feature Y"})
    @patch("daemon.ui.telegram_ui._read_local_version", return_value="v1.0.0")
    def test_zeigt_notes_im_dialog(self, _local, _info, mock_client):
        handle_update(12345)
        text = mock_client.send_message.call_args[0][1]
        self.assertIn("Feature X", text)
        self.assertIn("2026-06-14", text)

    @patch("daemon.ui.telegram_ui.telegram_client")
    @patch("daemon.ui.telegram_ui._fetch_latest_release_info",
           return_value={"tag": "v1.2.0", "name": "2026-06-14 — v1.2.0", "notes": "x" * 1000})
    @patch("daemon.ui.telegram_ui._read_local_version", return_value="v1.0.0")
    def test_kuerzt_notes_auf_800_zeichen(self, _local, _info, mock_client):
        handle_update(12345)
        text = mock_client.send_message.call_args[0][1]
        # Notes-Abschnitt darf nicht länger als 800 Zeichen sein
        notes_start = text.find("📋")
        notes_section = text[notes_start:] if notes_start >= 0 else text
        self.assertLessEqual(len(notes_section), 900)  # Overhead für Label
        self.assertIn("…", text)
```

- [ ] **Schritt 2: Tests laufen lassen — müssen FAIL**

```powershell
python -m unittest tests.ui.test_update_handler -v
```

- [ ] **Schritt 3: `_fetch_latest_release_tag()` zu `_fetch_latest_release_info()` refaktorieren**

```python
def _fetch_latest_release_info() -> dict:
    """Gibt {"tag": str, "name": str, "notes": str} zurück. Felder sind "" / "?" bei Fehler."""
    if not config.GITHUB_PAT or not config.GITHUB_REPO:
        return {"tag": "?", "name": "?", "notes": ""}
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {config.GITHUB_PAT}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "GardenIrrigationDaemon/1.0",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return {
                "tag":   data.get("tag_name", "?"),
                "name":  data.get("name", "?"),
                "notes": data.get("body", ""),
            }
    except Exception:
        return {"tag": "?", "name": "?", "notes": ""}
```

- [ ] **Schritt 4: `handle_update()` anpassen**

```python
def handle_update(chat_id: int):
    local = _read_local_version()
    info = _fetch_latest_release_info()
    remote_tag = info["tag"]
    remote_name = info["name"]
    notes_raw = info["notes"] or ""

    if local == remote_tag:
        telegram_client.send_message(
            chat_id,
            f"✅ Bereits aktuell ({local}). Kein Update verfügbar."
        )
        return

    # Notes kürzen
    if len(notes_raw) > 800:
        notes_raw = notes_raw[:800] + "…"
    notes_section = f"\n\n📋 **Was ist neu:**\n{notes_raw}" if notes_raw else ""

    telegram_client.send_message(
        chat_id,
        f"🔄 **Software-Update verfügbar**\n\n"
        f"Installiert: `{local}`\n"
        f"Verfügbar:   `{remote_name}`"
        f"{notes_section}\n\n"
        f"Soll das Update jetzt installiert werden?\n"
        f"_(Dauer: ca. 1–5 Minuten. Der Daemon startet neu.)_",
        {"inline_keyboard": [[
            {"text": "✓ Jetzt installieren", "callback_data": "update_confirm"},
            {"text": "✗ Abbrechen",          "callback_data": "update_cancel"},
        ]]}
    )
```

- [ ] **Schritt 5: Tests laufen lassen — müssen PASS**

```powershell
python -m unittest tests.ui.test_update_handler -v
python -m unittest discover tests
```

- [ ] **Schritt 6: Commit**

```bash
git add src/daemon/ui/telegram_ui.py tests/ui/test_update_handler.py
git commit -m "feat: _fetch_latest_release_info() mit Release-Notes, Truncation auf 800 Zeichen"
```

---

## Task 4: OTA-Notify-Mechanismus

**Zweck:** `update.sh` schreibt Ausgang in Notify-Datei. Beim Daemon-Start liest `main.py` die Datei und sendet Telegram-Nachricht.

**Files:**
- Modify: `scripts/update.sh`
- Modify: `src/daemon/main.py`
- Create oder Modify: `tests/test_main_startup.py`

### 4a: `update.sh` — Status in Notify-Datei schreiben

- [ ] **Schritt 1: Erfolgs-Pfad anpassen**

```bash
NOTIFY_FILE="/tmp/garden-ota-notify"

# Im Erfolgs-Pfad (nach Health-Check OK), vor exit 0:
if [ -f "$NOTIFY_FILE" ]; then
    CHAT_ID=$(head -1 "$NOTIFY_FILE")
    printf '%s\nsuccess\n%s\n' "$CHAT_ID" "$RELEASE_TAG" > "$NOTIFY_FILE"
fi
```

- [ ] **Schritt 2: Rollback-Pfad anpassen**

```bash
# Im Rollback-Pfad, vor exit 1:
if [ -f "$NOTIFY_FILE" ]; then
    CHAT_ID=$(head -1 "$NOTIFY_FILE")
    printf '%s\nfailed\n%s\n' "$CHAT_ID" "$LOCAL_VERSION" > "$NOTIFY_FILE"
fi
```

### 4b: `update_confirm`-Handler — `chat_id` in Notify-Datei schreiben

- [ ] **Schritt 3: In `telegram_ui.py`, im `update_confirm`-Zweig von `_process_callback_query`**

```python
elif data == "update_confirm":
    telegram_client.answer_callback_query(cb_id, "Update wird gestartet...")
    # chat_id für Post-Update-Benachrichtigung persistieren
    notify_file = Path("/tmp/garden-ota-notify")
    notify_file.write_text(str(chat_id))
    scripts_dir = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
    subprocess.Popen(["bash", str(scripts_dir / "update.sh")])
    telegram_client.send_message(
        chat_id,
        "⏳ Update gestartet. Bitte 1–5 Minuten warten, dann `/status` prüfen."
    )
```

### 4c: `main.py` — Notify-Datei beim Start prüfen

- [ ] **Schritt 4: Failing test schreiben**

```python
# tests/test_main_startup.py
class TestOtaNotify(unittest.TestCase):

    @patch("daemon.ui.telegram_client.send_message")
    def test_sendet_erfolg_nachricht(self, mock_send):
        notify = Path("/tmp/garden-ota-notify")
        notify.write_text("12345\nsuccess\nv1.2.3\n")
        from daemon.main import _check_ota_notify
        _check_ota_notify()
        mock_send.assert_called_once()
        text = mock_send.call_args[0][1]
        self.assertIn("erfolgreich", text.lower())
        self.assertIn("v1.2.3", text)
        self.assertFalse(notify.exists())

    @patch("daemon.ui.telegram_client.send_message")
    def test_sendet_rollback_nachricht(self, mock_send):
        notify = Path("/tmp/garden-ota-notify")
        notify.write_text("12345\nfailed\nv1.0.0\n")
        from daemon.main import _check_ota_notify
        _check_ota_notify()
        text = mock_send.call_args[0][1]
        self.assertIn("fehlgeschlagen", text.lower())
        self.assertFalse(notify.exists())

    def test_keine_nachricht_ohne_datei(self):
        notify = Path("/tmp/garden-ota-notify")
        if notify.exists():
            notify.unlink()
        from daemon.main import _check_ota_notify
        # Darf keine Exception werfen
        _check_ota_notify()
```

- [ ] **Schritt 5: Tests laufen lassen — müssen FAIL**

```powershell
python -m unittest tests.test_main_startup -v
```

- [ ] **Schritt 6: `_check_ota_notify()` in `main.py` implementieren**

```python
def _check_ota_notify():
    notify_file = Path("/tmp/garden-ota-notify")
    if not notify_file.exists():
        return
    try:
        lines = notify_file.read_text().splitlines()
        chat_id = int(lines[0])
        status = lines[1] if len(lines) > 1 else "unknown"
        version = lines[2] if len(lines) > 2 else "?"
        from .ui import telegram_client
        if status == "success":
            telegram_client.send_message(chat_id, f"✅ Update auf `{version}` erfolgreich installiert.")
        elif status == "failed":
            telegram_client.send_message(chat_id, f"❌ Update fehlgeschlagen — Rollback auf `{version}` durchgeführt.")
    except Exception as e:
        logger.warning(f"OTA-Notify konnte nicht verarbeitet werden: {e}")
    finally:
        notify_file.unlink(missing_ok=True)
```

In `main()` nach dem Telegram-Bot-Start aufrufen:

```python
# Nach telegram_bot.start_bot():
_check_ota_notify()
```

- [ ] **Schritt 7: Tests laufen lassen — müssen PASS**

```powershell
python -m unittest tests.test_main_startup -v
python -m unittest discover tests
```

- [ ] **Schritt 8: Shell-Tests für `update.sh` erweitern**

In `scripts/test_update_sh.sh` zwei neue Szenarien:
- Szenario 7: Notify-Datei mit `chat_id` vorhanden → nach erfolgreichem Update enthält sie `success`
- Szenario 8: Notify-Datei vorhanden → nach Rollback enthält sie `failed`

- [ ] **Schritt 9: Commit**

```bash
git add scripts/update.sh src/daemon/main.py src/daemon/ui/telegram_ui.py \
        tests/test_main_startup.py scripts/test_update_sh.sh
git commit -m "feat: OTA-Notify — success/failed Telegram-Nachricht nach Daemon-Neustart"
```

---

## Task 5: `/release`-Skill

**Zweck:** Geführter Release-Workflow — vergleicht `release..master`, liest neue Feature-Docs, schlägt Changelog vor, committet und pusht.

**Files:**
- Create: `.claude/skills/skills/release/SKILL.md`

- [ ] **Schritt 1: Skill-Verzeichnis anlegen und SKILL.md schreiben**

```markdown
---
name: release
description: Führt durch den Release-Prozess: vergleicht release..master, liest neue Feature-Docs, schlägt CHANGELOG-Eintrag vor, committet und pusht den Release-Branch.
---

## Ablauf

Du bist auf dem `master`-Branch. Führe die folgenden Schritte der Reihe nach aus.

### 1. Änderungen seit letztem Release ermitteln

Führe aus:
- `git log release..master --oneline` — alle Commits seit letztem Merge in release
- `git diff release..master -- docs/features/completed/` — neu abgeschlossene Features

Lies die neuen Feature-Dokumente vollständig. Notiere Titel und Kernaussage jedes neuen Features.

### 2. Changelog-Vorschlag erstellen

Synthetisiere aus Feature-Titeln und Commit-Messages einen Changelog-Vorschlag im Format:

```
## YYYY-MM-DD

- <Stichpunkt 1>
- <Stichpunkt 2>
```

Verwende das heutige Datum. Halte die Stichpunkte kurz (max. 80 Zeichen pro Zeile) und benutzerfreundlich — keine technischen Dateinamen.

Zeige den Vorschlag dem Benutzer und warte auf Bestätigung oder Korrekturen.

### 3. CHANGELOG.md aktualisieren

Füge den bestätigten Eintrag am Anfang von `CHANGELOG.md` ein, gefolgt von `---`. Bestehende Einträge bleiben unberührt.

### 4. Committen und pushen

```bash
git add CHANGELOG.md
git commit -m "chore: Release YYYY-MM-DD"
git push origin master:release
```

Melde dem Benutzer: „Release ausgelöst. Die CI-Pipeline baut jetzt — du erhältst eine Telegram-Benachrichtigung wenn das Build fertig ist."
```

- [ ] **Schritt 2: Commit**

```bash
git add .claude/skills/skills/release/SKILL.md
git commit -m "feat: /release-Skill für geführten Release-Workflow"
```

---

## Abschluss-Checkliste

- [ ] `CHANGELOG.md` im Repo, korrektes Format mit `---` Trennzeichen
- [ ] CI setzt Release-Name mit Datum und befüllt Release-Body aus CHANGELOG
- [ ] `/update`-Dialog zeigt Release-Notes (auf 800 Zeichen gekürzt)
- [ ] `update_confirm` schreibt `chat_id` in `/tmp/garden-ota-notify`
- [ ] `update.sh` schreibt `success`/`failed` + Version in Notify-Datei
- [ ] Daemon sendet nach Neustart automatisch Erfolgs- oder Rollback-Nachricht
- [ ] `/release`-Skill verfügbar und getestet
- [ ] Alle Python-Tests grün: `python -m unittest discover tests`
- [ ] Shell-Tests grün: `bash scripts/test_update_sh.sh`
