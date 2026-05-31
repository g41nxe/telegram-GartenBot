# 3. Softwarebasierte Wetterdaten-Integration über Online-API

Wir verwenden zur Erfassung von Niederschlag und Wettervorhersagen ausschließlich eine externe, kostenlose Online-Wetter-API (Open-Meteo) und verzichten auf physische Bodenfeuchtigkeits- oder Regensensoren.

## Kontext

Die Steuerung soll intelligent auf Regen reagieren können, ohne dass zum Start teure oder wartungsintensive physische Sensorhardware im Garten installiert werden muss. Der Benutzer verfügt über keine physischen Sensoren.

## Entscheidung

Wir integrieren die kostenlose **Open-Meteo API** in den Bewässerungs-Daemon. Die Steuerzentrale fragt in regelmäßigen Intervallen die historischen Regenmengen der letzten 24 Stunden sowie die Vorhersage für die kommenden 24 Stunden ab.
Liegt der gemessene oder vorhergesagte Niederschlag über einem definierten Schwellenwert (z. B. 3 mm), wird die geplante Bewässerung automatisch übersprungen (Weather Skip).

## Konsequenzen

- **Vorteile**: Keine zusätzlichen Hardwarekosten, keine Batteriewechsel für Sensoren, kein Verschleiß im Außenbereich, sofortige Implementierbarkeit.
- **Nachteile**: Wettervorhersagen und historische Stationsdaten können vom tatsächlichen Mikroklima des Gartens abweichen (z. B. bei lokalen Schauern).
