# 📅 Leitfaden zur Zeitsteuerung der Gartenbewässerung

Dieses Dokument erklärt detailliert die verschiedenen Optionen, Parameter und Mechanismen zur Zeitsteuerung und der intelligenten wetterabhängigen Bewässerung (Weather Skip).

---

## 1. Parameter eines Zeitplans (Schedules)

Jeder Bewässerungs-Zeitplan in der Datenbank verfügt über vier Hauptparameter, die Sie flexibel über den Telegram-Bot einstellen können:

### 1. **Name** (`name`)
*   **Beschreibung**: Ein frei wählbarer, aussagekräftiger Name für den Zeitplan, um ihn leicht zu identifizieren.
*   **Beispiele**: `Morgens`, `Rasen Hinten`, `Hochbeete Abend`

### 2. **Startzeit** (`time`)
*   **Beschreibung**: Die genaue Uhrzeit im 24-Stunden-Format (`HH:MM`), zu der die Bewässerung beginnen soll.
*   **Format**: `HH:MM`
*   **Beispiele**: `06:30` (für halb sieben morgens), `20:45` (für viertel vor neun abends)

### 3. **Wochentage** (`days`)
*   **Beschreibung**: Bestimmt, an welchen Tagen der Zeitplan ausgeführt wird. Sie haben zwei Möglichkeiten:
    *   **Täglich**: Das Schlüsselwort `everyday` (führt die Bewässerung an jedem Wochentag aus).
    *   **Bestimmte Tage**: Eine kommagetrennte Liste der englischen Kurzformen der Wochentage:
        *   `Mon` (Montag)
        *   `Tue` (Dienstag)
        *   `Wed` (Mittwoch)
        *   `Thu` (Donnerstag)
        *   `Fri` (Freitag)
        *   `Sat` (Samstag)
        *   `Sun` (Sonntag)
*   **Beispiele**: 
    *   `everyday` (Jeden Tag)
    *   `Mon,Wed,Fri` (Montag, Mittwoch und Freitag)
    *   `Sat,Sun` (Nur am Wochenende)

### 4. **Dauer** (`duration_minutes`)
*   **Beschreibung**: Die Laufzeit der Bewässerung in Minuten.
*   **Sicherheitsbegrenzung**: Aus Sicherheitsgründen (Schutz vor Überflutung) ist die maximale Dauer softwareseitig auf **25 Minuten** limitiert, da das Ventil sich nach 30 Minuten hardwareseitig selbst schließt.
*   **Beispiele**: `10` (für 10 Minuten), `20` (für 20 Minuten)

---

## 2. Intelligente Wettersteuerung (Weather Skip)

Die Zeitsteuerung arbeitet nicht blind, sondern führt vor jedem geplanten Bewässerungsstart einen automatischen **Wetter-Check** über die Open-Meteo API durch.

### Niederschlagsschwelle (`RAIN_THRESHOLD_MM`)
*   **Ort der Konfiguration**: In der Datei `.env` (Standardwert: `3.0`).
*   **Funktionsweise**:
    1. Unmittelbar vor dem geplanten Start ruft der Daemon die Wetterdaten für Ihre Koordinaten ab.
    2. Er berechnet die **Summe des Niederschlags**:
       $$\text{Gesamtniederschlag} = \text{Regenmenge der letzten 24 Stunden (Historie)} + \text{erwartete Regenmenge der nächsten 24 Stunden (Vorhersage)}$$
    3. Ist dieser Gesamtwert **größer oder gleich** dem Grenzwert (z. B. `3.0` mm), wird die Bewässerung **übersprungen** (Weather Skip).
    4. Sie erhalten sofort eine Push-Benachrichtigung auf Ihr Handy (z. B. *"Zeitplan übersprungen! Gefallen: 1.5mm, Erwartet: 2.5mm"*).
    5. Der Übersprung wird im Protokoll in der SQLite-Datenbank als `skipped` archiviert.

---

## 3. Befehls-Syntax im Telegram-Bot

Sie können Ihre Zeitpläne direkt über den Chat mit folgenden Befehlen verwalten:

### A. Zeitplan auflisten
*   **Befehl**: `/zeitplan` oder drücken Sie den Button **`📅 Zeitpläne`**
*   **Beschreibung**: Zeigt alle hinterlegten Pläne inklusive ihrer ID, Uhrzeit, Tage, Dauer und des aktuellen Status (Aktiv/Inaktiv) an.

### B. Neuen Zeitplan anlegen
*   **Befehl**: `/add <Name>, <Uhrzeit>, <Tage>, <Dauer>`
*   **Beispiele**:
    *   `Mon, Wed, Fri` Bewässerung abends für 15 Minuten:
        `/add Abend, 20:30, Mon,Wed,Fri, 15`
    *   Tägliche Bewässerung morgens für 10 Minuten:
        `/add Hauptlauf, 07:00, everyday, 10`

### C. Zeitplan aktivieren/deaktivieren (Toggle)
*   **Befehl**: `/toggle <ID>`
*   **Beschreibung**: Schaltet den Status eines Zeitplans (Aktiv $\leftrightarrow$ Inaktiv) um. Inaktive Pläne werden nicht ausgeführt.
*   **Beispiel**: `/toggle 1`

### D. Zeitplan löschen
*   **Befehl**: `/delete <ID>`
*   **Beschreibung**: Löscht den Zeitplan dauerhaft aus der Datenbank.
*   **Beispiel**: `/delete 3`
