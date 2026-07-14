# 40. Zustellung nach Aufnahme-Verzug statt Toleranzfenster

Ein Aufnahme-Zeitpunkt wird vom **ersten Bild erfüllt, das nach ihm eintrifft** — nicht mehr von
einem Bild innerhalb eines engen Toleranzfensters. Er bleibt offen, bis der nächste
Aufnahme-Zeitpunkt ihn ablöst. Weicht die Aufnahmezeit nennenswert vom Aufnahme-Zeitpunkt ab,
nennt die Bildunterschrift sie ausdrücklich.

Löst den Zustellungs-Teil von ADR 0026 (Punkt 7) und ADR 0036 ab.

## Kontext

Die Zustellung prüfte bisher, ob ein Upload **innerhalb von ±5 Minuten** um einen
Aufnahme-Zeitpunkt eintraf (`find_matching_photo_target`, `TIMED_PHOTO_TOLERANCE_MINUTES`).
Traf er das Fenster nicht, wurde das Bild gespeichert, aber **stillschweigend nicht zugestellt**.

Eine Auswertung dreier Betriebstage (12.–14.07.2026, Fotozeiten 08:00/20:00, Guss-Foto 22:22)
zeigte: **Nur 2 von 7 Aufnahme-Zeitpunkten wurden zugestellt.** Die Uploads trafen 2 bis 34
Minuten nach ihrem Aufnahme-Zeitpunkt ein und fielen damit regelmäßig aus dem Fenster. Der
Nutzer bekam keine Fotos, obwohl jedes einzelne auf der Steuerzentrale lag und beim manuellen
Abruf sichtbar war.

Die Ursache liegt in der Garten-Kamera (siehe ADR 0002 im Kamera-Repository): Sie wacht
pünktlich auf, aber einzelne Zyklen scheitern, und jeder gescheiterte Zyklus schiebt den Upload
um eine Backoff-Schlafdauer nach hinten. Entscheidend ist die daraus folgende Einsicht:

> **Die Steuerzentrale darf sich nicht darauf verlassen, dass die Garten-Kamera minutengenau
> erscheint.** Sie ist ein batteriebetriebenes Gerät ohne Uhr, das über eine Schlafdauer
> gesteuert wird; ihr Wecker ist bauartbedingt auf ±60 s genau, und Störungen verschieben ihn
> weiter. `CONTEXT.md` sagt das seit jeher („nähert sich an") — die Implementierung verlangte
> trotzdem Präzision und bestrafte deren Ausbleiben mit Datenverlust.

Verworfene Alternative — **breiteres Fenster** (z. B. ±60 min): behebt das Symptom, nicht die
Annahme. Jede feste Fensterbreite ist eine Wette auf die Pünktlichkeit eines Geräts, dessen
Pünktlichkeit wir nicht kontrollieren — und der Verlust bleibt still.

Verworfene Alternative — **Verfallsdauer** (Zeitpunkt verfällt nach N Minuten): verliert das
Bild trotzdem, obwohl es vorliegt. Warnung *und* Datenverlust ist die schlechteste Kombination.

## Entscheidung

1. **Erfüllung statt Fenster.** Bei jedem Upload ermittelt die Steuerzentrale den **jüngsten
   bereits fälligen** Aufnahme-Zeitpunkt. Ist es ein anderer als der zuletzt zugestellte, gilt er
   als erfüllt: Das Bild wird zugestellt und der Zeitpunkt als zugestellt vermerkt.

2. **Zustand = zuletzt zugestellter Aufnahme-Zeitpunkt**, je Garten-Kamera in `system_metadata`.
   Er ersetzt den bisherigen Dedup-Schlüssel `Datum|Beschriftung`, der zwei gleichnamige (oder
   zwei namenlose) Zeitpläne kollidieren ließ und deren zweites Guss-Foto des Tages verschluckte.
   Der Zeitstempel ist eindeutig; die Kollision entfällt.

   Verglichen wird **„jünger als der zuletzt zugestellte"**, nicht „ungleich". Ändert der Benutzer
   seine Fotozeiten, kann ein längst bedienter, älterer Aufnahme-Zeitpunkt wieder der jüngste
   fällige werden — bei einem Ungleich-Vergleich würde er ein veraltetes Bild zustellen.

2a. **Ein gescheiterter Versand öffnet den Aufnahme-Zeitpunkt wieder.** Der Vermerk wird beim
   Empfang gesetzt (sonst sendete jeder weitere Upload dasselbe Foto erneut). Scheitert der
   Telegram-Versand, meldet die UI das über `TimedPhotoDeliveryFailed`; der `DatabaseLoggerAdapter`
   setzt den Vermerk auf eine Sekunde **vor** den Zeitpunkt zurück — nicht auf leer: Der Zeitpunkt
   ist damit wieder offen, der Anker der Kamera-Überwachung (ADR 0041, Punkt 6a) bleibt aber
   erhalten. Der nächste Upload erfüllt den Zeitpunkt erneut. Ohne diesen
   Rückweg wäre das Bild endgültig verloren — der `EventBus` verschluckt Ausnahmen seiner
   Abonnenten, der Fehlschlag bliebe also unsichtbar. Das wäre exakt der stille Verlust, den
   dieser ADR beseitigt.

2b. **Nur Guss-Zeitpläne erzeugen Guss-Fotos.** Ein Nebel-Intervall (ADR 0033) liegt in derselben
   Tabelle wie die Bewässerungs-Zeitpläne, ist aber kein Guss. Ohne Filter auf `mode='watering'`
   erzeugt es einen Aufnahme-Zeitpunkt „Nach dem Guss …", der unter der Erfüllungs-Regel
   **zuverlässig** zugestellt würde (unter dem alten Toleranzfenster fiel er meist durch) — und der
   zudem einen echten Aufnahme-Zeitpunkt ablöst, dessen Bild dadurch nie ankäme.

3. **Ein Upload *vor* dem Aufnahme-Zeitpunkt erfüllt ihn nicht.** Die Garten-Kamera wacht bis zu
   60 s zu früh auf (Quantisierung des RTC-Countdowns) und nach einem Fehlversuch mitunter
   deutlich früher; ein Bild vor dem Zeitpunkt kann den Nach-Offset des Guss-Fotos unterlaufen und
   das Beet mitten im Guss zeigen. Die Kamera wacht in diesem Fall ohnehin kurz darauf erneut auf
   (`compute_next_sleep_seconds` gibt ihr die Restzeit) und erfüllt den Zeitpunkt dann.

4. **Die Bildunterschrift nennt den Aufnahme-Verzug, sobald er die Hinweis-Schwelle
   überschreitet** (`AUFNAHME_ABWEICHUNG_HINWEIS_MINUTEN`, Default 5):
   `📷 Foto um 08:00 · aufgenommen 08:28`. Darunter bleibt sie unverändert. Der Aufnahme-Zeitpunkt
   ist der **Anlass**, die Aufnahmezeit die **Tatsache**; fallen sie zusammen, ist die Tatsache
   redundant, weichen sie ab, ist sie die wichtigste Information am Bild. Das ergänzt ADR 0036,
   das die *Guss-Startzeit* aus der Unterschrift entfernte, weil sie irreführte — hier kommt keine
   irreführende Zeit zurück, sondern die wahre.

5. **`TIMED_PHOTO_TOLERANCE_MINUTES` entfällt.** Der Wert entschied bisher über die Zustellung; er
   entscheidet künftig nur noch über die Anzeige und heißt deshalb
   `AUFNAHME_ABWEICHUNG_HINWEIS_MINUTEN`. Ein Konfigurationswert, der seine Bedeutung ändert, aber
   seinen Namen behält, ist eine Falle für den nächsten Leser.

6. **Der erste Upload nach Einführung** wird zugestellt (es gibt noch keinen „zuletzt
   zugestellten" Zeitpunkt). Ein einzelnes, korrekt beschriftetes Foto ist kein Schaden — still
   zu verschlucken wäre genau der Fehler, den dieser ADR behebt.

Die Erfüllungs-Prüfung ist eine reine Funktion in `core/camera_schedule.py`; der Zustand liegt in
`system_metadata`, der `camera_receiver` bleibt zustandslos (ADR 0014).

## Konsequenzen

- **Kein Bild geht mehr verloren.** Jeder Aufnahme-Zeitpunkt wird bedient, sobald die Garten-Kamera
  sich meldet — unabhängig davon, wie pünktlich sie ist.
- **Ein spätes Bild kann alt sein.** Wacht die Kamera erst Stunden später auf, wird ein
  Nachmittagsbild als das 08:00-Foto zugestellt. Die Bildunterschrift macht das sichtbar
  (Punkt 4), und die Kamera-Überwachung meldet den Verzug (ADR 0041) — die Zustellung schweigt
  nicht mehr über ihre eigene Unschärfe.
- **Der stille Verlust war bisher ein Störungsmelder.** Dass die Fotos ausblieben, hat den Bug
  überhaupt erst sichtbar gemacht. Diese Warnfunktion darf nicht verloren gehen — sie wird von
  einem Nebeneffekt zu einer Absicht (ADR 0041).
- Die Dedup-Kollision gleichnamiger Zeitpläne verschwindet ersatzlos mit.
