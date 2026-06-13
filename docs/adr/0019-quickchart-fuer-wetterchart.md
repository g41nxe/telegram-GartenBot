# 19. QuickChart.io für die Wetterchart-Generierung im Tagesbericht

Wir verwenden die externe HTTP-API QuickChart.io anstelle einer lokalen Python-Charting-Bibliothek, um den stündlichen Wetterchart im `/report`-Befehl als PNG-Bild zu generieren.

## Kontext

Der Raspberry Pi Zero W (ARMv6) schränkt die Wahl der Charting-Bibliothek erheblich ein:

- **matplotlib** ist die naheliegende Wahl, hat aber keine vorkompilierten Wheels für ARMv6 — `pip install matplotlib` schlägt auf dem Pi Zero W fehl. Nur über `apt install python3-matplotlib` verfügbar, was die Paketversion an das Betriebssystem-Repository koppelt.
- **gnuplot** (Systempaket) wäre offline verfügbar, erfordert aber einen `subprocess`-Aufruf und eine externe Skript-Syntax, die schwieriger zu warten ist als Python-Code.
- **Pillow** funktioniert auf ARMv6, erfordert jedoch manuelles Zeichnen von Achsen, Beschriftungen und Linien — erheblicher Implementierungsaufwand für ein Multi-Achsen-Chart.

Der Daemon nutzt bereits externe HTTP-APIs (Open-Meteo, Telegram). QuickChart.io ist ein weiterer externer Dienst, der über `urllib` (bereits in Verwendung) aufgerufen wird. Er generiert Chart.js-basierte PNGs über eine deklarative JSON-Konfiguration und benötigt keine lokale Installation.

## Entscheidung

Wir verwenden **QuickChart.io** für die Chart-Generierung. Die Chart-Konfiguration wird als Chart.js-JSON-Objekt im neuen Adapter `adapters/chart.py` zusammengestellt und per HTTP-POST an `https://quickchart.io/chart` übermittelt. Die Antwort ist ein PNG als `bytes`, das direkt per Telegram `sendPhoto` versandt wird.

Bei Nichtverfügbarkeit von QuickChart.io (Netzwerkfehler, Timeout) fällt der Adapter auf eine textbasierte Darstellung zurück (24 Zeilen, stündliche Auflösung).

## Konsequenzen

- Kein neues lokales Paket, kein ARMv6-Kompatibilitätsproblem.
- Der `/report`-Befehl ist von der Verfügbarkeit von QuickChart.io abhängig; der Textfallback stellt sicher, dass der Befehl auch offline nutzbar bleibt.
- Das Free-Tier von QuickChart.io (1.000 Charts/Monat) ist bei einem täglichen `/report` ausreichend.
- Wetterdaten (Temperatur, Niederschlag, Wahrscheinlichkeit) werden bei jedem Chart-Aufruf an einen Drittanbieter übermittelt.

## Verworfene Alternativen

- **matplotlib via apt**: Paketversion ist an das OS-Repository gekoppelt, keine pip-Kontrolle, kein `requirements.txt`-Eintrag möglich.
- **gnuplot**: Externe subprocess-Abhängigkeit, eigene Skript-Syntax, schlechtere Wartbarkeit.
- **Pillow (manuell)**: Zu hoher Implementierungsaufwand für ein ansprechendes Multi-Achsen-Chart.
