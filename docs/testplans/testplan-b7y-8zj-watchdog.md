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

- [ ] Gegen **16:43** trifft die Telegram-Meldung ein:
      **„⚠️ Verbindung verloren: Ventil ‚Links Sprenger' hat seit 1.x Stunden kein Signal
      gesendet."**
- [ ] Die genannte Dauer liegt bei rund **1,6 Stunden** — nicht bei 24.
- [ ] `journalctl` zeigt die zugehörige Zeile mit Schwellenangabe:
      „Watchdog-Alert: Ventil ‚Links Sprenger' seit 1.6h still (Schwelle 1.0h)."
- [ ] `/status` weist danach **beide** Ventile rot aus.
- [ ] Batterie wieder einsetzen → Entwarnung
      **„🟢 Verbindung wiederhergestellt"**, `/status` für „Links Sprenger" wieder grün.

---

## Ergebnis

_(nach der Abnahme ausfüllen)_

**Datum:**
**Ergebnis:**
**Abweichungen:**
