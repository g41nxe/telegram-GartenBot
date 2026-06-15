#pragma once

// WLAN-Zugangsdaten
#define WIFI_SSID "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"

// Feste IP-Adresse der Kamera
#define CAMERA_IP "192.168.1.50"
#define CAMERA_GATEWAY "192.168.1.1"
#define CAMERA_SUBNET "255.255.255.0"
#define CAMERA_DNS "192.168.1.1"

// IP-Adresse des Raspberry Pi (Daemon)
#define PI_IP "192.168.1.100"
#define PI_PORT 8080

// Standard-Intervall (wird überschrieben, wenn der Server etwas anderes sendet)
#define DEFAULT_SLEEP_SECONDS 900
