# 35. Regen-Übersteuerung: Guss-Vorwarnung vor regenbedingtem Überspringen

Wir geben dem Nutzer die Möglichkeit, das automatische regenbedingte Überspringen oder
Reduzieren eines **geplanten** Gusses für einen einzelnen Lauf zu **übersteuern**. Dazu sendet
der Bewässerungs-Daemon ~5 Minuten vor dem geplanten Guss-Start eine **Guss-Vorwarnung** — aber
nur, wenn die Gieß-Empfehlung den Guss skippen oder reduzieren würde — mit der Option
**„🚿 Regen ignorieren"**. Wird sie gedrückt, läuft der Guss zu seiner regulären Zeit mit den
Original-Werten, als gäbe es keinen Regen.

## Kontext

Der Scheduler bewertet jeden geplanten Guss über die Gieß-Empfehlung (graduierte Gieß-Steuerung,
ADR 0031) und überspringt oder reduziert ihn bei ausreichendem Regen — **automatisch und
kommentarlos**. Der Nutzer erfährt davon erst über die nachgelagerte `WateringSkipped`-/
`WateringScaled`-Meldung, **nachdem** die Entscheidung gefallen ist. Es gibt keinen Weg, einen
bewusst gewollten Guss trotz Regen-Vorhersage durchzusetzen, ohne die Automatik abzuschalten.

Feature 0018 skizziert zwar einen „Trotzdem gießen"-Button am Skip, aber (a) nur für den
Skip-Fall, (b) vage als „manueller Guss mit Standardwerten" — nicht als exakte Wiederholung des
geplanten Gusses, und (c) erst **nach** dem Skip.

## Entscheidung

- **Vorgelagerte Warnung statt nachträglicher Reaktion.** Die Scheduler-Schleife (1-Minuten-Poll)
  führt bei `now == Startzeit − RAIN_WARNING_LEAD_MINUTES` (Standard 5) je aktivem Zeitplan die
  **bestehende** Wetter-Bewertung aus. Ergibt sie Skip **oder** Reduzierung (Faktor < 1),
  publiziert der Scheduler ein neues Domänen-Event `WateringRainWarning`
  (`schedule_id`, Name, Zeit, Ventile, `duration_original`, `volume_original`, Begründung).
- **Sowohl Skip als auch Reduzierung** lösen die Vorwarnung aus — eine reduzierte Bewässerung ist
  ebenfalls ein regenbedingter Eingriff, den der Nutzer aufheben können soll.
- **Event-getriebene Benachrichtigung.** Die Telegram-UI abonniert `WateringRainWarning` (wie
  `WateringSkipped`/`WateringScaled`) und sendet die **Guss-Vorwarnung** mit Inline-Button
  `rainoverride_{schedule_id}_{datum}`. Der Scheduler ruft die UI nicht direkt (ADR 0008/0017).
- **Übersteuerung als persistentes Flag.** Der Button-Callback setzt ein **System-Metadaten-Flag**
  (`rain_override:{schedule_id}:{datum}`) — analog zu den Watchdog-Flags und damit **neustart-fest**
  innerhalb des 5-Minuten-Fensters. Bewusst **kein** In-Memory-Zustand.
- **Voller Original-Guss bei der Ausführung.** Zur geplanten Zeit liest `_trigger_scheduled_watering`
  das Flag **vor** dem Wetter-Check. Gesetzt → der Guss läuft mit den Original-Werten (Dauer,
  Menge, Ventil(e), Ausführungsmodus), Wetter-Bewertung komplett umgangen; das Flag wird
  **verbraucht** (gelöscht). Nicht gesetzt → regulärer Ablauf.
- **Einmalig pro Lauf.** Die Übersteuerung gilt nur für diese eine Ausführung. Der nächste Lauf
  (z. B. am Folgetag) wird wieder frisch bewertet — kein Dauerzustand, der versehentlich die
  Regen-Logik abschaltet.
- **T−5 nur informativ.** Maßgeblich bleibt die Bewertung zur tatsächlichen Zeit T (außer das Flag
  ist gesetzt). Ändert sich das Wetter in den 5 Minuten, gibt es keine „veraltete" Entscheidung.
- **Zu spät = wirkungslos.** Wird der Button erst nach dem geplanten Lauf gedrückt (Guss bereits
  übersprungen/gelaufen), läuft **nichts** verspätet nach; der Nutzer erhält nur einen sachlichen
  Hinweis. Der Eingriff gilt ausschließlich **vor** dem Lauf.

## Konsequenzen

- Der Nutzer behält bei geplanten Güssen die Kontrolle, ohne die Automatik abschalten zu müssen —
  der Normalfall (kein Eingriff) bleibt unverändert (Skip/Reduzierung greift).
- Neues Event `WateringRainWarning` in `core/scheduler_events.py`; `WateringSkipped` muss um
  `schedule_id` (Zugriff auf Originalwerte/Ventile) erweitert werden — `WateringScaled` trägt die
  Originalwerte bereits.
- Die Wetter-Bewertung läuft pro betroffenem Zeitplan **zweimal** (T−5 für die Warnung, T für die
  Ausführung). Akzeptabel, da rein lesend und günstig; vermeidet veraltete Entscheidungen.
- Die Vorlaufzeit ist über `RAIN_WARNING_LEAD_MINUTES` (Standard 5) konfigurierbar.
- Baustein für Feature 0018: Der „Trotzdem gießen"-Callback und das Vorwarn-Muster werden hier
  konkret und können dort wiederverwendet werden.
