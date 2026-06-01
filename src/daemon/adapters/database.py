import sqlite3
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("garden_database")

# Pfad zur SQLite-Datenbankdatei (im Projekt-Root)
DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "garden.db"

def get_connection():
    """Erstellt eine Verbindung zur SQLite-Datenbank."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Zugriff über Spaltennamen ermöglichen
    return conn

def init_db():
    """Initialisiert die Datenbanktabellen, falls sie noch nicht existieren."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Tabelle für Zeitpläne (Zeit- und Literlimit)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                time TEXT NOT NULL,              -- Format: "HH:MM" (z.B. "08:00")
                days TEXT NOT NULL,              -- Kommagetrennt (z.B. "Mon,Wed,Fri" oder "everyday")
                duration_minutes INTEGER NOT NULL, -- Gießdauer (Zeitlimit)
                target_volume_liters INTEGER DEFAULT 0, -- Gießmenge (Volumenlimit)
                is_active INTEGER DEFAULT 1      -- 1 = Aktiv, 0 = Inaktiv
            )
        """)
        
        # Tabelle für Bewässerungsprotokolle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS watering_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,         -- ISO-Zeitstempel (z.B. "2026-05-31T12:00:00")
                duration_minutes INTEGER NOT NULL,
                source TEXT NOT NULL,            -- "schedule" (Zeitplan) oder "manual" (Manuell)
                status TEXT NOT NULL,            -- "completed" (Erfolgreich), "skipped" (Übersprungen), "failed" (Fehlgeschlagen)
                details TEXT                     -- Grund für Skip oder Fehlerbeschreibung
            )
        """)
        
        # Tabelle für Wetterhistorie
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS weather_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                rain_last_24h_mm REAL NOT NULL,
                rain_next_24h_mm REAL NOT NULL,
                current_temp REAL DEFAULT 0.0,
                weather_code INTEGER DEFAULT 0
            )
        """)
        
        # Schema-Migration check (falls Spalten in einer bestehenden Datenbank fehlen)
        try:
            cursor.execute("SELECT current_temp FROM weather_history LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migriere Datenbank: Füge Wetter-Spalten zu weather_history hinzu...")
            cursor.execute("ALTER TABLE weather_history ADD COLUMN current_temp REAL DEFAULT 0.0")
            cursor.execute("ALTER TABLE weather_history ADD COLUMN weather_code INTEGER DEFAULT 0")
            
        try:
            cursor.execute("SELECT target_volume_liters FROM schedules LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migriere Datenbank: Füge target_volume_liters Spalte zu schedules hinzu...")
            cursor.execute("ALTER TABLE schedules ADD COLUMN target_volume_liters INTEGER DEFAULT 0")
            
        conn.commit()
        logger.info("Datenbank erfolgreich initialisiert.")
    except Exception as e:
        logger.error(f"Fehler bei der Datenbank-Initialisierung: {e}")
    finally:
        conn.close()

# --- CRUD Operationen für Zeitpläne ---

def get_schedules():
    """Gibt alle Zeitpläne aus der Datenbank zurück."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM schedules")
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Fehler beim Laden der Zeitpläne: {e}")
        return []
    finally:
        conn.close()

def add_schedule(name: str, time: str, days: str, duration_minutes: int, target_volume_liters: int = 0, is_active: int = 1) -> int:
    """Fügt einen neuen Zeitplan hinzu und gibt dessen ID zurück."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO schedules (name, time, days, duration_minutes, target_volume_liters, is_active) VALUES (?, ?, ?, ?, ?, ?)",
            (name, time, days, duration_minutes, target_volume_liters, is_active)
        )
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        logger.error(f"Fehler beim Hinzufügen des Zeitplans: {e}")
        return -1
    finally:
        conn.close()

def update_schedule(schedule_id: int, name: str, time: str, days: str, duration_minutes: int, target_volume_liters: int, is_active: int) -> bool:
    """Aktualisiert einen bestehenden Zeitplan."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE schedules SET name = ?, time = ?, days = ?, duration_minutes = ?, target_volume_liters = ?, is_active = ? WHERE id = ?",
            (name, time, days, duration_minutes, target_volume_liters, is_active, schedule_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Fehler beim Aktualisieren des Zeitplans: {e}")
        return False
    finally:
        conn.close()

def delete_schedule(schedule_id: int) -> bool:
    """Löscht einen Zeitplan."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Fehler beim Löschen des Zeitplans: {e}")
        return False
    finally:
        conn.close()

# --- Operationen für Bewässerungshistorie ---

def log_watering(duration_minutes: int, source: str, status: str, details: str = None):
    """Protokolliert ein Bewässerungsereignis (egal ob erfolgreich oder übersprungen)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO watering_history (timestamp, duration_minutes, source, status, details) VALUES (?, ?, ?, ?, ?)",
            (timestamp, duration_minutes, source, status, details)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Fehler beim Protokollieren des Bewässerungsereignisses: {e}")
    finally:
        conn.close()

def get_recent_history(limit: int = 5):
    """Gibt die neuesten Bewässerungsprotokolle zurück."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM watering_history ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Fehler beim Laden des Bewässerungsprotokolls: {e}")
        return []
    finally:
        conn.close()

# --- Operationen für Wetterhistorie ---

def log_weather(rain_last_24h: float, rain_next_24h: float, current_temp: float = 0.0, weather_code: int = 0):
    """Speichert den abgerufenen Wetterstatus."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO weather_history (timestamp, rain_last_24h_mm, rain_next_24h_mm, current_temp, weather_code) VALUES (?, ?, ?, ?, ?)",
            (timestamp, rain_last_24h, rain_next_24h, current_temp, weather_code)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Fehler beim Protokollieren der Wetterdaten: {e}")
    finally:
        conn.close()

def get_last_weather():
    """Gibt den neuesten gespeicherten Wetterstatus zurück."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM weather_history ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Fehler beim Laden des neuesten Wetters: {e}")
        return None
    finally:
        conn.close()
