# Umsetzungsplan — Regenereignis mit Karenzzeit (ADR 0043, Ticket ctm)

Behebt das Melde-Flattern: statt ~50 Meldungen für ~9 Schauer soll jeder Schauer genau
**ein** Paar erzeugen. Vorgehen je Schritt: **roter Test zuerst → minimal grün → Refactor →
committen**. Domänenbegriffe: `CONTEXT.md` (*Regen-Messung*, *Regenereignis*, *Karenzzeit*).

---

## Schritt 1 — Kern: Regenereignis-Zustandslogik (pure)

**Ziel:** Aus (Zustand, Messung, Zeit) werden Zustandsübergänge — ohne I/O, ohne Datenbank.

- **Implementieren:** `core/rain_event.py` mit `RainEventState` (aktiv, Startzeit, letzter Kipp,
  Summe) und einer puren Funktion `advance(state, rainlevel_mm, now, grace_minutes)
  -> (neuer Zustand, ausgelöste Ereignisse)`.
- **Test:** erster Kipp → *gestartet*; Lücke < Karenzzeit → **kein** Ende; Lücke ≥ Karenzzeit →
  *beendet* mit korrekter Gesamtmenge und Dauer (letzter Kipp − erster Kipp);
  Kipp während laufendem Ereignis → nur Summe/letzter Kipp wachsen.
- **Krönung:** die **echte Niesel-Serie vom 06.07.** als Testfall → genau **ein** Paar
  statt neun.

## Schritt 2 — Ereignisse auf dem Ereignis-Kanal

**Ziel:** Die Übergänge sind für Abonnenten sichtbar.

- **Implementieren:** `RainEventStarted` und `RainEventEnded(total_mm, duration_minutes)`
  in `core/sensor_events.py` (englische Klassennamen wie im Bestand).
- **Test:** Kern liefert die Ereignisse mit den erwarteten Feldern.

## Schritt 3 — Adapter: Zustand persistieren, Ereignisse publizieren

**Ziel:** Der Zustand überlebt den Neustart des Bewässerungs-Daemons.

- **Implementieren:** Adapter abonniert `RainSensorMeasured`, lädt den Zustand aus
  `system_metadata`, ruft den Kern, speichert den Zustand, publiziert die Ereignisse.
  Neuer Config-Wert `RAIN_EVENT_GRACE_MINUTES` (Default 45) in `config.py` + `garden.conf`.
- **Test:** Zustand überlebt einen simulierten Neustart (Laden/Speichern round-trip);
  nach Neustart mitten im Regen **kein** doppeltes „gestartet".

## Schritt 4 — UI: Meldungen umstellen

**Ziel:** Die Benachrichtigungen hängen am Ereignis, nicht mehr an der Messung.

- **Implementieren:** `telegram_ui` abonniert `RainEventStarted`/`RainEventEnded`; die alte
  Flag-Logik in `_on_rain_sensor_measured` entfällt. Texte:
  `🌧 *Regen erkannt*` (ohne Menge) und `🌤 *Regen vorbei* — insgesamt X mm in Y`
  (Dauer entfällt bei nur einem Kipp).
- **Test:** Formatierung beider Meldungen inkl. Kurz-Regel.
- **Pflicht:** `docs/design/telegram-nachrichten.html` nachziehen (Regel `telegram_messages.md`).

## Schritt 5 — Beobachtbarkeit

**Ziel:** Das Verhalten ist künftig aus dem Journal prüfbar.

- **Implementieren:** `broadcast_notification` loggt den Meldungstext (`logger.info`).
- **Sichtbar:** Nach dem nächsten Regen zeigt das Journal die Meldungen direkt.

## Schritt 6 — Verifikation

- Die **echten Sensordaten** (1958 Messungen) durch die neue Logik spielen →
  erwartet ~24 statt 50 Meldungen, kein Paar unter der Karenzzeit.
- Volle Testsuite grün, Coverage nicht regressiert (`scripts/run_coverage.ps1`).

---

**Nicht im Umfang:** Die Guss-Steuerung bleibt unverändert auf der rohen `RainSensorMeasured`
(sie soll beim ersten Kipp unterbrechen — ADR 0043). Ebenso unverändert: Sensor-Parsing,
Ticks, Batterie, Tagesbericht und `/status`.
