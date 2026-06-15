# Feature: Zeitraffer-GIF-Generierung

Dieses Feature fasst die empfangenen Bilder der Garten-Kamera über ein konfigurierbares Intervall automatisch zu einem Zeitraffer-GIF zusammen und entlastet so den Speicherplatz der Steuerzentrale.

## Übersicht

- Bilder werden temporär im **Bild-Puffer** gesammelt.
- Das Intervall (der **Zeitraffer-Zyklus**) ist in Tagen konfigurierbar.
- Nach Ablauf des Zyklus wird mit `ffmpeg` speichereffizient ein Zeitraffer-GIF generiert.
- Das fertige GIF wird im automatisierten Tagesbericht verschickt und dauerhaft in der Bild-Historie archiviert.
- Die Rohbilder werden anschließend restlos gelöscht.
- Ein Telegram-Befehl `/timelapse` erlaubt eine sofortige Vorschau (Sneak-Peek) des aktuellen Puffers.

## Telegram-Befehle

- `/timelapse` - Erzeugt sofort ein GIF aus dem aktuellen Bild-Puffer und sendet es ab (die Originalbilder werden dabei *nicht* gelöscht).

## Systemvoraussetzungen

- Auf der Steuerzentrale muss `ffmpeg` installiert sein.
