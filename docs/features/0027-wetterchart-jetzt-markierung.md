# Feature: Wetterchart Jetzt-Markierung

## Problemstellung (Problem Statement)

Das Wetterchart im täglichen Bericht des Telegram-Bots zeigt nur einen kleinen Ausschnitt (-2h bis +22h), und die aktuelle Uhrzeit ist nicht markiert. Der Benutzer kann auf einen Blick nicht erkennen, wo im Chart sich „jetzt" befindet, welche Balken gemessener Regen sind und welche Vorhersage. Außerdem stimmen die vertikalen Gitternetzlinien nicht mit den Achsenbeschriftungen überein, was das Ablesen von Werten erschwert.

## Lösung (Solution)

Das Wetterchart wird auf ein ±24h-Fenster erweitert, damit genau die Datenmenge angezeigt wird, die auch der Bewässerungshinweis verwendet. In der Mitte des Charts erscheint eine dezente gestrichelte Linie mit dem Label „Jetzt", die Vergangenheit und Vorhersage visuell trennt. Gemessener Regen der letzten 24 Stunden wird voll opak dargestellt, Vorhersageregen mit wahrscheinlichkeitsabhängiger Transparenz. Die Gitternetzlinien werden über das Annotation-Plugin gerendert, damit sie pixelgenau unter den Achsenlabels liegen.

## User Stories

1. Als Benutzer möchte ich im Wetterchart die letzten 24 Stunden und die nächsten 24 Stunden sehen — dasselbe Zeitfenster, das der Bewässerungshinweis verwendet —, damit Chart und Entscheidung auf denselben Daten basieren.
2. Als Benutzer möchte ich die aktuelle Uhrzeit als „Jetzt" auf der Zeitachse beschriftet sehen, damit ich auf einen Blick erkenne, was Vergangenheit und was Vorhersage ist.
3. Als Benutzer möchte ich eine dezente vertikale Linie bei „Jetzt", die optisch zur bestehenden 0°C-Linie passt (gleiche Farbe, Breite, Strichelung), damit das Chart einheitlich wirkt.
4. Als Benutzer möchte ich, dass Beschriftungen und Gitternetzlinien genau übereinstimmen (alle 3 Stunden), damit ich Werte präzise ablesen kann.
5. Als Benutzer möchte ich, dass gemessener Regen der Vergangenheit voll opak dargestellt wird und Vorhersageregen entsprechend seiner Eintrittswahrscheinlichkeit transparent erscheint, damit ich sicher von unsicheren Daten unterscheide.
6. Als Benutzer möchte ich, dass das Chart auch dann korrekt angezeigt wird, wenn die Wetterdaten mehrere Stunden alt sind — in diesem Fall ohne die Jetzt-Markierung, aber mit vollem Datenfenster.
7. Als Benutzer möchte ich, dass der Chart-Titel das Zeitfenster korrekt beschreibt, damit ich beim Lesen sofort weiß, was der Chart abdeckt.
8. Als Benutzer möchte ich die Achsenlabels leicht geneigt lesen können, damit sie sich bei dicht beieinanderliegenden Stundenwerten nicht überlappen.

## Implementierungs-Entscheidungen (Implementation Decisions)

**Datenfenster:**
- Das Datenfenster wird von -2h/+22h auf ±24h (48 Datenpunkte) erweitert.
- Die Schnittmenge mit den verfügbaren API-Daten (`past_days=1`, `forecast_days=2`) deckt dieses Fenster vollständig ab.
- `now_index` = 24 (fest bei vollem Vergangenheitspuffer), allgemein: `current_idx - chart_start`.

**Jetzt-Linie (Annotation):**
- Eine vertikale Annotation-Linie bei `xMin = xMax = now_index` mit identischem Stil zur 0°C-Linie:
  ```python
  dash_line = {"borderColor": "rgba(60,60,60,0.35)", "borderWidth": 1, "borderDash": [6, 3]}
  ```
  *(Aus dem validierten Prototyp `scripts/test_chart.py`.)*
- Wenn `now_index < 0` (kein passender Zeitstempel in den Stundendaten), wird keine Jetzt-Linie hinzugefügt.

**Jetzt-Label:**
- An Position `now_index` auf der X-Achse erscheint „Jetzt" anstelle des regulären Stunden-Labels.
- Alle anderen Positionen folgen der bestehenden Regel: alle 3 Stunden `HH:MM`, dazwischen leer.
- Die Umsetzung nutzt die Labels-Liste (kein JavaScript-Callback), da QuickChart.io keine JS-Funktionen serialisieren kann.

**Gitternetzlinien via Annotation-Plugin:**
- Natives `x.grid` wird deaktiviert (`display: false`), weil Chart.js native Gitternetzlinien an der linken Kante von Balken zeichnet, Tick-Labels aber an der Balkenmitte erscheinen — das erzeugt einen systematischen halben-Balkenbreite-Versatz.
- Stattdessen werden vertikale Annotation-Linien bei jeder 3. Position eingefügt (`xMin = xMax = i` für `i % 3 == 0`). Annotationen verwenden dieselbe Koordinate wie die Tick-Labels (Balkenmitte) und sind damit pixelgenau ausgerichtet.
- Gitternetz-Stil: `borderColor: rgba(0,0,0,0.07)`, `borderWidth: 1`, kein Dash.

**Niederschlag-Opazität Vergangenheit vs. Vorhersage:**
- Der Wetter-Dienst-Adapter setzt `precip_prob` für vergangene Stunden mit gemessenem Regen auf 100, sonst auf 0.
- Zukünftige Stunden behalten die Vorhersagewahrscheinlichkeit.
- Die Opazitätsformel im Chart-Adapter bleibt unverändert: `alpha = 0.15 + 0.75 * (prob / 100)`.

**Tick-Rotation:**
- Labels werden um 45° geneigt (`minRotation: 45, maxRotation: 45`), damit bei 48 Datenpunkten keine Überlappung entsteht.

**Chart-Titel:**
- Geändert von „Wetterverlauf — nächste 24h" zu „Wetterverlauf — letzte & nächste 24h".

**Zuständigkeit der Module:**
- Der Wetter-Dienst-Adapter erweitert das Datenfenster und setzt die `precip_prob`-Werte für die Vergangenheit.
- Der Chart-Adapter ermittelt `now_index` aus den empfangenen Zeitstempeln und baut die Annotationen und Labels.
- Die Trennung zwischen Vergangenheit und Vorhersage liegt bewusst im Wetter-Dienst-Adapter, weil nur dieser die Information hat, ob ein Stundenwert gemessen oder vorhergesagt ist.

## Test-Entscheidungen (Testing Decisions)

**Was einen guten Test ausmacht:**
- Tests greifen ausschließlich auf das externe Verhalten zu: den JSON-Payload, der an QuickChart.io gesendet wird, bzw. das `hourly_forecast_json`-Feld, das in die Datenbank geschrieben wird.
- Implementierungsdetails wie interne Hilfsfunktionen oder die genaue Annotation-ID werden nicht direkt behauptet — stattdessen wird geprüft, ob das Ergebnis die erwarteten strukturellen Eigenschaften hat.

**Chart-Adapter (`tests/adapters/test_chart.py`):**
Das bestehende Muster `_capture_and_return()` (mock `database.get_last_weather` + mock `urllib.request.urlopen`, Payload inspizieren) ist die höchste verfügbare Nahtstelle und wird beibehalten. Neue Tests prüfen:
- Ob eine Annotation mit `xMin == xMax` und dem Jetzt-Linienstil vorhanden ist, wenn der Zeitstempel im Datensatz liegt.
- Ob kein `nowLine`-Eintrag in den Annotationen erscheint, wenn kein Zeitstempel zur aktuellen Stunde passt.
- Ob das Label an `now_index` den Wert „Jetzt" trägt und alle anderen Labels die Drei-Stunden-Regel einhalten.
- Ob vertikale Annotation-Linien bei allen Vielfachen von 3 vorhanden sind.
- Ob `x.grid.display` auf `false` gesetzt ist.
- Ob der Chart-Titel das Wort „letzte" enthält.

Der bestehende Test `test_labels_every_third_hour` muss aktualisiert werden: er soll „Jetzt" an der richtigen Position akzeptieren. Der Test nutzt Fixture-Zeiten aus der Vergangenheit, bei denen `now_index == -1` gilt — dort fällt kein „Jetzt"-Label an, sodass der Test weiterhin einfach gehalten werden kann.

Für Tests, die Jetzt-Verhalten prüfen, wird `datetime.now` gemockt und eine passende Fixture mit 48 Zeitstempeln um den gemockten Zeitpunkt herum verwendet.

**Wetter-Dienst-Adapter (`tests/adapters/test_weather.py`):**
Bestehende Nahtstelle: `get_weather_data()` mockt den HTTP-Aufruf an die Open-Meteo-API und prüft das publizierte `WeatherDataFetched`-Event (oder direkt das Rückgabetupel). Neue Tests prüfen:
- Ob `hourly_forecast_json` 48 Einträge enthält (statt 24).
- Ob `precip_prob` für vergangene Stunden mit `precip_mm > 0` den Wert 100 hat.
- Ob `precip_prob` für vergangene trockene Stunden den Wert 0 hat.

Referenzmuster für neue Tests: `TestGenerateWeatherChart` in `tests/adapters/test_chart.py` (Payload-Capture) sowie bestehende Wetter-Tests in `tests/adapters/test_weather.py`.

## Nicht im Leistungsumfang (Out of Scope)

- Änderungen an der Caption-Logik (`_build_caption`) — bleibt auf `rain_last_24h` + `rain_next_24h`.
- Änderungen an Farben, Temperaturachse oder anderen Chart-Parametern.
- Das Testscript `scripts/test_chart.py` wird nicht an die Produktionslogik angeglichen (es dient als eigenständiges Entwicklungswerkzeug mit festen Beispieldaten).
- Die Design-Spec `docs/superpowers/specs/2026-06-22-wetterchart-jetzt-markierung-design.md` wird durch dieses Dokument als primäre Referenz abgelöst; beide können koexistieren.

## Weitere Anmerkungen (Further Notes)

- Mockup und Prototyp: `docs/design/wetterchart-jetzt-mockup.html` (interaktiver Browser-Chart) und `scripts/test_chart.py` (QuickChart.io-Integration) dokumentieren das validierte visuelle Ergebnis.
- Der Alignment-Bug zwischen Gitternetz und Labels ist eine Chart.js-Eigenheit bei `type: bar` mit `offset: true` (Standard): native Grid-Linien erscheinen an der linken Kante jedes Balkens, Tick-Labels jedoch an der Mitte. Dieses Verhalten ist nicht konfigurierbar — der Annotation-Ansatz ist die korrekte Lösung.
- Die API-Konfiguration (`past_days=1`, `forecast_days=2`) liefert ausreichend Daten für das ±24h-Fenster; keine API-Parameter-Änderungen nötig.
