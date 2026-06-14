# 🌦 Forschungsbericht: M5Stack Wetterstation für den GartenBot

Dieses Dokument dokumentiert die technische Machbarkeit, Hardware-Optionen, Stromversorgungs-Konzepte und Integrationswege für den Aufbau einer autarken, M5Stack-basierten Wetterstation zur Erfassung von Echtzeit-Umweltdaten (Temperatur, Bodenfeuchtigkeit, Regenmenge) im Beet.

---

## 1. Physikalische Randbedingungen des Gartens

*   **Zentrale Infrastruktur:** Die Steuerzentrale (Raspberry Pi Zero W) befindet sich geschützt in der Hütte und betreibt einen Mosquitto MQTT-Broker sowie den Mittelweg-Dienst (Zigbee2MQTT).
*   **Sensorplatzierung:** Die Sensoren müssen direkt in den Beeten/im Außenbereich platziert werden.
*   **Verbindungsweg:** Aufgrund der Entfernung zu den Beeten scheidet eine Kabelverbindung aus. Die Datenübertragung muss drahtlos erfolgen. Da für den Füllstandssensor bereits WLAN-Abdeckung im Garten etabliert wurde, ist der Einsatz einer WiFi-basierten Wetterstation optimal.

---

## 2. Hardware-Architektur (M5Stack-Komponenten & Alternativen)

Das System basiert auf dem modularen M5Stack-Ökosystem (Grove-Steckverbindungen), ergänzt um langlebige Outdoor-Sensoren.

```
                  +-----------------------------------------+
                  |           Wetterfeste Box               |
                  |                                         |
                  |   +------------------+                  |
                  |   |  AtomS3 Lite     |                  |
                  |   |  (ESP32-S3)      |                  |
                  |   +--------+---------+                  |
                  |            | (I2C / GPIO / ADC)         |
                  +------------+----------------------------+
                               |
       +-----------------------+-----------------------+
       | (Grove I2C)           | (Grove Analog)        | (Grove Digital/Pulse)
+------v------+         +------v------+         +------v------+
|  ENV IV     |         | Kapazitiver |         | Regenwippe  |
|  SHT40 Temp |         | Bodenfeuchte|         | (Tipping    |
|  & Humid    |         | sensor      |         | Bucket)     |
+-------------+         +-------------+         +-------------+
```

### A. Das Steuergerät: M5Stack AtomS3 Lite (ca. 10 €)
*   **Details:** Extrem kompakter Microcontroller mit ESP32-S3-Chip, integriertem WLAN, USB-C-Anschluss und einem Grove-Port (I2C/GPIO).
*   **Port-Erweiterung:** Der AtomS3 Lite besitzt standardmäßig nur einen Grove-Port. Um mehrere Sensoren anzuschließen, gibt es zwei Wege:
    1.  **M5Stack PbHub / PaHub:** Ein I2C-basierter Hub, der einen Grove-Port in 6 steuerbare Kanäle aufteilt.
    2.  **Unterseite nutzen:** Der AtomS3 Lite führt an der Unterseite zusätzliche GPIO-Pins (G5, G6, G7, G8, G38, G39, G1, G2) heraus. Mittels eines *Atom Proto Boards* oder eines Grove-to-Pin-Kabels können dort weitere Sensoren direkt angeschlossen werden.

### B. Die Sensoren
1.  **Lufttemperatur & Luftfeuchtigkeit (M5Stack ENV IV Unit - ca. 8 €):**
    *   *Sensoren:* SHT40 (Präzise Temperatur & Feuchte) und BMP280 (Luftdruck).
    *   *Verbindung:* Wird direkt per I2C (Grove-Port) betrieben.
2.  **Bodenfeuchtigkeit (Kapazitiver Sensor - ca. 5 €):**
    *   *Hinweis zu M5Stack:* Die offizielle *M5Stack Earth/Soil Unit* arbeitet resistiv (zwei freiliegende Metallkontakte). Diese Kontakte oxidieren im feuchten Erdreich durch Elektrolyse innerhalb weniger Wochen und liefern unbrauchbare Werte.
    *   *Bessere Option:* Ein **kapazitiver Bodenfeuchtesensor v1.2** (z. B. von Mileles / DFRobot). Dieser hat keine freiliegenden Metallteile im Boden, misst die Feuchtigkeit über ein elektrisches Feld und hält jahrelang. Die Verbindung erfolgt über einen analogen Pin (ADC) des AtomS3 Lite.
3.  **Regenmenge (Niederschlags-Messung - ca. 15-20 €):**
    *   *Hardware:* Eine standardmäßige **Ersatz-Regenwippe** für Wetterstationen (z. B. von Froggit/Misol).
    *   *Funktion:* Wasser läuft durch einen Trichter in eine kleine Wippe. Bei ca. 0,3 mm gefüllter Regenmenge kippt die Wippe. Ein integrierter Magnet schließt dabei kurzzeitig einen Reed-Kontakt.
    *   *Verbindung:* Der Schalter wird an einen digitalen Pin (GPIO) des AtomS3 angeschlossen und über einen Software-Impulszähler (Pulse Counter) ausgewertet.

---

## 3. Energieversorgung (Solar & Deep Sleep)

Ein ESP32 im Dauerbetrieb benötigt ca. 80-120 mA, was eine Batterie in wenigen Tagen leeren würde. Daher nutzt die Station das **Deep-Sleep-Verfahren**:
*   Der Controller schläft für **15 Minuten** im Stromsparmodus.
*   Er wacht für ca. **5 Sekunden** auf, schaltet die Sensoren ein, verbindet sich mit dem WLAN, sendet die Daten per MQTT und schläft wieder ein.

### Energiebedarfsrechnung (für einen 18650-Akku mit 3000 mAh)
*   **Schlafstrom (AtomS3 Lite ohne Hardware-Modifikationen):** ca. 1,5 mA (bedingt durch LDO und DCDC-Regler).
    $$\text{Energie}_{\text{Schlaf}} = 1,5\text{ mA} \times 24\text{ Std} = 36\text{ mAh / Tag}$$
*   **Aktivstrom (Messung & WLAN-Übertragung):** 150 mA für 5 Sekunden alle 15 Minuten (96-mal pro Tag).
    $$\text{Aktivzeit pro Tag} = 96 \times 5\text{ Sek} = 480\text{ Sek} \approx 0,133\text{ Std}$$
    $$\text{Energie}_{\text{Aktiv}} = 150\text{ mA} \times 0,133\text{ Std} \approx 20\text{ mAh / Tag}$$
*   **Gesamtbedarf:** $\approx 56\text{ mAh / Tag}$.
*   **Laufzeit ohne Nachladen:** $3000\text{ mAh} / 56\text{ mAh} \approx \mathbf{53\text{ Tage}}$ (ca. 1,5 bis 2 Monate).

### Autarker Betrieb mit Solar
Um die Wetterstation 100% wartungsfrei zu betreiben, reicht ein winziges **5V / 1W Solarpanel** in Kombination mit dem **M5Stack Solar Charger Unit** (CN3163-Ladecontroller).
*   Das Panel liefert bei direktem Sonnenschein ca. 150–200 mA Ladestrom.
*   Um den wöchentlichen Energiebedarf von ca. $392\text{ mAh}$ ($56\text{ mAh} \times 7$) zu decken, genügen bereits **2 Stunden Sonnenschein pro Woche**! Das System läuft somit auch im trüben Winter autark.

---

## 4. Software & Protokoll (ESPHome)

Die Programmierung erfolgt am einfachsten über **ESPHome**. Nachfolgend ein vollständiges YAML-Konfigurationsbeispiel für den AtomS3 Lite:

```yaml
esphome:
  name: garten-wetterstation
  friendly_name: Garten Wetterstation

esp32:
  board: esp32-s3-devkitc-1
  framework:
    type: esp-idf

# I2C-Bus definieren (für ENV IV Unit)
i2c:
  sda: G38
  scl: G39

sensor:
  # 1. ENV IV: SHT40 Temperatur und Luftfeuchtigkeit
  - platform: sht3xd
    temperature:
      name: "Gartentemperatur"
      id: garten_temp
    humidity:
      name: "Luftfeuchtigkeit"
      id: garten_feuchte
    address: 0x44

  # 2. Bodenfeuchtigkeit (Analogwert von kapazitivem Sensor an Pin G1)
  - platform: adc
    pin: G1
    name: "Bodenfeuchtigkeit Analog"
    id: boden_analog
    attenuation: 11db
    unit_of_measurement: "%"
    # Kalibrierung: 2.8V = trocken (0%), 1.1V = im Wasser (100%)
    filters:
      - calibrate_linear:
          - 2.8 -> 0.0
          - 1.1 -> 100.0

  # 3. Regenmesser (Pulse-Counter für Wippe an Pin G2)
  - platform: pulse_counter
    pin:
      number: G2
      mode: INPUT_PULLUP
    name: "Regenmenge Ticks"
    id: regen_ticks
    update_interval: 60s

# Tiefschlaf-Steuerung (10 Sekunden aktiv zum Senden, danach 15 Min Schlaf)
deep_sleep:
  run_duration: 10s
  sleep_duration: 15min

mqtt:
  broker: 192.168.0.165
  topic_prefix: garten/wetterstation
```

---

## 5. Architektonische Integration in den Bewässerungs-Daemon

Sobald die Wetterstation Daten per MQTT sendet, werden diese vom **Bewässerungs-Daemon** empfangen und verarbeitet.

### A. Datenbank-Schema erweitern
Die SQLite-Datenbank (`garden.db`) wird um eine Tabelle für lokale Sensormessungen erweitert:

```sql
CREATE TABLE sensor_logs (
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    sensor_name TEXT,
    value REAL
);
```

### B. Anpassung der Gieß-Empfehlung (giesscheck)
Der Algorithmus zur Gieß-Empfehlung greift aktuell auf den externen Open-Meteo API-Dienst zu. Die Integration der Wetterstation optimiert die Entscheidungen:

1.  **Reale Regenmenge:** Anstatt den gemessenen Regen der letzten 24 Stunden aus der ungenauen API zu beziehen, summiert die Gieß-Empfehlung die gemessenen "Ticks" der physikalischen Regenwippe.
2.  **Bodenfeuchte-Override:**
    *   Liegt die Bodenfeuchte über einem konfigurierbaren Schwellenwert (z. B. 60 %), wird die Bewässerung ungeachtet des Zeitplans und der Wettervorhersage **übersprungen**.
    *   Liegt die Bodenfeuchte extrem niedrig (z. B. < 20 %), kann die Gießdauer automatisch verlängert werden.
3.  **Frost-Schutz:** Sinkt die gemessene Gartentemperatur unter 2°C, werden Ventile und Leitungen gesperrt, um Frostschäden vorzubeugen.
