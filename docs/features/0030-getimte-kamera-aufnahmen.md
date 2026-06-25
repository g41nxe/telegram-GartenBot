# Feature: Getimte Kamera-Aufnahmen (Aufnahme-Zeitpunkte)

## Problemstellung (Problem Statement)

Heute steuert die Garten-Kamera nur ein festes **Sende-Intervall** (`sleep_duration_seconds`):
Sie wacht aus dem Tiefschlaf auf, macht ein Foto, lädt es hoch und schläft wieder gleich
lang. Der Benutzer kann **keine konkreten Zeitpunkte** festlegen, zu denen ein Foto
entstehen soll — insbesondere nicht **nach einem zeitgesteuerten Guss**, um das Ergebnis
der Bewässerung zu sehen. Außerdem landen alle Bilder still in der Bild-Historie; es gibt
keine aktive Benachrichtigung zu einem gewünschten Zeitpunkt.

## Lösung (Solution)

Die Steuerzentrale berechnet **Aufnahme-Zeitpunkte** und weckt die Kamera gezielt dann,
indem sie deren **Schlafdauer dynamisch** setzt. Aufnahme-Zeitpunkte haben zwei Quellen:

1. **Nach jedem zeitgesteuerten Guss** — automatisch, `Startzeit + Dauer + Nach-Offset`.
2. **Global konfigurierte feste Uhrzeiten** — täglich wiederkehrend (HH:MM), per Wizard
   gepflegt (analog zu den Guss-Zeitplänen).

Ein zu einem Aufnahme-Zeitpunkt entstandenes Foto wird **aktiv per Telegram-Bot
zugestellt** (mit Beschriftung). Reguläre Intervall-Bilder bleiben wie bisher still in der
Bild-Historie. Das **Intervall bleibt** als obere Schlaf-Grenze erhalten (Zeitraffer läuft
weiter und sorgt für regelmäßiges „Check-in").

Das gesamte Feature ist **rein serverseitig** — das Protokoll zwischen Kamera und
Steuerzentrale und die Firmware bleiben unverändert.

## User Stories

1. Als Benutzer möchte ich nach jedem zeitgesteuerten Guss automatisch ein Foto erhalten,
   um das Bewässerungsergebnis zu sehen.
2. Als Benutzer möchte ich feste tägliche Uhrzeiten festlegen, zu denen die Kamera ein Foto
   macht (z. B. 08:00, 18:00).
3. Als Benutzer möchte ich solche festen Uhrzeiten **per Wizard** anlegen — Stunde und
   Minute wählen — genauso vertraut wie beim Anlegen eines Guss-Zeitplans.
4. Als Benutzer möchte ich meine Aufnahme-Uhrzeiten auflisten und einzeln löschen können.
5. Als Benutzer möchte ich das getimte Foto **als Telegram-Nachricht mit Beschriftung**
   bekommen (z. B. „Nach dem Guss um 06:00"), nicht nur in der Historie.
6. Als Benutzer möchte ich, dass die regulären Zeitraffer-Bilder **nicht** als Nachricht
   kommen (kein Spam) — nur die getimten.
7. Als Benutzer möchte ich, dass das Sende-Intervall als regelmäßige Basis erhalten bleibt,
   damit der Zeitraffer weiterläuft und neue Zeitpläne zeitnah berücksichtigt werden.
8. Als Betreiber möchte ich Toleranzfenster und Nach-Guss-Offset konfigurieren können.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Rein serverseitig, kein Protokoll-/Firmware-Eingriff.** `GET /config` liefert dieselbe
  Struktur wie heute, nur `sleep_duration_seconds` wird **dynamisch** berechnet. `POST
  /upload` bleibt unverändert; die Kamera teilt **nicht** mit, warum sie aufgewacht ist.
- **Schlafdauer-Berechnung als reine Core-Funktion** (z. B. `core/camera_schedule.py`):
  `compute_next_sleep_seconds(now, schedules, photo_times, interval_seconds, after_offset)`
  → `min(now + interval, nächster Aufnahme-Zeitpunkt) − now`. Keine I/O; der `/config`-
  Adapter beschafft die Eingaben (Zeitpläne, Foto-Uhrzeiten, Kamera-Intervall) und ruft sie
  auf.
- **Aufnahme-Zeitpunkte:**
  - **Guss:** nur **nach** dem Guss — `Startzeit + duration_minutes + Nach-Offset`. Geplant
    auf die **Max-Dauer**, da die Kamera ihre Schlafdauer beim Aufwachen festlegt und ein
    früheres (volumenbedingtes) Guss-Ende nicht nachsteuern kann. **Kein** Vor-Foto.
  - **Absolut:** global konfigurierte tägliche HH:MM-Zeiten (minutengenau).
- **Intervall** (`sleep_duration_seconds`, pro Kamera) bleibt die **obere Schlaf-Grenze**.
  Es garantiert ein „Check-in" mindestens jedes Intervall — dadurch werden neue/geänderte
  Zeitpläne zeitnah gesehen (mildert die „committed sleep"-Einschränkung).
- **Telegram-Zustellung über den Ereignis-Kanal:** Beim Upload prüft der Adapter über eine
  reine Core-Funktion, ob `now` innerhalb des Toleranzfensters um einen Aufnahme-Zeitpunkt
  liegt. Falls ja → neues Ereignis `TimedPhotoCaptured(wish_name, pfad, caption)`; der
  Telegram-Bot abonniert es und sendet das Foto mit Beschriftung. Falls nein → nur
  Bild-Historie (wie bisher). Beispiel-Beschriftungen: „📷 Nach dem Guss um 06:00",
  „📷 Foto um 18:00".
- **Erkennung zustandslos & neustart-sicher:** Zeit-Heuristik (Upload-Uhrzeit vs. berechnete
  Aufnahme-Zeitpunkte), kein gemerkter Zustand zwischen `/config` und `/upload`. Bewusster
  Trade-off für „kein Protokoll-Eingriff" (siehe Out of Scope: zuverlässiges Tagging).
- **Persistenz der Foto-Uhrzeiten — eigene Tabelle, analog Zeitpläne:** neue Tabelle
  `camera_photo_times` (global; eine Zeile pro täglicher Uhrzeit, `UNIQUE(time)`),
  Migration über `init_db()` (`ALTER TABLE`/`CREATE TABLE` im `try/except`-Stil).
- **Wizard + Verwaltung im Telegram-Bot**, gespiegelt am Guss-Zeitplan-UX: Anlegen über
  Stunden-/Minuten-Inline-Tastaturen (bestehende Keyboards mit eigenem Callback-Prefix
  wiederverwenden), plus Liste und Einzel-Löschung.
- **Konfigurationswerte:**
  - `TIMED_PHOTO_TOLERANCE_MINUTES` (`garden.conf`, Default 5) — Toleranzfenster.
  - `CAMERA_AFTER_GUSS_OFFSET_MINUTES` (`garden.conf`, Default 2) — Nach-Guss-Offset.
  - Foto-Uhrzeiten in der DB-Tabelle `camera_photo_times` (über Wizard, kein Deploy nötig).

## Test-Entscheidungen (Testing Decisions)

- **Was ein guter Test ist:** beobachtbares Außenverhalten — welche Schlafdauer `/config`
  liefert, welches Ereignis/welche Telegram-Nachricht ein Upload auslöst — nicht interne
  Felder.
- **Core (rein, ohne I/O):**
  - `compute_next_sleep_seconds`: nächster Aufnahme-Zeitpunkt aus Guss-Zeitplänen +
    Foto-Uhrzeiten korrekt; Deckelung durch Intervall; „kein Ziel in Reichweite" → volles
    Intervall; Guss-Ziel = Start + Dauer + Offset.
    Klassifikation beim Upload: innerhalb/außerhalb Toleranzfenster, richtige Beschriftung,
    nächstgelegenes Ziel bei mehreren.
- **Adapter `camera_receiver`:** `/config` gibt dynamische Schlafdauer zurück; `/upload`
  innerhalb des Fensters → `TimedPhotoCaptured`, außerhalb → kein Ereignis. Referenz:
  bestehende `tests/adapters/test_camera_receiver.py`.
- **Telegram-Bot:** Handler für `TimedPhotoCaptured` sendet Foto mit korrekter Beschriftung;
  Wizard legt Foto-Uhrzeit an, Liste/Löschen funktionieren. Referenz: bestehende
  Zeitplan-Wizard-Tests und Benachrichtigungs-Tests in `tests/ui/test_telegram_ui.py`.
- **DB:** Migration/CRUD für `camera_photo_times`.
- **Pflege:** neue Telegram-Nachricht (getimtes Foto + Beschriftung) und der `/camera_times`-
  bzw. Wizard-Dialog in `docs/design/telegram-nachrichten.html` nachziehen (Regel
  `.claude/rules/telegram_messages.md`). Coverage darf nicht regredieren; TDD.

## Nicht im Leistungsumfang (Out of Scope)

- **Vor-Guss-Foto** — nur nach dem Guss.
- **Zuverlässiges Pro-Foto-Tagging / automatische Vorher-Nachher-Paare** — bräuchte einen
  Protokoll-Eingriff (Kamera meldet den Aufwach-Grund). Eigenes Folge-Feature.
- **Pro-Kamera unterschiedliche absolute Uhrzeiten** — die Liste ist global.
- **Fotos zu manuellen (nicht zeitgesteuerten) Güssen** — die Kamera kann dafür nicht
  geweckt werden.
- **Unterdrückung des Nach-Fotos bei regenbedingt übersprungenem Guss** — technisch durch
  „committed sleep" kaum möglich; das Nach-Foto wird akzeptiert.
- **Höhere Zeitpräzision als minutengenau** und sekundengenaue Aufwach-Steuerung (RTC-Drift).

## Weitere Anmerkungen (Further Notes)

- Kernconstraint: Die Kamera (M5Stack Timer Camera F) ist batteriebetrieben, schläft per
  RTC stromlos und ist **nur beim Aufwachen** über `GET /config` erreichbar. Einziger
  Steuerhebel ist die zurückgegebene Schlafdauer; aktives Aufwecken ist unmöglich. Daraus
  folgt die Annäherung an Aufnahme-Zeitpunkte und die „committed sleep"-Einschränkung.
- Mit `/grill-with-docs` aus dem Konversationskontext erarbeitet.
