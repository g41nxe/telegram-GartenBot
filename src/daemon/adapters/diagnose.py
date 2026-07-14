"""Diagnose-Paket (Feature 0041): sammelt Journal-Auszüge, Datenbank-Schnappschuss,
fachliche Konfiguration und System-Steckbrief zu einem Archiv für die Ferndiagnose.

Degradations-Politik: Jeder Baustein wird unabhängig eingesammelt; Fehler erzeugen
einen Lücken-Eintrag statt eines Gesamtabbruchs. Geheimnisse (.env) sind durch die
Whitelist-Bauweise ausgeschlossen — es wird nur aufgenommen, was hier explizit steht.
"""

import os
import shutil
import sqlite3
import logging
import platform
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from . import database
from .. import config

logger = logging.getLogger("garden_diagnose")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
GARDEN_CONF_PATH = _REPO_ROOT / "config" / "garden.conf"

JOURNAL_DAEMON_LINES = 2000
JOURNAL_Z2M_LINES = 500
# Sicherheitsabstand unter Telegrams 50-MB-Upload-Grenze für Bots
MAX_PACKET_BYTES = 45 * 1024 * 1024

_SERVICES = ("mosquitto", "zigbee2mqtt", "garden-irrigation")


def _journal(unit: str, lines: int) -> str:
    """Letzte Journal-Zeilen einer systemd-Unit (ohne root; braucht Journal-Lesegruppe)."""
    result = subprocess.run(
        ["journalctl", "-u", unit, "-n", str(lines), "--no-pager"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        detail = (result.stderr or "").strip() or f"journalctl Exit-Code {result.returncode}"
        raise RuntimeError(detail)
    return result.stdout


def _db_snapshot_to_file() -> str:
    """Konsistenter Schnappschuss der Datenbank auf eine Temp-Datei (SQLite-Backup-API).

    Gibt den Temp-Pfad zurück (Aufrufer räumt auf). Wird später per zipfile.write direkt
    von der Platte gepackt, damit die u. U. mehrere MB große DB nie komplett im RAM liegt
    (Schutz vor OOM auf der 512-MB-Steuerzentrale). Niemals eine Roh-Kopie der laufenden
    WAL-Datei. Eine fehlende Datenbank-Datei führt zum Fehler — sqlite3.connect würde sonst
    als Seiteneffekt eine leere anlegen.
    """
    if not os.path.isfile(database.DB_PATH):
        raise FileNotFoundError(f"Datenbank-Datei nicht gefunden: {database.DB_PATH}")
    fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src = sqlite3.connect(database.DB_PATH)
        try:
            dst = sqlite3.connect(tmp_path)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return tmp_path
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _uptime() -> str:
    seconds = float(Path("/proc/uptime").read_text().split()[0])
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours} h {minutes} min"


def _service_state(service: str) -> str:
    result = subprocess.run(
        ["systemctl", "is-active", service],
        capture_output=True, text=True, timeout=10,
    )
    return (result.stdout or "").strip() or "unbekannt"


def _system_info(missing: list) -> str:
    """System-Steckbrief; jede Zeile ist einzeln fehler-tolerant. Enthält die Lückenliste."""
    lines = [
        "# System-Steckbrief (Diagnose-Paket)",
        f"Erstellt: {datetime.now().isoformat(timespec='seconds')}",
    ]

    def add(label, fn):
        try:
            lines.append(f"{label}: {fn()}")
        except Exception as e:
            lines.append(f"{label}: unbekannt ({e})")

    add("Version", config.read_version)
    add("Python", platform.python_version)
    add("Plattform", platform.platform)
    add("Uptime", _uptime)
    add("Freier Speicher", lambda: f"{shutil.disk_usage(str(_REPO_ROOT)).free // (1024 * 1024)} MB")
    for service in _SERVICES:
        add(f"Dienst {service}", lambda s=service: _service_state(s))

    if missing:
        lines.append("")
        lines.append("# Lücken (nicht einsammelbar)")
        lines.extend(f"- {m}" for m in missing)
    return "\n".join(lines) + "\n"


def collect_diagnose_paket(max_bytes: int = MAX_PACKET_BYTES) -> "tuple[bytes | None, list[str]]":
    """Sammelt das Diagnose-Paket ein. Gibt (Archiv-Bytes, Lückenliste) zurück.

    Bausteine werden unabhängig eingesammelt (Degradations-Politik). Überschreitet
    das Archiv max_bytes, weicht der Datenbank-Schnappschuss (größter Baustein).
    Das ZIP wird auf einer Temp-Datei aufgebaut und die DB von der Platte gestreamt,
    damit die u. U. mehrere MB große DB nicht zusätzlich als RAM-Kopie anfällt.
    None entsteht nur, wenn selbst das Packen scheitert.
    """
    text_parts: dict = {}   # kleine Textbausteine (Journale, Konfiguration)
    missing: list = []
    db_snap_path = None

    def _try_text(name, fn):
        try:
            text_parts[name] = fn()
        except Exception as e:
            logger.warning(f"Diagnose-Baustein '{name}' nicht einsammelbar: {e}")
            missing.append(f"{name}: {e}")

    _try_text("journal_daemon.txt", lambda: _journal("garden-irrigation", JOURNAL_DAEMON_LINES))
    _try_text("journal_zigbee2mqtt.txt", lambda: _journal("zigbee2mqtt", JOURNAL_Z2M_LINES))
    _try_text("garden.conf", lambda: GARDEN_CONF_PATH.read_text(encoding="utf-8"))

    try:
        db_snap_path = _db_snapshot_to_file()
    except Exception as e:
        logger.warning(f"Diagnose-Baustein 'garden.db' nicht einsammelbar: {e}")
        missing.append(f"garden.db: {e}")

    def _build(include_db: bool) -> str:
        fd, zpath = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(text_parts):
                zf.writestr(name, text_parts[name])
            # Steckbrief zuletzt geschrieben: trägt die aktuelle Lückenliste in sich
            zf.writestr("system_info.txt", _system_info(missing))
            if include_db and db_snap_path:
                zf.write(db_snap_path, arcname="garden.db")
        return zpath

    zpath = None
    try:
        zpath = _build(include_db=True)
        if os.path.getsize(zpath) > max_bytes and db_snap_path:
            os.unlink(zpath)
            zpath = None
            missing.append("garden.db: wegen Übergröße entfernt (Archiv über Versand-Limit)")
            zpath = _build(include_db=False)
        return Path(zpath).read_bytes(), missing
    except Exception as e:
        logger.error(f"Diagnose-Paket konnte nicht gepackt werden: {e}")
        missing.append(f"Archiv: {e}")
        return None, missing
    finally:
        for tmp in (zpath, db_snap_path):
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
