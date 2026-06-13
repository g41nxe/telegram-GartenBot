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
                details TEXT,                    -- Grund für Skip oder Fehlerbeschreibung
                watered_volume REAL DEFAULT 0.0  -- Tatsächliche Wassermenge in Litern
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
                weather_code INTEGER DEFAULT 0,
                temp_min REAL DEFAULT 0.0,
                temp_max REAL DEFAULT 0.0,
                rain_probability INTEGER DEFAULT 0
            )
        """)

        # Tabelle für System-Metadaten (Schlüssel-Wert-Paare)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # Tabelle für Verbindungsstatistiken (Passives Status-Logging)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS device_status_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                battery INTEGER,
                linkquality INTEGER
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
            cursor.execute("SELECT temp_min FROM weather_history LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migriere Datenbank: Füge temp_min, temp_max, rain_probability Spalten zu weather_history hinzu...")
            cursor.execute("ALTER TABLE weather_history ADD COLUMN temp_min REAL DEFAULT 0.0")
            cursor.execute("ALTER TABLE weather_history ADD COLUMN temp_max REAL DEFAULT 0.0")
            cursor.execute("ALTER TABLE weather_history ADD COLUMN rain_probability INTEGER DEFAULT 0")
            
        try:
            cursor.execute("SELECT target_volume_liters FROM schedules LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migriere Datenbank: Füge target_volume_liters Spalte zu schedules hinzu...")
            cursor.execute("ALTER TABLE schedules ADD COLUMN target_volume_liters INTEGER DEFAULT 0")

        try:
            cursor.execute("SELECT watered_volume FROM watering_history LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migriere Datenbank: Füge watered_volume Spalte zu watering_history hinzu...")
            cursor.execute("ALTER TABLE watering_history ADD COLUMN watered_volume REAL DEFAULT 0.0")
            
        try:
            cursor.execute("SELECT id FROM device_status_log LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migriere Datenbank: Erstelle Tabelle device_status_log...")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS device_status_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    battery INTEGER,
                    linkquality INTEGER
                )
            """)

        # --- Multi-Ventil-Schema (Feature 0006) ---

        # Neue Tabellen anlegen
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS valves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wish_name TEXT NOT NULL,
                mqtt_name TEXT NOT NULL UNIQUE,
                is_paired INTEGER DEFAULT 1,
                battery INTEGER DEFAULT 100,
                linkquality INTEGER DEFAULT 0,
                last_update TEXT,
                valve_abnormal_state TEXT DEFAULT 'normal'
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schedule_valves (
                schedule_id INTEGER NOT NULL,
                valve_id INTEGER NOT NULL,
                PRIMARY KEY (schedule_id, valve_id)
            )
        """)

        # Spalten-Migrationen für bestehende Tabellen
        try:
            cursor.execute("SELECT execution_mode FROM schedules LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migriere Datenbank: Füge execution_mode Spalte zu schedules hinzu...")
            cursor.execute("ALTER TABLE schedules ADD COLUMN execution_mode TEXT DEFAULT 'sequential'")

        try:
            cursor.execute("SELECT valve_id FROM watering_history LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migriere Datenbank: Füge valve_id Spalte zu watering_history hinzu...")
            cursor.execute("ALTER TABLE watering_history ADD COLUMN valve_id INTEGER")

        try:
            cursor.execute("SELECT device_name FROM device_status_log LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migriere Datenbank: Füge device_name Spalte zu device_status_log hinzu...")
            cursor.execute("ALTER TABLE device_status_log ADD COLUMN device_name TEXT")

        try:
            cursor.execute("SELECT current_precipitation_mm FROM weather_history LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migriere Datenbank: Füge current_precipitation_mm und hourly_forecast_json zu weather_history hinzu...")
            cursor.execute("ALTER TABLE weather_history ADD COLUMN current_precipitation_mm REAL DEFAULT 0.0")
            cursor.execute("ALTER TABLE weather_history ADD COLUMN hourly_forecast_json TEXT")

        # Daten-Migrationen: Standard-Ventil anlegen und Altdaten verknüpfen
        cursor.execute("SELECT COUNT(*) FROM valves")
        if cursor.fetchone()[0] == 0:
            logger.info("Migriere Datenbank: Lege Standard-Ventil an (garden_valve)...")
            cursor.execute(
                "INSERT INTO valves (wish_name, mqtt_name, is_paired) VALUES (?, ?, ?)",
                ("Ventil", "garden_valve", 1)
            )

        # Bestehende Zeitpläne ohne schedule_valves-Eintrag mit valve_id=1 verknüpfen
        cursor.execute("""
            INSERT OR IGNORE INTO schedule_valves (schedule_id, valve_id)
            SELECT id, 1 FROM schedules
            WHERE id NOT IN (SELECT schedule_id FROM schedule_valves)
        """)

        # Bestehende device_status_log-Einträge ohne device_name auf "garden_valve" setzen
        cursor.execute(
            "UPDATE device_status_log SET device_name = 'garden_valve' WHERE device_name IS NULL"
        )

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

def log_watering(duration_minutes: int, source: str, status: str, details: str = None, watered_volume: float = 0.0):
    """Protokolliert ein Bewässerungsereignis (egal ob erfolgreich oder übersprungen)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO watering_history (timestamp, duration_minutes, source, status, details, watered_volume) VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, duration_minutes, source, status, details, watered_volume)
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

def log_weather(rain_last_24h: float, rain_next_24h: float, current_temp: float = 0.0, weather_code: int = 0,
                temp_min: float = 0.0, temp_max: float = 0.0, rain_probability: int = 0,
                current_precipitation_mm: float = 0.0, hourly_forecast_json: str = ""):
    """Speichert den abgerufenen Wetterstatus."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO weather_history (timestamp, rain_last_24h_mm, rain_next_24h_mm, current_temp, weather_code, temp_min, temp_max, rain_probability, current_precipitation_mm, hourly_forecast_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (timestamp, rain_last_24h, rain_next_24h, current_temp, weather_code, temp_min, temp_max, rain_probability, current_precipitation_mm, hourly_forecast_json or None)
        )
        conn.commit()
        logger.info("Stundendaten erfolgreich in weather_history gespeichert (24 Einträge).")
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

# --- Operationen für System-Metadaten ---

def get_metadata(key: str, default: str = None) -> str:
    """Gibt den Metadatenwert für einen bestimmten Schlüssel zurück."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM system_metadata WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Metadaten für {key}: {e}")
        return default
    finally:
        conn.close()

def set_metadata(key: str, value: str):
    """Speichert oder aktualisiert einen Metadatenwert für einen bestimmten Schlüssel."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO system_metadata (key, value) VALUES (?, ?)",
            (key, value)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Fehler beim Speichern der Metadaten für {key}: {e}")
    finally:
        conn.close()

def get_watering_stats_last_24h() -> tuple[int, int, float]:
    """
    Gibt (erfolgreiche_zyklen, fehlgeschlagene_zyklen, gesamt_liter) für die letzten 24 Stunden zurück.
    Erfolgreiche Zyklen schließt auch vorzeitig gestoppte ein.
    Start-Einträge ('Bewässerung gestartet...') werden ignoriert.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        # ISO-Zeitstempel vor 24h berechnen
        from datetime import timedelta
        time_limit = (datetime.now() - timedelta(hours=24)).isoformat()
        
        # 1. Erfolgreiche / gestoppte Läufe
        cursor.execute("""
            SELECT COUNT(*), SUM(watered_volume) 
            FROM watering_history 
            WHERE timestamp >= ? 
              AND status IN ('completed', 'stopped')
              AND details NOT LIKE 'Bewässerung gestartet%'
        """, (time_limit,))
        row = cursor.fetchone()
        success_count = row[0] or 0
        volume = row[1] or 0.0
        
        # 2. Fehlgeschlagene Läufe
        cursor.execute("""
            SELECT COUNT(*) 
            FROM watering_history 
            WHERE timestamp >= ? 
              AND status = 'failed'
        """, (time_limit,))
        failed_count = cursor.fetchone()[0] or 0
        
        return success_count, failed_count, round(volume, 2)
    except Exception as e:
        logger.error(f"Fehler beim Laden der Bewässerungsstatistik: {e}")
        return 0, 0, 0.0
    finally:
        conn.close()

def log_device_status(device_name: str, battery: int, linkquality: int):
    """Loggt den aktuellen Batteriestand und die Signalqualität für statistische Auswertungen."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO device_status_log (timestamp, device_name, battery, linkquality) VALUES (?, ?, ?, ?)",
            (timestamp, device_name, battery, linkquality)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Fehler beim Protokollieren des Gerätestatus: {e}")
    finally:
        conn.close()

def get_device_status_stats_last_24h(device_name: str) -> dict:
    """Errechnet Signalstärkestatistiken der letzten 24 Stunden für ein bestimmtes Gerät."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        from datetime import datetime, timedelta
        time_limit = (datetime.now() - timedelta(hours=24)).isoformat()

        cursor.execute("""
            SELECT timestamp, linkquality
            FROM device_status_log
            WHERE timestamp >= ?
              AND device_name = ?
            ORDER BY timestamp ASC
        """, (time_limit, device_name))
        rows = cursor.fetchall()
        
        if not rows:
            return {
                "count": 0,
                "avg_lqi": 0.0,
                "max_gap_hours": 0.0
            }
            
        count = len(rows)
        lqis = [r["linkquality"] for r in rows]
        avg_lqi = sum(lqis) / count
        
        # Berechne maximale Funklücke
        max_gap_seconds = 0.0
        prev_time = datetime.fromisoformat(rows[0]["timestamp"])
        
        # Vergleiche mit dem Startzeitpunkt (vor 24h)
        start_time = datetime.now() - timedelta(hours=24)
        gap_start = (prev_time - start_time).total_seconds()
        if gap_start > max_gap_seconds:
            max_gap_seconds = gap_start
            
        for r in rows[1:]:
            curr_time = datetime.fromisoformat(r["timestamp"])
            gap = (curr_time - prev_time).total_seconds()
            if gap > max_gap_seconds:
                max_gap_seconds = gap
            prev_time = curr_time
            
        # Vergleiche mit dem jetzigen Zeitpunkt
        gap_end = (datetime.now() - prev_time).total_seconds()
        if gap_end > max_gap_seconds:
            max_gap_seconds = gap_end
            
        max_gap_hours = max_gap_seconds / 3600.0
        
        return {
            "count": count,
            "avg_lqi": round(avg_lqi, 1),
            "max_gap_hours": round(max_gap_hours, 1)
        }
    except Exception as e:
        logger.error(f"Fehler beim Berechnen der Gerätestatus-Statistik: {e}")
        return {
            "count": 0,
            "avg_lqi": 0.0,
            "max_gap_hours": 0.0
        }
    finally:
        conn.close()

# --- CRUD Operationen für Ventile (valves) ---

def get_all_valves() -> list:
    """Gibt alle registrierten Ventile zurück."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM valves ORDER BY id ASC")
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Fehler beim Laden der Ventile: {e}")
        return []
    finally:
        conn.close()

def get_valve_by_id(valve_id: int) -> dict | None:
    """Gibt ein Ventil anhand seiner ID zurück."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM valves WHERE id = ?", (valve_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Fehler beim Laden des Ventils (id={valve_id}): {e}")
        return None
    finally:
        conn.close()

def get_valve_by_mqtt_name(mqtt_name: str) -> dict | None:
    """Gibt ein Ventil anhand seines MQTT-Namens zurück."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM valves WHERE mqtt_name = ?", (mqtt_name,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Fehler beim Laden des Ventils (mqtt_name={mqtt_name}): {e}")
        return None
    finally:
        conn.close()

def add_valve(wish_name: str, mqtt_name: str) -> int:
    """Fügt ein neues Ventil hinzu und gibt dessen ID zurück. Gibt -1 bei Fehler zurück."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO valves (wish_name, mqtt_name, is_paired) VALUES (?, ?, ?)",
            (wish_name, mqtt_name, 1)
        )
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        logger.warning(f"Ventil mit mqtt_name='{mqtt_name}' existiert bereits.")
        return -1
    except Exception as e:
        logger.error(f"Fehler beim Hinzufügen des Ventils '{mqtt_name}': {e}")
        return -1
    finally:
        conn.close()

def update_valve_status(mqtt_name: str, battery: int, linkquality: int, last_update: str, valve_abnormal_state: str):
    """Aktualisiert den Live-Status eines Ventils in der Datenbank."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE valves
               SET battery = ?, linkquality = ?, last_update = ?, valve_abnormal_state = ?
               WHERE mqtt_name = ?""",
            (battery, linkquality, last_update, valve_abnormal_state, mqtt_name)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Fehler beim Aktualisieren des Ventilstatus für '{mqtt_name}': {e}")
    finally:
        conn.close()

# --- CRUD Operationen für schedule_valves ---

def get_schedule_valves(schedule_id: int) -> list:
    """Gibt alle valve_ids zurück, die einem Zeitplan zugeordnet sind."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT valve_id FROM schedule_valves WHERE schedule_id = ?", (schedule_id,))
        return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Fehler beim Laden der Ventile für Zeitplan {schedule_id}: {e}")
        return []
    finally:
        conn.close()

def set_schedule_valves(schedule_id: int, valve_ids: list):
    """Setzt die Ventil-Zuordnung für einen Zeitplan (ersetzt bestehende Einträge)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM schedule_valves WHERE schedule_id = ?", (schedule_id,))
        for valve_id in valve_ids:
            cursor.execute(
                "INSERT INTO schedule_valves (schedule_id, valve_id) VALUES (?, ?)",
                (schedule_id, valve_id)
            )
        conn.commit()
    except Exception as e:
        logger.error(f"Fehler beim Setzen der Ventile für Zeitplan {schedule_id}: {e}")
    finally:
        conn.close()
