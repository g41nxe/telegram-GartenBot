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

2. **Tatsache und Bewertung getrennt.** Der `camera_receiver` ermittelt beim Upload den
   **Aufnahme-Zeitpunkt und die Aufnahmezeit** (er braucht beide ohnehin für die Bildunterschrift)
   und trägt sie im Ereignis `TimedPhotoCaptured` mit. Der Watchdog abonniert es und **bewertet**:
   Schwelle, Zähler, Alarm, Entwarnung. Policy im Watchdog, Tatsachen im Adapter.

   Der Verzug wird bewusst **nicht** persistiert: Er ist aus dem Ereignis ableitbar, und der einzige
   Zustand, der ihn überdauern muss, ist der Zähler — nicht die Zahl.

3. **Verzugs-Schwelle: 15 Minuten.** Gesund liegt der Verzug unter einer Minute (±60 s
   Wecker-Quantisierung plus Bootzeit). 15 Minuten liegen weit über dem Rauschen und weit unter
   dem beobachteten Störungsbild — jeder der gemessenen Ausfälle hätte gefeuert.

4. **Alarm erst beim zweiten Verzug in Folge.** Ein einzelner WLAN-Wackler soll nicht nachts
   melden; ein echtes Problem meldet sich am nächsten Aufnahme-Zeitpunkt ohnehin wieder.

5. **Entwarnung**, sobald ein Aufnahme-Zeitpunkt wieder innerhalb der Schwelle erfüllt wird —
   sofort über den Ereignis-Kanal, analog zu Ventil, Kamera und Regensensor (ADR 0018, Punkt 3).

6. **Ein verpasster Aufnahme-Zeitpunkt ist kein „maximaler Verzug", sondern eine eigene
   Tatsache.** Wird ein Aufnahme-Zeitpunkt von seinem Nachfolger abgelöst, ohne je ein Bild
   erhalten zu haben, gibt es **kein Bild** — also auch keine Aufnahmezeit und keinen messbaren
   Verzug. Jede Minutenangabe dafür wäre erfunden, und eine erfundene Zahl kann unter die Schwelle
   rutschen: Ein Zeitpunkt ganz ohne Bild würde dann als „pünktlich" gelten und einen laufenden
   Alarm sogar entwarnen. Die Bewertung nimmt deshalb die **Tatsache** entgegen (`gestört: bool`),
   nicht eine Zahl, aus der sie erst geschlossen werden müsste.

   Beide Gründe zahlen auf **denselben** Zähler und dasselbe Flag ein (zwei Störungen in Folge →
   melden; ein Wechsel der Art zählt mit), aber die **Nachricht folgt der Tatsache**:

   | Grund | Was vorliegt | Was der Nutzer tun soll |
   |---|---|---|
   | `verzug` | Die Kamera **war da**, aber zu spät | WLAN/Akku prüfen |
   | `verpasst` | Die Kamera war über das ganze Fenster **stumm** | Nachsehen, ob sie noch läuft |

   Denn ein verpasster Zeitpunkt heißt zwingend, dass **kein einziger Upload** in seinem Fenster
   eintraf — jeder hätte ihn erfüllt. Von „28 Minuten zu spät" zu sprechen, wo gar nichts geliefert
   wurde, schickt den Nutzer auf die falsche Fährte. Damit ist **Feature 0040** vollständig
   abgedeckt; es braucht keinen eigenen Mechanismus.

6a. **Der Anker der Überwachung darf nicht zerstört werden.** `last_delivered_target:<mac>`
   beantwortet zwei Fragen: „Was ist bedient?" (Empfänger) und „Ab wo suche ich nach verpassten
   Zeitpunkten?" (Überwachung). Bei einem gescheiterten Versand (ADR 0040, Punkt 2a) wird der
   Schlüssel deshalb **nicht geleert**, sondern auf eine Sekunde **vor** den Zeitpunkt gesetzt: Der
   Zeitpunkt ist damit wieder offen, der Anker bleibt aber eine echte Zeit. Ein geleerter Schlüssel
   bedeutet „ich weiß nichts" — und dann meldet die Überwachung bewusst nichts (Neustart-Schutz).
   Fielen erst Telegram und dann die Kamera aus, schwiege sie sonst ausgerechnet dann.

7. **Sichtbarkeit im Tagesbericht** analog ADR 0018, Punkt 5: Solange der Alarm aktiv ist,
   erscheint eine Störungszeile und der Bericht gilt nicht mehr als grün. **Die Inaktivität hat
   dabei Vorrang** (Punkt 5): Eine stumme Kamera trifft ihre Aufnahme-Zeitpunkte selbstverständlich
   nicht — die mildere Diagnose würde hier nur in die Irre führen.

   **Abweichung von der ursprünglichen Fassung:** Dort war der **durchschnittliche** Aufnahme-Verzug
   des Tages vorgesehen. Dafür bräuchte es eine Verzugs-Historie — eine neue Tabelle, die es nicht
   gibt. Der Zustand („trifft die Zeitpunkte nicht mehr") trägt die Entscheidung, die der Nutzer
   treffen muss, genauso gut; die Zahl wäre Zierrat. Eine Historie lohnt erst, wenn wir Trends
   auswerten wollen — dann als eigenes Feature, nicht als Beifang.

## Konsequenzen

- Eine Garten-Kamera, die ihre Aufnahme-Zeitpunkte verfehlt, meldet sich **selbst**, statt sich
  hinter zugestellten Fotos zu verstecken.
- Der Verzug ist der beste verfügbare Frühindikator für Funkloch, schwachen Akku oder scheiternde
  Zyklen — Zustände, die die Steuerzentrale sonst nicht sehen kann, weil gescheiterte Zyklen sie
  nie erreichen.
- Feature 0040 wird nicht separat implementiert, sondern als Grenzfall dieser Alarmklasse.
- Kein Schema-Eingriff: Der Zustand (Zähler, Flag, Anker) liegt in `system_metadata`, wie bei den
  drei bestehenden Alarmen.
