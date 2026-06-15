# Gieß-Empfehlung als pure Funktion in `core/`

Die Bewertungslogik für die Gieß-Empfehlung (`/giesscheck`) lebt als pure Funktion `evaluate()` in `core/watering_advice.py` — ohne I/O, ohne Zustand, ohne Adapter-Abhängigkeiten.

## Kontext

Die naheliegendere Alternative wäre gewesen, die Logik direkt im Telegram-Handler oder in `daily_report.py` zu implementieren. Bei einer einfachen Verkettung von drei if-Bedingungen erscheint ein eigenes Modul zunächst überdimensioniert.

## Entscheidung

Das Hexagonale Architekturprinzip dieses Projekts verbietet I/O in `core/`. Da die Gieß-Empfehlung zwei unabhängige Aufruforte hat (Telegram-Handler für `/giesscheck`, zukünftige Tagesbericht-Integration) und ohne Mocks testbar sein soll, ist `core/` der einzig korrekte Platz. Die Funktion nimmt Daten entgegen und gibt ein Tupel `(verdict, reasons)` zurück — kein Adapter-Import, kein Datenbankzugriff.

## Konsequenzen

- Beide Aufruforte teilen dieselbe Logik ohne Duplizierung.
- Tests für `evaluate()` brauchen keine Mocks — reine Eingabe/Ausgabe-Szenarien.
- `daily_report.py` bleibt ein reiner Formatter; die Bewertung ist davon entkoppelt.

**Ergänzung (Feature 0014):** `core/watering_advice.py` wurde zunächst mit der Teil-Funktion `evaluate_rain_window()` realisiert (für die pure Skip-/Caption-Entscheidung). Das vollständige `evaluate()` (aus Feature 0009) wird diese Basis kompositionell nutzen.
