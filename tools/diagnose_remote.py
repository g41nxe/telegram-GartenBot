#!/usr/bin/env python3
import sqlite3
import os
import sys

DB_PATH = "/home/g41nxe/garden/garden.db"

def check_database():
    print("=== Datenbank-Check ===")
    if not os.path.exists(DB_PATH):
        print(f"Fehler: Datenbank unter {DB_PATH} existiert nicht.")
        return
        
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Tabellen und Zeilenzahl ausgeben
        tables = ["watering_history", "weather_history", "device_status_log", "system_metadata"]
        for t in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {t}")
                count = cursor.fetchone()[0]
                print(f"  - Tabelle '{t}': {count} Einträge")
            except sqlite3.OperationalError:
                print(f"  - Tabelle '{t}': Fehlt oder beschädigt")
                
        # Letzte 5 LQI / Batteriemeldungen ausgeben
        print("\nLetzte 5 Ventil-Statusmeldungen (device_status_log):")
        try:
            cursor.execute("SELECT timestamp, battery, linkquality FROM device_status_log ORDER BY id DESC LIMIT 5")
            rows = cursor.fetchall()
            for r in rows:
                print(f"    - Zeit: {r['timestamp']}, Batterie: {r['battery']}%, LQI: {r['linkquality']}")
        except Exception as e:
            print(f"    Fehler beim Auslesen: {e}")
            
        conn.close()
    except Exception as e:
        print(f"Allgemeiner Datenbankfehler: {e}")

def listen_mqtt():
    print("\n=== MQTT Live-Diagnose (Warte max. 5s auf Nachricht...) ===")
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        print("Fehler: 'paho-mqtt' ist auf diesem System nicht installiert.")
        return
        
    import json
    import time
    
    received = []
    
    def on_connect(client, userdata, flags, rc):
        client.subscribe("zigbee2mqtt/garden_valve")
        # Trigger get command
        client.publish("zigbee2mqtt/garden_valve/get", json.dumps({"state": "", "battery": ""}))
        
    def on_message(client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8")
            received.append(payload)
            print("  [Empfangen]:", payload)
        except Exception as e:
            print("  Fehler beim Decodieren:", e)
            
    client = mqtt.Client()
    # Handle both V1 and newer callback APIs safely
    try:
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
    except AttributeError:
        client = mqtt.Client()
        
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        client.connect("127.0.0.1", 1883)
        client.loop_start()
        time.sleep(5)
        client.disconnect()
    except Exception as e:
        print("Verbindungsfehler zum MQTT-Broker:", e)
        
    if not received:
        print("  Keine Nachricht empfangen (Timeout).")

if __name__ == "__main__":
    check_database()
    listen_mqtt()
