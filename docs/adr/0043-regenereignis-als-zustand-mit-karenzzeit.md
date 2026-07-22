# 43. Regenereignis als Zustand mit Karenzzeit

Wir trennen die **Regen-Messung** (eine einzelne Sensormeldung) vom **Regenereignis**
(dem zusammenhängenden Schauer). Das Ereignis ist ein Zustand mit einer **Karenzzeit**:
es endet erst, wenn eine Weile kein Regen mehr angekommen ist. Benachrichtigungen hängen
am Ereignis, die Guss-Unterbrechung weiterhin an der Messung.

## Kontext

Der Regensensor ist eine **Regenwippe**: sie kippt pro 0,5 mm und meldet die Kipps als
`rainlevel` (Zuwachs seit der letzten Meldung). Daraus wurde bisher direkt
`is_raining = rainlevel_mm >= RAIN_SENSOR_THRESHOLD_MM` gebildet — also *„kam in dieser
einen Meldung Regen an?"*. Die Benachrichtigung hing an der Flanke dieses Wertes.

Bei leichtem Regen liegen die Kipps jedoch **weiter auseinander als das Melde-Intervall**
(Median ~13,5 Min). Jede Meldung ohne Kipp kippte den Zustand sofort auf „kein Regen" —
und der nächste Kipp wieder zurück. Ergebnis: Melde-Flattern.

Nachgespielt an echten Sensordaten (1958 Messungen, 28.06.–17.07.2026) hätte die
bisherige Logik **50 Meldungen für real ~9 Regenereignisse** ausgelöst; am 06.07. neun
„erkannt/vorbei"-Paare an einem einzigen Nieselnachmittag, teils **1 Minute** auseinander.

Die eigentliche Ursache ist begrifflich: *Messung* und *Ereignis* wurden vermischt. Beide
Konsumenten brauchen Unterschiedliches — die **Guss-Steuerung** will beim ersten Kipp
sofort unterbrechen, die **Benachrichtigung** will den Zustand über den Schauer hinweg.

## Entscheidung

- **Regenereignis als Zustand im `core`.** Eine pure Funktion bildet
  (Zustand + Messung + Zeit) → (neuer Zustand + Ereignisse). Kein I/O, mit echten
  Sensordaten direkt testbar.

- **Karenzzeit 45 Minuten**, konfigurierbar in `config/garden.conf` (nicht-geheim, ADR 0030).
  Das Ereignis endet erst, wenn seit dem letzten Kipp so lange nichts mehr kam. Begründung
  aus den Daten: bei ~13,5 Min Melde-Intervall entspricht das **drei ausgefallenen Meldungen**;
  die Simulation ergibt 50 → 24 Meldungen. Kürzer (30 Min) lässt spürbar Lärm stehen, länger
  (90 Min) halbiert ihn nicht noch einmal, verzögert aber die Ende-Meldung um eine weitere
  Dreiviertelstunde.

- **Zwei neue Ereignisse auf dem Ereignis-Kanal:** `RainEventStarted` und `RainEventEnded`
  (letzteres mit **Gesamtmenge** und **Dauer**). Die Telegram-UI abonniert nur noch diese und
  formuliert Text — sie hält keinen Zustand mehr.

- **Der Zustand wird persistiert** (`system_metadata`, neben dem bestehenden Flag):
  Startzeit, Zeitpunkt des letzten Kipps, Summe bisher. Der Bewässerungs-Daemon startet bei
  jedem Release neu; ein Schauer dauert Stunden. Ohne Persistenz gäbe es nach einem Neustart
  ein doppeltes „Regen erkannt" und eine unvollständige Gesamtmenge — ein Rückschritt
  gegenüber heute. Der Kern bleibt pur, ein **Adapter** liest und schreibt den Zustand
  (Muster wie ADR 0042).

- **Die Guss-Steuerung bleibt auf der rohen Messung** (`RainSensorMeasured`). Sie soll beim
  **ersten Kipp** unterbrechen; eine Hysterese wäre dort falsch.

- **Meldungs-Inhalte:**
  - Start: `🌧 *Regen erkannt*` — **ohne** Menge. Die bisherige Zahl war stets die 0,5 mm des
    ersten Kipps, also eine Startmarkierung ohne Aussage über den Schauer.
  - Ende: `🌤 *Regen vorbei* — insgesamt X mm in Y`. **Dauer = letzter Kipp − erster Kipp**;
    die Karenzzeit ist ein Erkennungs-Artefakt und zählt nicht als Regen. Bei nur einem Kipp
    (Dauer 0) entfällt die Dauer und nur die Menge wird gemeldet.

- **Benachrichtigungen werden geloggt.** `broadcast_notification` schreibt den Meldungstext
  ins Journal. Ohne das war dieses Verhalten nicht aus den Logs nachvollziehbar — die Analyse
  musste über die Datenbank rekonstruiert werden.

## Konsequenzen

- Aus ~50 werden ~24 Meldungen; ein Schauer erzeugt genau ein Paar statt bis zu neun.
- Die Ende-Meldung trägt erstmals die **Gesamtmenge** des Ereignisses — die Zahl, die für die
  Gieß-Entscheidung tatsächlich interessant ist.
- Die Ende-Meldung kommt systembedingt **45 Min nach dem letzten Tropfen**; das ist der Preis
  für die Entflatterung und in der gemeldeten Dauer bewusst nicht enthalten.
- Neuer Config-Wert (Karenzzeit) und drei zusätzliche `system_metadata`-Schlüssel.
- Feature 0016 (Regensensor-Integration) wird in seinem Melde-Verhalten abgelöst; die
  Sensor-Anbindung selbst (Parsing, Ticks, Batterie) bleibt unverändert.
