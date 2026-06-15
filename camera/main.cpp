#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include "battery.h"
#include "bmm8563.h"
#include "camera.h"
#include <ArduinoJson.h>
#include "config.h"

// Exponential backoff state im RTC-RAM (überlebt den Deep Sleep)
RTC_DATA_ATTR int failCount = 0;

void goToSleep(int seconds) {
    Serial.printf("Gehe für %d Sekunden in den Tiefschlaf...\n", seconds);
    Serial.flush();
    
    // M5Stack Timer Camera F: Schaltet das System komplett ab und wacht über den RTC-Timer wieder auf
    bat_disable_output(seconds); 
    
    // Fallback, falls bat_disable_output() fehlschlagen sollte
    esp_sleep_enable_timer_wakeup(seconds * 1000000ULL);
    esp_deep_sleep_start();
}

void setup() {
    Serial.begin(115200);
    bat_init();
    bmm8563_init();
    
    // Kameramodul initialisieren
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_d0 = 32;
    config.pin_d1 = 35;
    config.pin_d2 = 34;
    config.pin_d3 = 5;
    config.pin_d4 = 39;
    config.pin_d5 = 18;
    config.pin_d6 = 36;
    config.pin_d7 = 19;
    config.pin_xclk = 27;
    config.pin_pclk = 21;
    config.pin_vsync = 22;
    config.pin_href = 26;
    config.pin_sscb_sda = 25;
    config.pin_sscb_scl = 23;
    config.pin_pwdn = -1;
    config.pin_reset = 15;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;
    config.frame_size = FRAMESIZE_XGA; // Default Auflösung
    config.jpeg_quality = 10;
    config.fb_count = 2;

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("Kamera-Init fehlgeschlagen! Fehler: 0x%x\n", err);
        goToSleep(DEFAULT_SLEEP_SECONDS);
    }
    
    // Feste IP konfigurieren
    IPAddress ip, gateway, subnet, dns;
    ip.fromString(CAMERA_IP);
    gateway.fromString(CAMERA_GATEWAY);
    subnet.fromString(CAMERA_SUBNET);
    dns.fromString(CAMERA_DNS);
    
    WiFi.config(ip, gateway, subnet, dns);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    
    Serial.print("Verbinde mit WiFi");
    int retries = 0;
    while (WiFi.status() != WL_CONNECTED && retries < 20) {
        delay(500);
        Serial.print(".");
        retries++;
    }
    Serial.println();
    
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("WiFi-Verbindung fehlgeschlagen!");
        failCount++;
        int backoff_interval = min(60 * (1 << failCount), (int)DEFAULT_SLEEP_SECONDS);
        goToSleep(backoff_interval);
    }

    String macAddr = WiFi.macAddress();
    Serial.printf("Mit WiFi verbunden! MAC: %s\n", macAddr.c_str());

    HTTPClient http;
    String baseUrl = String("http://") + PI_IP + ":" + PI_PORT;
    int sleep_interval = DEFAULT_SLEEP_SECONDS;
    
    // 1. Registrierung versuchen (Idempotent)
    // Wird bei jedem Aufwachen aufgerufen - bei bereits registrierter MAC gibt der Server 200 OK zurück.
    http.begin(baseUrl + "/register");
    http.addHeader("Content-Type", "application/json");
    
    StaticJsonDocument<128> regDoc;
    regDoc["mac"] = macAddr;
    String regPayload;
    serializeJson(regDoc, regPayload);
    
    int httpResponseCode = http.POST(regPayload);
    http.end();
    
    if (httpResponseCode == 200) {
        Serial.println("Kamera ist beim Server registriert.");
    } else if (httpResponseCode == 403) {
        Serial.println("Kamera ist nicht gekoppelt und Koppelmodus ist inaktiv.");
        // Hier weiterzumachen hat wenig Sinn, da Upload/Config ebenfalls abgelehnt werden.
        // Wir gehen in den Schlafmodus (Backoff anwenden).
        failCount++;
        sleep_interval = min(60 * (1 << failCount), (int)DEFAULT_SLEEP_SECONDS);
        goToSleep(sleep_interval);
    } else {
        Serial.printf("Registrierung fehlgeschlagen, HTTP Code: %d\n", httpResponseCode);
    }
    
    // 2. Konfiguration abrufen
    http.begin(baseUrl + "/config");
    http.addHeader("X-Camera-MAC", macAddr);
    httpResponseCode = http.GET();
    
    if (httpResponseCode == 200) {
        String payload = http.getString();
        StaticJsonDocument<256> confDoc;
        DeserializationError error = deserializeJson(confDoc, payload);
        if (!error) {
            sleep_interval = confDoc["sleep_duration_seconds"] | DEFAULT_SLEEP_SECONDS;
            int quality = confDoc["quality"] | 10;
            
            // Wende Settings an, falls unterstützt
            sensor_t * s = esp_camera_sensor_get();
            if (s) {
                s->set_quality(s, quality);
            }
            Serial.printf("Config geladen: Sleep=%ds, Quality=%d\n", sleep_interval, quality);
        }
    }
    http.end();
    
    // 3. Foto aufnehmen
    camera_fb_t * fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("Foto aufnehmen fehlgeschlagen!");
        failCount++;
        int backoff_interval = min(60 * (1 << failCount), sleep_interval);
        goToSleep(backoff_interval);
    }
    
    // 4. Foto hochladen
    http.begin(baseUrl + "/upload");
    http.addHeader("X-Camera-MAC", macAddr);
    http.addHeader("Content-Type", "image/jpeg");
    
    httpResponseCode = http.POST(fb->buf, fb->len);
    esp_camera_fb_return(fb);
    http.end();
    
    if (httpResponseCode == 200) {
        Serial.println("Bild erfolgreich hochgeladen!");
        failCount = 0; // Zähler nach Erfolg zurücksetzen
    } else {
        Serial.printf("Bild-Upload fehlgeschlagen, HTTP Code: %d\n", httpResponseCode);
        failCount++;
        sleep_interval = min(60 * (1 << failCount), sleep_interval);
    }
    
    goToSleep(sleep_interval);
}

void loop() {
    // Wird nie erreicht, da am Ende von setup() in den Deep Sleep gewechselt wird.
}
