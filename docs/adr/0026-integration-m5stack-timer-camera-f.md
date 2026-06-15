# 26. Integration M5Stack Timer Camera F (Garten-Kamera)

Wir werden eine oder mehrere batteriebetriebene M5Stack Timer Camera F Module als **Garten-Kameras** in das System integrieren.

## Kontext

Für eine visuelle Überwachung des Gartens und der Bewässerungseffekte soll das System Bilder empfangen, archivieren und über den Telegram-Bot ausgeben können. Da die Kameras im Außenbereich per Akku betrieben werden, müssen sie extrem stromsparend arbeiten. Zudem soll das System sicher sein, mehrere Kameras unterstützen und flexibel konfigurierbar sein.

## Entscheidung

Wir implementieren folgende Architektur und Verfahren zur Anbindung der Garten-Kamera:

1. **Indirekte HTTP-Verbindung:** 
   Die Kameras kommunizieren nicht direkt mit der Telegram-API (aus Sicherheitsgründen, um das Bot-Token zu schützen). Stattdessen laden sie ihre Bilder per HTTP POST direkt auf einen neuen HTTP-Empfängerdienst (`camera_receiver`) auf der Steuerzentrale (Raspberry Pi) hoch. Der Daemon speichert die Bilder und leitet sie auf Anfrage an den Telegram-Bot weiter.

2. **Akkuschonender Deep-Sleep-Betrieb:** 
   Die Kamera schläft fast durchgehend (2 µA) und wacht nur periodisch (z. B. alle 15 Minuten) auf, um ein Foto zu machen, dieses hochzuladen und sich sofort wieder abzuschalten. Zur Reduzierung der aktiven Online-Zeit (Vermeidung von DHCP-Handshakes) wird der Kamera eine statische IP-Adresse zugewiesen.

3. **Hybrid-Konfigurationsmodell:** 
   WLAN-Zugangsdaten sind statisch im C++ Code hinterlegt. Vor jeder Aufnahme fragt die Kamera jedoch über `GET /config` unter Angabe ihrer MAC-Adresse ihre aktuellen Betriebsparameter (Aufweck-Intervall, Auflösung, Bildqualität) vom Pi ab. Dies erlaubt eine zentrale Steuerung der Kamera-Parameter ohne erneutes Flashen.

4. **Kamera-Kopplung (Pairing) über MAC-Adresse:** 
   Neue Kameras werden über einen geführten Telegram-Befehl `/camera_setup` angelernt. Der Pi öffnet ein 90-Sekunden-Fenster, in dem eine neu bootende Kamera ihre MAC-Adresse per `POST /register` registriert und einem Wunschnamen zugeordnet wird. Nicht registrierte Kameras werden vom HTTP-Server mit `403 Forbidden` abgewiesen.

5. **WLAN-Fehlertoleranz mit Exponential Backoff (RTC-RAM):** 
   Schlägt die WLAN-Verbindung der Kamera fehl (Timeout nach 15s), wird ein Fehlerzähler im RTC-RAM der Kamera (`RTC_DATA_ATTR`) erhöht. Die Kamera schläft daraufhin für ein stufenweise ansteigendes Intervall ($60 \times 2^{\text{failures}}$ Sekunden), gedeckelt beim regulären Intervall, um den Akku bei dauerhaften Funklöchern zu schonen. Bei erfolgreicher Verbindung wird der Zähler zurückgesetzt.

6. **Dynamische Kamera-Überwachung (Watchdog):** 
   Der Inaktivitäts-Watchdog des Daemons wird um die Garten-Kameras erweitert. Das Watchdog-Timeout wird dynamisch auf das **3-Fache des konfigurierten Schlafintervalls** (mindestens jedoch 1 Stunde) gesetzt. Bleibt das Bild aus, wird der Benutzer per Telegram gewarnt.

7. **Bild-Historie und Menüführung:** 
   Bilder werden in dedizierten Ordnern pro Kamera abgelegt (`data/camera/<wish_name>/`). Wenn mehrere Kameras gekoppelt sind, bietet der Bot-Befehl `/photo` ein Inline-Keyboard zur Auswahl der Kamera an. Bei nur einer Kamera wird das Bild direkt gesendet.

8. **Automatische Bild-Bereinigung:**
   Um ein Volllaufen der SD-Karte der Steuerzentrale zu verhindern, wird eine intelligente Bereinigungslogik implementiert. Ein täglicher Job löscht Bilder, die älter als 30 Tage sind. Das jeweils erste aufgenommene Bild eines Tages wird jedoch dauerhaft aufbewahrt, um langfristige Zeitraffer-Aufnahmen zu ermöglichen.


## Konsequenzen

* **Sicherheit:** Das Telegram-Bot-Token verbleibt sicher auf dem Pi.
* **Batterielaufzeit:** Maximiert durch minimalen Online-Wachzustand (statisches IP-Routing) und robustes Backoff-Verhalten bei Netzstörungen.
* **Modularität:** Neue Kameras können dynamisch über den Bot registriert werden.
* **Komplexität:** Erhöhter Implementierungsaufwand im C++ Code der Kamera (RTC-RAM Verwaltung, JSON-Parsing via ArduinoJson) sowie im Python-Daemon (HTTP-Server Thread, Datenbank-Erweiterung).
