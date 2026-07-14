# 41. Aufnahme-Verzug als zweite Alarmklasse der Kamera-Überwachung

Die Kamera-Überwachung bekommt neben der **Inaktivität** eine zweite Alarmklasse: den
**Aufnahme-Verzug**. Sie meldet damit auch eine Garten-Kamera, die zwar Bilder liefert, ihre
Aufnahme-Zeitpunkte aber nicht mehr trifft. Feature 0040 („Warnung bei ausgebliebener getimter
Aufnahme") geht darin auf.

Erweitert ADR 0018.

## Kontext

Mit ADR 0040 geht kein Bild mehr verloren — auch ein 30 Minuten verspätetes wird zugestellt. Das
behebt den Datenverlust, schafft aber ein neues Risiko: **Die Störung wird unsichtbar.**

Genau diese Störung lag drei Tage lang vor (Uploads 2–34 min nach ihrem Aufnahme-Zeitpunkt), und
der bestehende Watchdog hat sie nicht gesehen — er konnte es nicht: Er prüft `cameras.last_seen`
gegen ein Timeout von `3 × Schlafintervall`, und dieser Wert war durchgehend frisch. Die Kamera
war ja quicklebendig. Bemerkt wurde der Fehler nur, weil die Fotos ausblieben — also durch einen
*anderen* Bug. Diese Warnfunktion war ein Zufall; sie soll eine Absicht werden.

Verworfene Alternative — **Meldung im `camera_receiver`**: Der Verzug ist dort exakt bekannt (er
wird für die Bildunterschrift ohnehin berechnet). ADR 0018 hat jedoch bereits entschieden, keine
**Alarm-Logik in einen Transport-Adapter** zu legen (dort: MQTT-Adapter). Für den
Kamera-Empfänger gilt dasselbe.

## Entscheidung

1. **Zwei Alarmklassen, ein Modul.** `adapters/watchdog.py` überwacht die Garten-Kamera künftig
   auf:

   | Klasse | Frage | Datenquelle |
   |---|---|---|
   | Inaktivität (bestehend) | Kommt überhaupt noch ein Bild? | `cameras.last_seen` |
   | Aufnahme-Verzug (neu) | Trifft sie ihre Aufnahme-Zeitpunkte? | Verzug des letzten erfüllten Aufnahme-Zeitpunkts |

2. **Tatsache und Bewertung getrennt.** Der `camera_receiver` ermittelt beim Upload den **Verzug**
   (Aufnahmezeit − Aufnahme-Zeitpunkt) und schreibt ihn in die `cameras`-Zeile — dort, wo er auch
   `last_seen` und `battery` fortschreibt. Der Watchdog **bewertet** ihn: Schwelle, Alarm,
   Entwarnung. Policy im Watchdog, Tatsachen im Adapter.

3. **Verzugs-Schwelle: 15 Minuten.** Gesund liegt der Verzug unter einer Minute (±60 s
   Wecker-Quantisierung plus Bootzeit). 15 Minuten liegen weit über dem Rauschen und weit unter
   dem beobachteten Störungsbild — jeder der gemessenen Ausfälle hätte gefeuert.

4. **Alarm erst beim zweiten Verzug in Folge.** Ein einzelner WLAN-Wackler soll nicht nachts
   melden; ein echtes Problem meldet sich am nächsten Aufnahme-Zeitpunkt ohnehin wieder.

5. **Entwarnung**, sobald ein Aufnahme-Zeitpunkt wieder innerhalb der Schwelle erfüllt wird —
   sofort über den Ereignis-Kanal, analog zu Ventil, Kamera und Regensensor (ADR 0018, Punkt 3).

6. **Ein nicht erfüllter Aufnahme-Zeitpunkt ist der Grenzfall.** Wird ein Aufnahme-Zeitpunkt von
   seinem Nachfolger abgelöst, ohne je ein Bild erhalten zu haben, gilt er als maximal verzögert
   und löst dieselbe Warnung aus. Damit ist **Feature 0040** vollständig abgedeckt; es braucht
   keinen eigenen Mechanismus.

7. **Sichtbarkeit im Tagesbericht** analog ADR 0018, Punkt 5: Der durchschnittliche Aufnahme-Verzug
   des Tages wird ausgewiesen. Er ist der Frühindikator — er steigt, lange bevor Bilder ganz
   ausbleiben.

## Konsequenzen

- Eine Garten-Kamera, die ihre Aufnahme-Zeitpunkte verfehlt, meldet sich **selbst**, statt sich
  hinter zugestellten Fotos zu verstecken.
- Der Verzug ist der beste verfügbare Frühindikator für Funkloch, schwachen Akku oder scheiternde
  Zyklen — Zustände, die die Steuerzentrale sonst nicht sehen kann, weil gescheiterte Zyklen sie
  nie erreichen.
- Feature 0040 wird nicht separat implementiert, sondern als Grenzfall dieser Alarmklasse.
- Die `cameras`-Tabelle bekommt eine Spalte für den letzten Verzug (Migration via
  `ALTER TABLE` in `init_db()`, wie im Projekt üblich).
