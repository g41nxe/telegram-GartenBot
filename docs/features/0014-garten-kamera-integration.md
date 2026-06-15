# Feature: Garten-Kamera-Integration (M5Stack Timer Camera F)

## Problemstellung (Problem Statement)

Als Benutzer der Gartenbewässerung möchte ich visuell überprüfen können, ob meine Pflanzen ausreichend bewässert sind, wie sich das Wachstum entwickelt und ob die Ventile ordnungsgemäß schließen. Die Kamera muss im Garten per Akku betrieben werden können und darf daher den Akku nicht schnell entladen, das System nicht durch unbefugte Uploads kompromittieren oder die SD-Karte des Raspberry Pi mit unbegrenzten Bilddaten überlasten.

## Lösung (Solution)

Wir integrieren eine oder mehrere **Garten-Kameras** (M5Stack Timer Camera F) in das System. Die Kamera wacht periodisch aus dem Deep Sleep auf, macht ein Foto, verbindet sich mit dem WLAN, fragt dynamisch Einstellungen ab, lädt das Bild per HTTP POST auf die Steuerzentrale hoch und schläft sofort wieder ein. Die Steuerzentrale verwaltet die Kameras, steuert das Pairing, bereinigt alte Fotos und stellt dem Benutzer über den Telegram-Bot komfortable Abruf- und Konfigurationsmöglichkeiten bereit.

## User Stories

1. Als Benutzer möchte ich eine neue Garten-Kamera über den Telegram-Bot koppeln können, um sie im System zu registrieren und ihr einen Wunschnamen zu geben.
2. Als Benutzer möchte ich den Koppelmodus zeitbegrenzt (90 Sekunden) aktivieren, um zu verhindern, dass sich unerwünschte Geräte im Netzwerk als Kamera registrieren.
3. Als Benutzer möchte ich mit dem Befehl `/photo` das aktuellste Foto meiner Garten-Kamera anfordern, um den aktuellen Zustand meines Gartens zu sehen.
4. Als Benutzer möchte ich bei mehreren gekoppelten Garten-Kameras über eine Auswahltastatur im Bot wählen können, welches Bild ich sehen möchte, um den Überblick zu behalten.
5. Als Benutzer möchte ich das Schlafintervall der Garten-Kamera dynamisch über den Telegram-Bot anpassen können (z. B. `/camera_interval 30`), ohne die Kamera flashen zu müssen.
6. Als Benutzer möchte ich über den Inaktivitäts-Watchdog gewarnt werden, wenn eine Kamera seit dem Dreifachen ihres Schlafintervalls kein Bild mehr hochgeladen hat, um eine leere Batterie oder Funkstörungen zu erkennen.
7. Als Systembetreiber möchte ich, dass Bilder, die älter als 30 Tage sind, automatisch gelöscht werden, um die SD-Karte des Raspberry Pi vor dem Volllaufen zu schützen.
8. Als Systembetreiber möchte ich, dass das jeweils erste Bild eines jeden Tages dauerhaft aufbewahrt wird, um später Zeitraffer-Aufnahmen des Gartenwachstums generieren zu können.
9. Als Systembetreiber möchte ich, dass die Kamera bei Verbindungsfehlern stufenweise seltener aufwacht (Exponential Backoff), um bei längeren Netzwerkausfällen den Akku zu schonen.

## Implementierungs-Entscheidungen (Implementation Decisions)

### 1. Datenmodell & Persistenz
* Wir erstellen eine neue Datenbanktabelle zur Verwaltung der Kameras. Diese speichert die MAC-Adresse (Primärschlüssel), den eindeutigen Wunschnamen, den Zeitstempel des letzten Kontakts sowie Konfigurationsparameter (Schlafintervall, Auflösung, Qualität).

### 2. HTTP-API (Schnittstelle Kamera <-> Steuerzentrale)
* Der Daemon auf dem Pi startet einen separaten, leichtgewichtigen HTTP-Server auf einem konfigurierbaren Port.
* **`POST /register`**: Wird von der Kamera beim Booten aufgerufen. Wenn das Koppelzeitfenster offen ist, wird die Kamera mit ihrer MAC-Adresse registriert.
* **`GET /config`**: Die Kamera fragt unter Angabe ihrer MAC-Adresse ihre Konfiguration (Schlafzeit, Kameraauflösung, JPEG-Qualität) ab.
* **`POST /upload`**: Die Kamera lädt das aufgenommene Bild als rohen JPEG-Datenstrom im Body hoch. Die MAC-Adresse wird im HTTP-Header mitgesendet. Der Pi validiert das Bild und speichert es.

### 3. C++ Firmware (Garten-Kamera)
* Nutzt die herstellerspezifische Bibliothek zur Ansteuerung des Weitwinkel-Kamerasensors.
* Bypasst das langsame DHCP-Protokoll, indem die Kamera eine statische IP-Adresse im lokalen WLAN nutzt.
* Speichert den Backoff-Fehlerzähler im RTC-RAM (überlebt den Deep Sleep), um bei Verbindungsfehlern ein progressiv ansteigendes Schlafintervall (1, 2, 4, 8 Minuten) zu berechnen.
* Nutzt den RTC-Chip, um die Stromversorgung des ESP32 am Ende des Zyklus physisch zu trennen und nach Ablauf des Intervalls wieder anzuschalten.

### 4. Bild-Management & Cleanup
* Die empfangenen Bilder werden in getrennten Ordnern pro Kamera-Wunschnamen gespeichert. Das aktuellste Bild wird stets als symbolischer Link oder Kopie bereitgestellt.
* Ein täglicher Scheduler-Job durchsucht die Kameraordner, löscht alle Bilder, die älter als 30 Tage sind, schließt jedoch das chronologisch erste Bild jedes Kalendertages von der Löschung aus.

### 5. Watchdog-Integration
* Der Inaktivitäts-Watchdog des Daemons überwacht den `last_seen`-Zeitstempel aller registrierten Kameras. Das Toleranzfenster beträgt das 3-Fache des für die Kamera konfigurierten Schlafintervalls (mindestens jedoch 1 Stunde).

## Test-Entscheidungen (Testing Decisions)

### Nahtstellen (Seams) für Tests

1. **HTTP-Endpunkte-Integrationstest (driving seam):**
   Wir testen den HTTP-Server des Daemons, indem wir programmgesteuert HTTP-Requests absetzen.
   * *Szenario:* Pairing-Fenster öffnen, `POST /register` senden, prüfen, ob die Kamera in der DB angelegt wird.
   * *Szenario:* `GET /config` mit registrierter/unregistrierter MAC senden und JSON-Antwort validieren.
   * *Szenario:* `POST /upload` mit gültigem/ungültigem JPEG-Inhalt senden und Dateierstellung sowie EventBus-Benachrichtigung verifizieren.

2. **Watchdog-Integrationstest (core seam):**
   Wir simulieren den Ablauf der Zeit über Mock-Daten in der Datenbank und prüfen, ob die Watchdog-Komponente ein Inaktivitäts-Event auf dem EventBus publiziert, wenn der letzte Kontakt der Kamera das berechnete Limit überschreitet.

3. **Cleanup-Job-Unittest:**
   Wir legen Mock-Dateien mit verschiedenen Dateizeitstempeln an und lassen die Bereinigungsfunktion darüber laufen. Wir testen, ob alte Dateien gelöscht, Tages-Erstbilder und neuere Dateien jedoch beibehalten werden.

*Referenz-Tests:* Ähnliche Strukturen finden sich in den Integrationstests des Pairing-Moduls und des Watchdogs.

## Nicht im Leistungsumfang (Out of Scope)

* Das Erstellen von tatsächlichen Zeitraffer-Videos (MP4/GIF) aus der Bild-Historie. Dies wird in einem zukünftigen Feature realisiert.
* Eine Weboberfläche zur Bildbetrachtung (Telegram bleibt die einzige Benutzeroberfläche).
* Konfiguration des WLAN-Netzwerks über ein lokales Captive Portal (die Zugangsdaten werden fest einkompiliert).

## Weitere Anmerkungen (Further Notes)

* Für die Kompilierung des C++ Codes wird die Bibliothek `ArduinoJson` in der Firmware benötigt.
* Der Port des HTTP-Empfängers muss in der Firewall der Steuerzentrale (Raspberry Pi) freigegeben werden.
