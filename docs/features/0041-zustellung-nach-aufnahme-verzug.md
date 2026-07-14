# Feature: Zustellung nach Aufnahme-Verzug statt Toleranzfenster

## Problemstellung (Problem Statement)

Die Garten-Kamera nimmt ihre Fotos auf, lädt sie hoch — und der Benutzer bekommt sie
trotzdem nicht. Die Bilder liegen auf der Steuerzentrale und sind über „Foto anzeigen"
sichtbar, aber der Telegram-Bot stellt sie nicht zu.

Grund: Der Kamera-Empfänger stellt ein Bild nur zu, wenn es **innerhalb von ±5 Minuten** um
einen Aufnahme-Zeitpunkt eintrifft (`find_matching_photo_target`,
`TIMED_PHOTO_TOLERANCE_MINUTES`). Trifft es das Fenster nicht, wird es **stillschweigend
verworfen** — keine Zustellung, keine Meldung, kein Logeintrag.

Messung über drei Betriebstage (12.–14.07.2026; Feste Fotozeiten 08:00 und 20:00, Guss-Foto
„Abends" um 22:22):

| Aufnahme-Zeitpunkt | Bild traf ein | Aufnahme-Verzug | zugestellt? |
|---|---|---|---|
| 12.07. 20:00 | 21:07:21 | +67 min | nein |
| 13.07. 08:00 | 08:28:59 | +29 min | nein |
| 13.07. 20:00 | 20:15:50 | +16 min | nein |
| 13.07. 22:22 | 22:24:37 | +2,6 min | ja |
| 14.07. 08:00 | 08:10:15 | +10 min | nein |
| 14.07. 20:00 | 19:59:09 / 20:00:14 | pünktlich | ja |

**2 von 7 Aufnahme-Zeitpunkten wurden zugestellt.** Der Rest fiel aus dem Fenster.

Die Ursache liegt in der Garten-Kamera (Feature 0005 im Kamera-Repository): Sie wacht
pünktlich auf, aber einzelne Zyklen scheitern, und jeder gescheiterte Zyklus schiebt den
Upload um einen Backoff-Schlaf nach hinten. Die Steuerzentrale verlangt eine
Minutengenauigkeit, die ein batteriebetriebenes Gerät ohne Uhr prinzipiell nicht liefern
kann — `CONTEXT.md` sagt seit jeher, das Aufwachen „nähert sich an".

## Lösung (Solution)

Ein Aufnahme-Zeitpunkt wird vom **ersten Bild erfüllt, das nach ihm eintrifft**. Er bleibt
offen, bis der nächste Aufnahme-Zeitpunkt ihn ablöst. Damit geht kein Bild mehr verloren —
unabhängig davon, wie pünktlich die Garten-Kamera ist.

Weicht die Aufnahmezeit um mehr als die Hinweis-Schwelle (Default 5 min) vom
Aufnahme-Zeitpunkt ab, nennt die Bildunterschrift sie ausdrücklich:

- `📷 Foto um 08:00 · aufgenommen 08:28`
- `📷 Nach dem Guss „Abends" · aufgenommen 22:24`

Der Aufnahme-Zeitpunkt ist der **Anlass**, die Aufnahmezeit die **Tatsache**. Fallen sie
zusammen, bleibt die Unterschrift wie bisher.

Siehe ADR 0040.

## User Stories

**Als Benutzer möchte ich mein Guss-Foto auch dann bekommen, wenn die Garten-Kamera ein paar
Minuten zu spät dran war**, damit ich nicht ohne Bild dastehe, obwohl das Bild existiert.

**Als Benutzer möchte ich sehen, wann ein Foto tatsächlich entstanden ist**, wenn es
deutlich später als geplant aufgenommen wurde, damit ich es richtig einordne und nicht ein
Nachmittagsbild für das Morgenbild halte.

**Als Benutzer möchte ich pro Aufnahme-Zeitpunkt genau ein Foto bekommen** — auch wenn die
Garten-Kamera kurz vor und kurz nach dem Zeitpunkt aufwacht und zwei Bilder schickt.

## Implementierungs-Entscheidungen (Implementation Decisions)

1. **Neue reine Funktion in `core/camera_schedule.py`:**
   `faelliger_aufnahme_zeitpunkt(now, schedules, photo_times, after_offset_minutes)` liefert
   den **jüngsten bereits fälligen** Aufnahme-Zeitpunkt als `(target_dt, caption, label)` oder
   `None`. Schwesterfunktion zu `next_photo_target`. Keine I/O.

2. **`find_matching_photo_target` entfällt** — samt Toleranzfenster.

3. **Zustand: zuletzt zugestellter Aufnahme-Zeitpunkt**, je Kamera in `system_metadata`
   (`last_delivered_target:<mac>`, ISO-Zeitstempel). Er ersetzt den Dedup-Schlüssel
   `Datum|Beschriftung`, der zwei gleichnamige oder zwei namenlose Zeitpläne kollidieren ließ
   (zweites Guss-Foto des Tages wurde als Dublette verschluckt). Der `camera_receiver` bleibt
   zustandslos (ADR 0014).

4. **Zustellregel im `camera_receiver`:** Ist der fällige Aufnahme-Zeitpunkt ein anderer als
   der zuletzt zugestellte → `TimedPhotoCaptured` veröffentlichen und Zeitstempel merken.
   Ein Upload **vor** dem Zeitpunkt erfüllt ihn nicht (die Kamera wacht bis zu 60 s zu früh
   auf; ein Bild vor dem Nach-Offset kann das Beet mitten im Guss zeigen).

5. **`TimedPhotoCaptured` trägt Aufnahme-Zeitpunkt und Aufnahmezeit** mit, damit `telegram_ui`
   die Bildunterschrift bauen und der Watchdog den Verzug bewerten kann (Feature 0040).

6. **Konfiguration:** `TIMED_PHOTO_TOLERANCE_MINUTES` → `AUFNAHME_ABWEICHUNG_HINWEIS_MINUTEN`
   (Default 5). Der Wert entscheidet nicht mehr über die Zustellung, sondern nur noch über die
   Anzeige — ein Name, der seine Bedeutung stillschweigend ändert, ist eine Falle.

7. **Erster Upload nach Einführung** wird zugestellt (es gibt noch keinen „zuletzt
   zugestellten" Zeitpunkt).

8. **`docs/design/telegram-nachrichten.html`** wird für die erweiterte Bildunterschrift
   aktualisiert (`.claude/rules/telegram_messages.md`).

## Test-Entscheidungen (Testing Decisions)

- `tests/core/test_camera_schedule.py`: `faelliger_aufnahme_zeitpunkt` — kein Zeitpunkt fällig,
  genau einer fällig, mehrerer fällig (jüngster gewinnt), Tageswechsel, Guss + feste Fotozeit
  gemischt, inaktiver Zeitplan wird ignoriert.
- `tests/adapters/test_camera_receiver.py`:
  - Upload 28 min nach Zeitpunkt → **wird zugestellt** (der Regressionstest für diesen Bug).
  - Upload vor dem Zeitpunkt → nicht zugestellt.
  - Zwei Uploads nach demselben Zeitpunkt → genau ein `TimedPhotoCaptured`.
  - Zwei **namenlose** Zeitpläne am selben Tag → **zwei** Zustellungen (alte Dedup-Kollision).
  - Zwei Kameras → je eine Zustellung.
- `tests/ui/test_photo_times.py`: Bildunterschrift mit und ohne Verzugs-Hinweis (Schwelle).

## Nicht im Leistungsumfang (Out of Scope)

- Die **Warnung** bei zu großem oder unendlichem Verzug — das ist Feature 0040 (ADR 0041).
- Die **Ursache** der verspäteten Uploads — das ist Feature 0005 im Kamera-Repository. Dieses
  Feature macht die Steuerzentrale robust gegen Unpünktlichkeit; es macht die Kamera nicht
  pünktlich.

## Weitere Anmerkungen (Further Notes)

Der stille Verlust war bisher der einzige Störungsmelder: Dass die Fotos ausblieben, hat den
Bug überhaupt erst sichtbar gemacht. Wird die Zustellung robust, verschwindet dieses Signal —
deshalb ist Feature 0040 (Verzugs-Warnung) die **notwendige** Ergänzung und nicht optional.
Ohne sie würde eine kranke Kamera künftig unbemerkt leise vor sich hin leiden.
