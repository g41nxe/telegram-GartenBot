# 47. Kein Aufnahme-Zeitpunkt außerhalb des Tageslichts

Aufnahme-Zeitpunkte, die außerhalb des Tageslicht-Fensters lägen, **entstehen gar nicht**.
Sonnenauf- und -untergang werden lokal aus Koordinaten und Datum gerechnet, nicht abgefragt.
Welche Sorte Aufnahme-Zeitpunkt der Dunkelheit weicht, entscheidet die Konfiguration.

## Kontext

Ein Bewässerungs-Zeitplan liegt aus guten Gründen oft am Rand des Tages — abends nach der
Hitze, morgens vor der Sonne. Das daraus abgeleitete Guss-Foto (ADR 0036) erbte diese Uhrzeit
blind: Ein Guss um 22:00 erzeugte einen Aufnahme-Zeitpunkt um 22:32, die Garten-Kamera wurde
geweckt, belichtete ein schwarzes Bild und der Bot stellte es als „📷 Nach dem Guss „Rasen""
zu. Die Kamera hat keine Beleuchtung; im Dunkeln gibt es nichts aufzunehmen.

Drei Stellen hätten den Fall abfangen können, und die Wahl zwischen ihnen ist die eigentliche
Entscheidung:

1. **Bei der Zustellung** (`camera_receiver.handle_upload`) das Ereignis unterdrücken.
2. **Nach dem Upload** die Helligkeit des JPEG prüfen.
3. **Bei der Erzeugung** des Aufnahme-Zeitpunkts (`core/camera_schedule.py`).

Variante 1 scheitert an der Kopplung: Der Aufnahme-Zeitpunkt bliebe für die Kamera-Überwachung
bestehen und würde nach ADR 0041 als **verpasster Aufnahme-Zeitpunkt** gemeldet — das schwarze
Foto wäre durch einen Fehlalarm ersetzt. Außerdem wäre die Kamera nachts trotzdem aufgewacht;
sie ist batteriebetrieben.

Variante 2 kommt grundsätzlich zu spät: Der Akku ist verbraucht, bevor die Prüfung greift, und
über die Schlafdauer kann sie nichts aussagen. Sie bräuchte zudem eine JPEG-Dekodierung —
`requirements.txt` enthält allein `paho-mqtt`, Pillow wäre auf dem Raspberry Pi Zero W eine
teure neue Abhängigkeit für eine Frage, die sich vorher beantworten lässt.

Für die Bestimmung der Dunkelheit lagen zwei Quellen nahe: `daily=sunrise,sunset` beim ohnehin
laufenden Open-Meteo-Aufruf, oder die Rechnung aus `LATITUDE`/`LONGITUDE` (bereits in der
`.env`, ADR 0030). Feste Uhrzeit-Grenzen scheiden aus — in Berlin liegt der Sonnenuntergang
zwischen 15:50 und 21:33.

## Entscheidung

- **Der Filter greift bei der Erzeugung, nicht bei der Zustellung.** `_all_targets` in
  `core/camera_schedule.py` ist die einzige Quelle aller Aufnahme-Zeitpunkte und filtert dort.
  Damit erben alle vier Verbraucher dieselbe Regel: Schlafdauer (die Kamera wird nicht
  geweckt), Zustellung (kein Foto), Kamera-Überwachung (kein Verzugs-Alarm) und Bot-Anzeige
  (kein angekündigter Zeitpunkt, der nie kommt). Ein unterdrückter Aufnahme-Zeitpunkt ist
  **nicht vorhanden**, nicht **ausgefallen**.

- **Sonnenauf-/untergang wird gerechnet, nicht abgefragt.** `core/sun.py` implementiert die
  Sonnenaufgangsgleichung (NOAA/Meeus, gekürzte Reihe) mit `math` — rein, ohne I/O, ~2 min
  genau. Der Netzweg hätte Persistenz und Durchreichung der Zeiten erfordert und wäre bei
  API-Ausfall ohne Grundlage; Sonnenstand ist eine Funktion von Datum und Ort, keine
  Beobachtung. Die Genauigkeit ist gegen den Puffer belanglos.

- **Ein Puffer rückt beide Grenzen nach innen** (`CAMERA_DAYLIGHT_MARGIN_MINUTES`, Standard 30).
  Zwischen dem Moment des Sonnenaufgangs und Licht, bei dem ein Beet auf einem Foto erkennbar
  ist, liegt eine gute halbe Stunde. Zehrt der Puffer den ganzen Tag auf, gilt der Tag als
  dunkel — die Grenzen dürfen nicht kippen.

- **Der Geltungsbereich ist konfigurierbar** (`CAMERA_DAYLIGHT_FILTER_TYPES`, Standard
  `guss,fix`). Die Werte sind die Label-Typen der Aufnahme-Zeitpunkte. Ein Guss-Foto entsteht
  als Nebenwirkung einer Uhrzeit, die wegen der Bewässerung gewählt wurde; eine feste Fotozeit
  hat der Benutzer bewusst gesetzt. Beide Lesarten sind vertretbar, deshalb entscheidet die
  Konfiguration und nicht der Code. Leere Menge = Filter aus.

- **Ohne Koordinaten bleibt der Filter aus.** `LATITUDE`/`LONGITUDE` haben den Vorgabewert
  `0.0` (config.py) — das ist der Golf von Guinea. Lieber nicht filtern als am falschen Ort.

- **Die Verdrahtung liegt in `src/daemon/camera_daylight.py`.** Nach ADR 0045 folgt der
  Modulort der Kopplung: Der Code liest Konfiguration (also kein Kern-Modul) und wird von
  `adapters/` **und** `ui/` gebraucht (als Adapter verletzte er Regel 1). Er reicht dem Kern
  nach ADR 0017 ein einzelnes Prädikat herein statt fünf Konfigurationswerte durch jede Ebene.

## Konsequenzen

- **Vorteile:**
  - Kein schwarzes Foto, kein Fehlalarm, und die Kamera schläft nachts durch — bei
    Batteriebetrieb der handfesteste Gewinn.
  - `core/sun.py` und der Filter sind rein und deterministisch testbar; die Sonnenwenden-Tests
    prüfen gegen echte Almanach-Werte.
  - Keine neue Abhängigkeit, kein zusätzlicher Netzaufruf.

- **Nachteile:**
  - Ein Guss am Rand des Tageslicht-Fensters verliert sein Foto ohne Hinweis. Bewusst: Eine
    Meldung „kein Foto, weil dunkel" nach jedem Abendguss wäre täglicher Lärm für einen
    Zustand, den der Benutzer selbst gesetzt hat.
  - Tests, die mit `datetime.now()` arbeiten, werden vom Filter uhrzeitabhängig. Sie schalten
    ihn deshalb ausdrücklich ab (`ohne_tageslicht_filter`), und die Verdrahtung wird mit
    festem Prädikat geprüft statt mit echter Sonnenstands-Rechnung.
  - Die Rechnung ist auf ~2 min genau. Bei einem Puffer von 30 min irrelevant; wer den Puffer
    auf 0 setzt, sollte das wissen.
