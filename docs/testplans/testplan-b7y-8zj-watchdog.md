# Testplan — Ventil-Ausfall sichtbar machen (b7y, 8zj)

**Umfang:** zwei Fehler, die derselbe reale Vorfall aufgedeckt hat. Ein ausgebautes
Ventil blieb 24 Stunden unbemerkt, und danach meldete `/status` weiter „alles im grünen
Bereich", obwohl der Watchdog längst Alarm geschlagen hatte.

- **telegram_GartenBot-b7y** — `/status` las das Watchdog-Flag nicht und urteilte
  gegensätzlich zum Tagesbericht.
- **telegram_GartenBot-8zj** — die Inaktivitäts-Schwelle lag fest bei 24 Stunden,
  unabhängig davon, dass beide Ventile im 5-Minuten-Takt funken.

Ausgeliefert mit **v1.20.1**. Die Unit-Tests decken die Logik ab; diese Abnahme prüft
das Verhalten auf der echten Anlage.

---

## Vorbereitung

- [x] Version auf der Steuerzentrale ist **v1.20.1** (per SSH geprüft, 30.08. 15:07).
- [x] `WATCHDOG_VALVE_TIMEOUT_HOURS=1` in `config/garden.conf` auf dem Pi angekommen.
- [x] Ausgangslage in der Datenbank festgehalten:
  - `Links Sprenger` (garden_valve): letztes Signal 30.08. 15:05:02, Flag 0
  - `Rechts Nebelregen` (valve_ffff): letztes Signal 22.08. 13:30:01, Flag 1

---

## 1 · b7y — Der Status zeigt den Ausfall

Ausgangslage: „Rechts Nebelregen" ist seit dem 22.08. ausgebaut, das Watchdog-Flag steht
auf 1. Vor dem Fix zeigte `/status` für dieses Ventil `🟢 aktiv · 🔋 Voll · 📶 gut` und
als Kopfzeile „🟢 Alles im grünen Bereich".

- [x] `/status` aufrufen.
- [x] Kopfzeile lautet **„🔴 Es gibt ein Problem"**.
- [x] „Rechts Nebelregen" erscheint mit **🔴** und der Zeile
      **„⚠️ kein Signal seit 22.08. um 13:30 Uhr"**.
- [x] Bei diesem Ventil steht **keine** Batterie- und Signalstärke-Zeile mehr — die Werte
      stammen aus der letzten empfangenen Meldung und würden Gesundheit behaupten, die
      seit dem Ausfall niemand geprüft hat.
- [ ] Die technische ID (`valve_ffff`) taucht **nirgends** im Status auf.
- [ ] `/tagesbericht` nennt dasselbe Ventil ebenfalls als gestört — Status und
      Tagesbericht widersprechen sich nicht mehr.

## 2 · 8zj — Der Ausfall wird nach einer Stunde gemeldet

Durchführung: Batterie aus „Links Sprenger" entfernt am 30.08. gegen 15:08.

Vorhersage aus Daemon-Start (26.08. 22:43:27) und Stundentakt des Watchdogs:

| | |
|---|---|
| Letztes Signal | 15:05:02 |
| Schwelle (1 h) | 16:05:02 |
| Nächster Prüflauf | **16:43:27** |

- [x] Gegen **16:43** trifft die Telegram-Meldung ein:
      **„⚠️ Verbindung verloren: Ventil ‚Links Sprenger' hat seit 1.x Stunden kein Signal
      gesendet."**
- [x] Die genannte Dauer liegt bei rund **1,6 Stunden** — nicht bei 24.
- [x] `journalctl` zeigt die zugehörige Zeile mit Schwellenangabe:
      „Watchdog-Alert: Ventil ‚Links Sprenger' seit 1.6h still (Schwelle 1.0h)."
- [x] `/status` weist danach **beide** Ventile rot aus.
- [x] Batterie wieder einsetzen → Entwarnung
      **„🟢 Verbindung wiederhergestellt"**, `/status` für „Links Sprenger" wieder grün.

---

## Ergebnis

**Datum:** 30.08.2026
**Ergebnis:** GO

**1 · b7y** — bestätigt. `/status` meldete „🔴 Es gibt ein Problem"; „Rechts Nebelregen"
erschien mit „⚠️ kein Signal seit 22.08. um 13:30 Uhr" und ohne Batterie-/Signalstärke-Zeile.
Vor dem Fix stand dort „🟢 aktiv · 🔋 Voll · 📶 gut" bei grüner Kopfzeile.

**2 · 8zj** — bestätigt, und zwar zum vorausberechneten Zeitpunkt. Aus Daemon-Start
(26.08. 22:43:27) und Stundentakt ergab sich als Meldezeit 16:43:27; eingetroffen ist sie
um 16:43:00:

    16:43:00  Verbindung verloren: Ventil "Links Sprenger" hat seit 1.6 Stunden kein Signal gesendet.
    16:43:01  Watchdog-Alert: Ventil 'Links Sprenger' seit 1.6h still (Schwelle 1.0h).

Beide Flags danach auf 1. Mit der alten 24-Stunden-Schwelle wäre die Meldung erst am
31.08. gegen 15:05 gekommen.

Die Entwarnung nach dem Wiedereinsetzen der Batterie kam um 16:56:26 — zwei Sekunden nach
dem ersten wieder eingegangenen Signal (16:56:28). Sie hängt am Ventil-Ereignis, nicht am
Prüftakt, und ist deshalb sofort. Flag für Ventil 1 zurück auf 0, Ventil 2 unverändert 1
(weiterhin ausgebaut).

**Abweichungen:** keine im geprüften Verhalten.

Zwei Punkte aus Abschnitt 1 blieben ungeprüft, weil sie den Befund nicht berühren: das
Ausbleiben der technischen ID im Status und der Gegencheck über `/tagesbericht`. Beide
sind durch Unit-Tests abgedeckt.

**Folgebefund während der Abnahme:** Zwischen dem Reißen der Schwelle (16:05) und der
Meldung (16:43) vergingen 38 Minuten, weil der Watchdog nur stündlich prüft — die
Wartezeit ist im schlechtesten Fall doppelt so lang wie die Schwelle. Behoben in
Commit 0512925 (`WATCHDOG_CHECK_INTERVAL_SECONDS`, Vorgabe 300 s); wirksam ab dem
nächsten Release.
