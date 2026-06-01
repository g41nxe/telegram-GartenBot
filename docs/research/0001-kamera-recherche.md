# 📷 Forschungsbericht: Kameras für den GartenBot

Dieses Dokument dokumentiert die technische Machbarkeit, Hardware-Optionen, Batterielaufzeit-Berechnungen und Integrationswege für eine Kamera-Erweiterung am **Raspberry Pi Zero W** (Steuerzentrale).

---

## 1. Physikalische Randbedingungen des Gartens

*   **Der Pi Zero W** befindet sich fest verbaut in der Gartenhütte und hat dort eine permanente Stromversorgung (230V Steckdose).
*   **Die Beete** befinden sich im Außenbereich ohne Kabel und Strom.
*   **Verkabelungshürden:** CSI-Flachbandkabel sind auf max. 1–2 Meter limitiert (Signaldegradation). Lange USB-Kabel (bis 10m) sind möglich, erfordern aber mechanischen Schutz (Wellrohr) unter der Rasenfläche.
*   **Die Konsequenz:** Kameras im Beet müssen **kabellos (WLAN) und batteriebetrieben** sein. Kameras an der Hütte können **kabelgebunden** betrieben werden.

---

## 2. Hardware-Vergleich

### A. Lokale Kameramodule (Direkt am Pi)
*   **CSI-Module (z. B. Pi Camera Module v2 / v3):**
    *   *Details:* Direktanschluss per Flachbandkabel am Pi Zero W (erfordert spezifisches, schmaleres Pi Zero Kabel).
    *   *Vorteile:* Extrem stromsparend, hervorragende Bildqualität, Kamera Module v3 bietet echten Autofokus und HDR.
    *   *Nachteil:* Kamera muss sich im Umkreis von max. 1,5 Metern um den Pi (in der Hütte) befinden.
*   **USB-Webcams (z. B. Logitech C270 / C310):**
    *   *Vorteile:* Einfache Montage per Stativgewinde, USB-Kabel bis 3m.
    *   *Nachteil:* Belegt den einzigen Micro-USB-Datenport des Pi Zero W (erfordert ggf. USB-Hub) und verbraucht mehr Strom als CSI-Module.

### B. Kabellose Satelliten-Kamera (DIY ESP32-CAM)
*   **Das Konzept:** Ein winziges ESP32-CAM Board (ca. 6 €) mit OV2640 Kameramodul (2 Megapixel) und integriertem WLAN.
*   **Spannungsversorgung:** 3x AA Lithium-Batterien (z. B. Energizer Ultimate Lithium) oder 18650 Li-Ion Akku, gekoppelt an einen **HT7333-A** LDO-Spannungsregler (3.3V) und einen Puffer-Kondensator (100µF).
*   **Vorteile:**
    *   **Kein Hub erforderlich:** Der Pi Zero W in der Hütte fungiert selbst als Empfänger (HTTP-POST-Server).
    *   **100 % offline-first & lokal:** Keine Cloud, kein Internet nötig.
    *   **Extrem günstig:** Gesamtkosten ca. 20–25 €.

### C. Kommerzielle Fertiggeräte

#### 1. Reolink (z. B. Argus MagiCam)
*   **Vorteile:** IP67 wetterfest, Magnethalterung, läuft bis zu 9 Monate mit AA-Lithium-Batterien. Professionelle Optik.
*   **Der Haken:** Standalone-Akku-Kameras unterstützen **kein ONVIF, RTSP oder lokale HTTP-APIs**, da sie zum Batterieschutz tief schlafen. Sie sind standardmäßig in der Reolink-App/Cloud gesperrt.
*   **Die Integrationswege ohne Cloud:**
    *   *Weg A (Mit Hub):* Reolink Home Hub (ca. 70 €) in der Hütte. Dieser fungiert als lokaler Proxy und stellt ONVIF/RTSP/Snapshots lokal bereit.
    *   *Weg B (Neolink Proxy):* Das Open-Source-Tool **Neolink** (in Rust) fungiert auf dem Pi als Software-Hub und weckt die Kamera per P2P auf. **Achtung (ARMv6-Flaschenhals):** Der Pi Zero W nutzt die ältere ARMv6-Architektur. Offizielle Neolink-Binaries (ARMv7) stürzen mit `Illegal Instruction` ab. Neolink müsste extrem aufwendig auf dem Pi Zero selbst kompiliert werden, was auf 512MB RAM instabil ist.

#### 2. TP-Link Tapo (z. B. Tapo C410)
*   **Details:** Integrierter 6400-mAh-Akku, direktes WLAN (kein Hub nötig).
*   **Der Haken:** TP-Link hat **RTSP/ONVIF bei allen Akku-Modellen komplett deaktiviert** (es gibt kein lokales Kamera-Konto in der App). Die Kamera lässt sich **ausschließlich** über die offizielle Tapo Cloud/App steuern. Sie ist für ein lokales Offline-System unbrauchbar.

#### 3. Wyze (z. B. Battery Cam Pro)
*   **Details:** Wechselbarer Akku, hohe Auflösung.
*   **Der Haken:** Über das Tool `docker-wyze-bridge` lässt sich unkompliziert ein lokaler RTSP-Stream auf dem Pi erzeugen, aber **dieses Tool benötigt zwingend eine aktive Internetverbindung zur Wyze-Cloud** zur Token-Aushandlung.

---

## 3. Energiebedarfsberechnung (Batteriebetrieb für 1 Jahr)

Um 1 Jahr (365 Tage) Laufzeit ohne Solarpanel im Beet bei **2 Foto-Abrufen pro Tag** zu garantieren:

### A. Das reine Intervall-Foto (Kamera wacht von allein auf)
*   **Tiefschlaf-Strom:** 0,1 mA (mit LDO-Spannungsregler HT7333-A).
    $$\text{Energie}_{\text{Schlaf}} = 0,1\text{ mA} \times 8760\text{ Std/Jahr} = \mathbf{876\text{ mAh}}$$
*   **Aktiv-Strom (Bild machen & senden):** 150 mA über 8 Sekunden (inkl. WLAN-Verbindung und HTTP-POST-Übertragung zum Pi).
    $$\text{Energie}_{\text{Aktiv}} = 150\text{ mA} \times \left(\frac{730 \times 8\text{ Sek}}{3600}\right) \approx \mathbf{243\text{ mAh}}$$
*   **Gesamtbedarf:** **1.119 mAh** pro Jahr.
*   *Reichweite:* Eine 3000-mAh-Batterie (3x AA Lithium) hält problemlos **over 2 Jahre**!

### B. Das Polling-Modell (Für On-Demand-Fotos)
Da schlafende WLAN-Chips keine Signale empfangen können, wacht die Kamera in Intervallen kurz auf (2 Sek. mit statischer IP) und fragt den Pi: *„Soll ich ein Foto machen?“*.

Mit einer **3000-mAh-Batterie** (Nutzbar für Polling nach Abzug von Schlaf- und Fotoenergie: 1881 mAh):
*   Jeder 2-sekündige Check verbraucht **0,083 mAh**.
*   Das reicht für **22.572 Checks pro Jahr** (ca. 62 Checks pro Tag).
*   **Maximales Weck-Intervall:** **alle 23 Minuten** für eine Batterielaufzeit von exakt 1 Jahr!

Mit **zwei 18650-Akkus parallel (6000 mAh)**:
*   **Maximales Weck-Intervall:** **alle 9 Minuten** für eine Batterielaufzeit von 1 Jahr!

---

## 4. Empfohlene DIY-Bastelanleitungen & Software

Falls die Wahl auf die kabellose **ESP32-CAM** fällt, bieten folgende Projekte die beste Grundlage:

1.  **Random Nerd Tutorials:** *„ESP32-CAM Take Picture and Send to Server via HTTP POST“*
    *   *Fokus:* Der absolute Gold-Standard für die Software-Verbindung (C++ Code für ESP32 und HTTP-Empfänger auf dem Server).
2.  **Andreas Spiess (YouTube/GitHub):** *„ESP32-CAM: Ultra Low Power and AA Batteries“*
    *   *Fokus:* Exakte Details zur LDO-Schaltung (HT7333-A) und Strommessung ohne Lötarbeiten an der Kamera-Platine.
3.  **GitHub-Projekt `rzeldent/esp32-securitycam`:**
    *   *Fokus:* Eine fertige, hochoptimierte Firmware für ESP32-CAMs mit Deep-Sleep- und HTTP-POST-Support, die nur noch konfiguriert werden muss.
