# 27. Zeitraffer-GIF-Generierung für die Garten-Kamera

Wir fassen die empfangenen Bilder der Garten-Kamera über ein konfigurierbares Intervall zu einem Zeitraffer-GIF zusammen und speichern nur dieses in der Bild-Historie.

## Context

Die M5Stack Timer Camera F liefert regelmäßig Bilder. Diese einzeln langfristig aufzubewahren, verbraucht zu viel Speicherplatz auf der Steuerzentrale (Raspberry Pi Zero W). Der Benutzer möchte stattdessen Zeitraffer-Bilder (GIFs) haben.

## Decision

- Eintreffende Bilder werden vorübergehend in einem temporären **Bild-Puffer** gesammelt.
- Das Intervall (der **Zeitraffer-Zyklus**) für die Erstellung der GIFs ist in Tagen konfigurierbar.
- Nach Ablauf des Intervalls wird aus den gepufferten Bildern ein Zeitraffer-GIF erstellt. Hierfür wird zwingend das Kommandozeilen-Tool `ffmpeg` verwendet, um die Bilder speichereffizient (als Stream) zu verarbeiten und RAM-Abstürze (Out Of Memory) auf dem Pi Zero W zu vermeiden.
- Das generierte GIF wird dauerhaft in der **Bild-Historie** archiviert und zusammen mit dem **Tagesbericht** via Telegram an den Benutzer gesendet.
- Der Benutzer kann über den Telegram-Befehl `/timelapse` jederzeit eine vorzeitige Vorschau (Sneak-Peek) des aktuellen Bild-Puffers als GIF anfordern, ohne dass die Originalbilder dabei gelöscht oder der laufende Zyklus unterbrochen werden.
- Die im Bild-Puffer gesammelten **Originalbilder werden nach der erfolgreichen GIF-Generierung unwiderruflich gelöscht**, um SD-Karten-Speicher freizugeben.

## Consequences

- Massive Einsparung von dauerhaft belegtem Speicherplatz auf der SD-Karte.
- Das unkomprimierte Bild liegt langfristig nicht mehr vor; das GIF ist die finale und einzige langfristige Repräsentation in der Bild-Historie.
- Eine Logik zur Überwachung des Intervalls (Zeitraffer-Zyklus) und zur Fehlerbehandlung bei der GIF-Generierung wird benötigt.
- Die Installations-Skripte der Steuerzentrale müssen um die Systemabhängigkeit `ffmpeg` erweitert werden.
