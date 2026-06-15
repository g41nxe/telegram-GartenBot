# Zeitraffer-GIF-Generierung für die Garten-Kamera

Die Garten-Kamera sammelt regelmäßig Bilder. Um den Speicherplatz auf dem Pi Zero W zu schonen und gleichzeitig einen schönen visuellen Rückblick zu bieten, werden die gesammelten Bilder in regelmäßigen Zyklen zu einem Zeitraffer-GIF kombiniert und die Rohdaten gelöscht.

## Offene Design-Entscheidungen (vor der Implementierung)

- **Unterstützung mehrerer Kameras:** In der Datenbank können theoretisch mehrere Kameras gekoppelt werden. Soll `/timelapse` und der automatisierte Tagesbericht für *jede* registrierte Kamera ein separates GIF erzeugen? (Annahme: Ja, getrennte GIFs pro Wunschnamen der Kamera).
- **Framerate:** Wie schnell soll das GIF abgespielt werden? Eine gute Basis sind 10 bis 15 Bilder pro Sekunde (fps). Wir werden einen vernünftigen Standardwert (z. B. 10 fps) nutzen und ihn in der Konfiguration anpassbar machen.

## Geplante Änderungen

### 1. System & Deployment

#### Setup-Skripte (Ansible / Bash)
- Hinzufügen von `ffmpeg` zu den System-Abhängigkeiten (`sudo apt-get install -y ffmpeg`), damit die Steuerzentrale GIFs effizient generieren kann.

#### Konfiguration (`config.py` oder `.env`)
- `TIMELAPSE_CYCLE_DAYS`: Konfigurierbares Intervall in Tagen (Standard: 1).
- `TIMELAPSE_FPS`: Abspielgeschwindigkeit (Standard: 10).

### 2. Domain & Speicherung

#### `camera_receiver.py` (oder äquivalenter Bild-Handler)
- Anpassen der Speicherlogik: Eintreffende Bilder werden nicht direkt ins langfristige Archiv, sondern in einen dedizierten Ordner für den **Bild-Puffer** geschrieben (sortiert nach Kamera).

#### `timelapse_service.py` (Neu)
- Einbindung von `ffmpeg` via Subprozess:
  `ffmpeg -f image2 -pattern_type glob -i 'buffer/*.jpg' -framerate 10 -vf scale=640:-1 out.gif`
- **Sicherheits-Logik**: Die Rohbilder im Puffer werden *ausschließlich* dann gelöscht, wenn der `ffmpeg`-Befehl erfolgreich (Exit Code 0) durchlief und die GIF-Datei existiert.

### 3. Telegram UI

#### `telegram_ui.py`
- **Befehl `/timelapse`**: Generiert on-the-fly ein temporäres Sneak-Peek-GIF aus dem aktuellen Bild-Puffer und sendet es dem Benutzer. **Wichtig:** Originalbilder werden dabei nicht gelöscht.
- **Tagesbericht-Integration**: Beim täglichen Report (08:00 Uhr) wird geprüft, ob der *Zeitraffer-Zyklus* erreicht ist. Falls ja, wird das finale GIF gebaut, an die Chat-Nachricht angehängt, dauerhaft archiviert und der Puffer geleert.

## Verifizierungsplan

### Automatisierte Tests
- Unit-Tests für `timelapse_service.py` zur Sicherstellung, dass `ffmpeg`-Parameter korrekt zusammengebaut werden.
- Tests der Fehlerbehandlung: Mock eines fehlgeschlagenen `ffmpeg`-Aufrufs -> Sicherstellen, dass keine Puffer-Bilder gelöscht werden.

### Manuelle Tests
- Lokaler Test mit simulierten Bildern: Aufruf von `/timelapse` im Bot verifizieren.
- Tagesbericht erzwingen und prüfen, ob das finale GIF als Anhang versendet wird und der Bild-Puffer danach leer ist.
