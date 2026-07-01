# Feature: Warnung bei ausgebliebener getimter Aufnahme

## Problemstellung (Problem Statement)

Bleibt ein erwartetes getimtes Foto aus — ein **Guss-Foto** nach einem Zeitplan oder
eine **Feste Fotozeit** —, erfährt der Benutzer das heute **nicht zeitnah**. Wacht die
Garten-Kamera zum Aufnahme-Zeitpunkt nicht auf, kommt sie nicht ins WLAN oder wird ihr
Upload abgewiesen, kommt schlicht kein Bild an — und niemand meldet das.

Der einzige bestehende Sicherungsmechanismus ist die **Kamera-Überwachung** (Erweiterung
des Inaktivitäts-Watchdogs). Sie schlägt aber erst nach einer dynamischen Stille-Grenze von
`max(3 · Sende-Intervall, 3600 s)` an — bei einem großen Sende-Intervall also erst nach
Stunden. Ein konkreter, erwarteter Aufnahme-Zeitpunkt kann so unbemerkt verstreichen: Der
Bot zeigt „Nächstes Foto 22:17" an, das Bild bleibt aus, und der Benutzer bemerkt es erst
zufällig, weil er das Guss-Foto erwartet hat.

Beobachteter Vorfall: Die Garten-Kamera lieferte zuletzt um 20:00 ein Bild (`last_seen`
eingefroren auf 20:00), der Akku-Wert im Bot stammte noch vom 20:00-Upload. Das um 22:17
erwartete Guss-Foto kam nie an — ohne jede Meldung.

## Lösung (Solution)

Der Bewässerungs-Daemon überwacht jeden Aufnahme-Zeitpunkt aktiv: Schließt dessen
Zustellfenster, ohne dass die Garten-Kamera ein Bild geliefert hat, sendet der Telegram-Bot
**zeitnah** (innerhalb weniger Minuten nach dem erwarteten Zeitpunkt) genau **eine**
Warnung. Der Benutzer erfährt so sofort, dass ein erwartetes Foto ausgeblieben ist — statt
erst Stunden später über die träge Kamera-Überwachung oder gar nicht.

Die Warnung nennt den betroffenen Aufnahme-Zeitpunkt (Beschriftung und Uhrzeit) und wann
die Garten-Kamera zuletzt gesehen wurde, sodass der Benutzer das Problem einordnen kann
(Kamera schläft/offline vs. Upload-Fehler).

Das Feature ist **rein serverseitig** — Protokoll zwischen Garten-Kamera und Steuerzentrale
sowie die Firmware bleiben unverändert (wie bei Feature 0030).

## User Stories

1. Als Benutzer möchte ich zeitnah gewarnt werden, wenn ein erwartetes **Guss-Foto** nach
   einem Zeitplan nicht ankommt, um zu erfahren, dass die Garten-Kamera das
   Bewässerungsergebnis nicht liefern konnte.
2. Als Benutzer möchte ich zeitnah gewarnt werden, wenn ein Foto zu einer **Festen
   Fotozeit** ausbleibt, damit auch meine fest konfigurierten Aufnahme-Zeitpunkte überwacht
   sind.
3. Als Benutzer möchte ich die Warnung **innerhalb weniger Minuten** nach dem erwarteten
   Zeitpunkt erhalten, nicht erst Stunden später über die Kamera-Überwachung.
4. Als Benutzer möchte ich in der Warnung sehen, **welcher** Aufnahme-Zeitpunkt betroffen
   ist (Beschriftung wie „Nach dem Guss „Rasen"" oder „Foto um 18:00") und um welche
   **Uhrzeit** er erwartet war.
5. Als Benutzer möchte ich in der Warnung sehen, **wann die Garten-Kamera zuletzt gesehen**
   wurde, um einzuschätzen, ob sie schläft, offline ist oder nur ein Upload fehlschlug.
6. Als Benutzer möchte ich **genau eine** Warnung je erwartetem Foto — kein wiederholtes
   Nachhaken für denselben Aufnahme-Zeitpunkt.
7. Als Benutzer möchte ich **keine** Entwarnung, wenn die Kamera später wieder liefert — die
   ausgebliebene Aufnahme ist die Information, die ich brauche.
8. Als Benutzer möchte ich bei einem **längeren Ausfall keine Doppel-Meldungen**: Sobald die
   Kamera-Überwachung die Garten-Kamera bereits als offline gemeldet hat, soll die
   Foto-Warnung schweigen — der Watchdog hat übernommen.
9. Als Benutzer möchte ich auch dann gewarnt werden, wenn der zugehörige Guss **regenbedingt
   übersprungen** wurde — ein fehlendes Foto signalisiert ein Kamera-/Netzwerk-Problem
   unabhängig davon, ob gegossen wurde.
10. Als Benutzer möchte ich auch dann eine Warnung, wenn die Kamera zwar aufwachte, aber ihr
    **Upload abgewiesen** wurde (kein gültiges Bild) — auch dann ist kein Foto angekommen.
11. Als Betreiber möchte ich nach einem **Daemon-Neustart keine Alarm-Flut** für längst
    vergangene Aufnahme-Zeitpunkte des Tages.
12. Als Betreiber möchte ich das Karenzfenster der Erkennung **konfigurieren** können.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Rein serverseitig**, kein Protokoll-/Firmware-Eingriff. Baut direkt auf den
  Aufnahme-Zeitpunkten aus Feature 0030 auf (Guss-Foto = Startzeit + Dauer + Nach-Offset;
  Feste Fotozeit = konfigurierte HH:MM).

- **Minütliche Prüfung im Scheduler.** Eine neue Prüf-Routine wird — analog zur bestehenden
  Guss-Vorwarnung — je Minute aus der Scheduler-Schleife aufgerufen. Sie liest den Zustand
  der Garten-Kameras und die Aufnahme-Zeitpunkte und entscheidet, ob eine Warnung fällig
  ist.

- **Erkennung „Fenster gerade geschlossen" als reine Core-Funktion.** In der bestehenden
  Core-Komponente für getimte Aufnahmen entscheidet eine reine Funktion (keine I/O), welche
  Aufnahme-Zeitpunkte **gerade** ihr Zustellfenster geschlossen haben — d. h. `Ziel +
  Toleranz` liegt innerhalb der zurückliegenden Karenz. Eingaben: `now`, Zeitpläne, Feste
  Fotozeiten, Nach-Offset, Toleranz, Karenz. Ausgabe: Liste aus (Ziel-Zeitpunkt,
  Beschriftung).

- **Zustell-Kriterium über `last_seen`.** Ein Aufnahme-Zeitpunkt gilt als **zugestellt**,
  wenn die Garten-Kamera innerhalb des Fensters ein Bild hochgeladen hat. Als robustes,
  zustandsloses Signal dient `last_seen` der Kamera: Liegt es **auf oder nach**
  Fensterbeginn (`Ziel − Toleranz`), gab es einen Upload im Fenster — und dieser hätte per
  bestehender Zuordnung (`find_matching_photo_target`) automatisch das getimte Foto
  zugestellt. Ein **abgewiesener** Upload aktualisiert `last_seen` nicht und wird daher
  korrekt als „ausgeblieben" erkannt. Die Prüfung vergleicht Zeitstempel konsistent in
  lokaler Zeit (so wie `last_seen` beim Upload geschrieben wird).

- **Verpasst-Bedingung (Entscheidungs-Kern).** Für einen aktiven Aufnahme-Zeitpunkt und eine
  Garten-Kamera gilt „ausgeblieben" genau dann, wenn alle drei zutreffen:
  1. `0 ≤ (now − (Ziel + Toleranz)) < Karenz` — Fenster gerade geschlossen (zeitnah &
     neustart-sicher: alte Ziele fallen aus der Karenz).
  2. `last_seen < Ziel − Toleranz` — kein Upload im Fenster (bzw. `last_seen` fehlt ganz).
  3. Für die Kamera ist **kein** Kamera-Überwachungs-Alarm aktiv
     (`watchdog_alert_active_camera_{mac} != "1"`).

- **Genau ein Alarm je Aufnahme-Zeitpunkt, keine Entwarnung.** Ein einzelner Merker je
  Garten-Kamera (`last_missed_photo_alert:{mac}` = `{Datum}|{Beschriftung}`) verhindert eine
  Doppelmeldung über zwei aufeinanderfolgende Minuten-Ticks. Bewusst als **ein** Schlüssel
  gehalten — exakt gespiegelt am bestehenden `last_timed_photo:{mac}`-Muster (kein
  Aufräumen, kein Datenmüll). Ein anderer, späterer Aufnahme-Zeitpunkt löst weiterhin seine
  eigene Warnung aus. Es gibt **kein** Resolved-Ereignis.

- **Übergang zur Kamera-Überwachung.** Sobald die Kamera-Überwachung die Garten-Kamera als
  offline meldet (ihr Alarm-Flag aktiv), schweigt die Foto-Warnung (Bedingung 3). So gibt es
  genau eine Foto-Warnung beim ersten verpassten Bild; bei anhaltendem Ausfall übernimmt der
  Inaktivitäts-Watchdog. Die Kamera-Überwachung selbst bleibt **unverändert**.

- **Neues Ereignis im Ereignis-Kanal.** Ein `TimedPhotoMissed`-Ereignis (Wunschname,
  Beschriftung, Ziel-Uhrzeit, Zuletzt-gesehen-Zeitpunkt) wird von der Scheduler-Prüfung
  publiziert. Die Präsentationsschicht (Telegram-Bot) abonniert es und sendet die Warnung
  als Broadcast-Benachrichtigung — Muster wie beim bestehenden Kamera-Inaktivitäts-Alarm.
  Kein direkter Aufruf zwischen den Schichten.

- **Nachricht (Entwurf).** Stil wie bestehende Kamera-Warnungen, z. B.:
  „⚠️ *Foto ausgeblieben:* Das erwartete Foto „Nach dem Guss „Rasen"" um **22:17 Uhr** ist
  nicht angekommen. Garten-Kamera „GartenKamera" zuletzt gesehen: **20:00 Uhr**."

- **Konfiguration.** Toleranzfenster: bestehendes `TIMED_PHOTO_TOLERANCE_MINUTES` (Default
  5). Neu: `CAMERA_MISSED_PHOTO_GRACE_MINUTES` (Karenz nach Fensterschluss, Default 2) in
  `config/garden.conf` — nicht-geheim, versioniert (ADR 0030).

- **Mehrere Garten-Kameras.** Die Prüfung läuft je aktiver Garten-Kamera; jede, die einen
  Aufnahme-Zeitpunkt nicht bedient hat, meldet für sich. (Für den Ein-Kamera-Betrieb ohne
  Zusatzkosten.)

## Test-Entscheidungen (Testing Decisions)

- **Was ein guter Test ist:** beobachtbares Außenverhalten — welche Aufnahme-Zeitpunkte die
  Core-Funktion als „gerade geschlossen" liefert, und welches Ereignis / welche
  Telegram-Nachricht die minütliche Prüfung auslöst. Keine internen Felder.

- **Core (rein, ohne I/O):** die neue „Fenster gerade geschlossen"-Funktion —
  - Ziel, dessen `Ziel + Toleranz` in der Karenz liegt → gelistet;
  - Ziel noch offen (Fenster nicht geschlossen) oder außerhalb der Karenz (zu alt) → nicht
    gelistet (Neustart-Sicherheit);
  - deckt Guss-Foto und Feste Fotozeit ab.
  Referenz: bestehende `tests/core/test_camera_schedule.py`.

- **Scheduler-Prüfung:** höchste sinnvolle Nahtstelle — die minütliche `check_missed_photos`
  gegen eine temporäre DB (Muster wie bestehende Scheduler-/Integrationstests). Fälle:
  - `last_seen` vor Fensterbeginn → `TimedPhotoMissed` wird publiziert;
  - `last_seen` im Fenster → kein Ereignis;
  - Kamera-Überwachungs-Flag aktiv → kein Ereignis;
  - Merker bereits gesetzt (zweiter Tick) → keine erneute Meldung;
  - Aufnahme-Zeitpunkt von früher am Tag (außerhalb Karenz) → kein Ereignis;
  - übersprungener Guss → dennoch Ereignis (Entkopplung vom Guss-Ergebnis).

- **Telegram-Bot:** der Handler für `TimedPhotoMissed` sendet die korrekte
  Broadcast-Benachrichtigung mit Beschriftung, Ziel-Uhrzeit und Zuletzt-gesehen-Zeit.
  Referenz: bestehende Benachrichtigungs-Tests (Kamera-Inaktivität) in
  `tests/ui/test_telegram_ui.py`.

- **Pflege:** neue Telegram-Nachricht in `docs/design/telegram-nachrichten.html` nachziehen
  (Regel `.claude/rules/telegram_messages.md`). Coverage darf nicht regredieren; TDD
  (Failing-Test zuerst).

## Nicht im Leistungsumfang (Out of Scope)

- **Entwarnung / Resolved-Meldung**, wenn die Garten-Kamera später wieder liefert.
- **Unterdrückung bei regenbedingt übersprungenem Guss** — es wird bewusst trotzdem gewarnt.
- **Änderungen an der Kamera-Überwachung / am Inaktivitäts-Watchdog** — dieser bleibt wie er
  ist und dient als Auffangnetz bei anhaltendem Ausfall.
- **Behebung der eigentlichen Aufwach-/Drift-Ursache** (RTC-Drift, WLAN-Abbruch,
  Brown-out) an der Garten-Kamera — Firmware/Hardware, eigenes Thema.
- **Wiederholte Erinnerungen** an denselben ausgebliebenen Aufnahme-Zeitpunkt.
- **Aktuelle Akku-Abfrage** — der angezeigte Akku-Wert stammt weiterhin aus dem letzten
  Upload; dieses Feature ändert das nicht.

## Weitere Anmerkungen (Further Notes)

- Kernconstraint (aus Feature 0030): Die Garten-Kamera ist batteriebetrieben, schläft per RTC
  stromlos und ist **nur beim Aufwachen** über `GET /config` erreichbar. Aktives Aufwecken
  ist unmöglich — deshalb kann der Daemon eine ausbleibende Aufnahme nur **nachträglich**
  erkennen (nach Fensterschluss), nicht verhindern.
- Das Feature schließt die Reaktions-Lücke zwischen dem präzisen, aber späten
  Inaktivitäts-Watchdog und dem Wunsch nach einer sofortigen Rückmeldung zu einem konkret
  erwarteten Aufnahme-Zeitpunkt.
- Der `last_seen`-basierte Zustell-Nachweis nutzt bewusst dasselbe zustandslose,
  neustart-sichere Prinzip wie die Zuordnung beim Upload in Feature 0030 (Zeit-Heuristik,
  kein gemerkter Zustand zwischen `/config` und `/upload`).
- Aus dem Debugging-/Brainstorming-Kontext dieser Sitzung erarbeitet.
