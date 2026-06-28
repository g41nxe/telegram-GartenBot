# Implementierungsplan: Feature 0035 — Nächsten Aufnahme-Zeitpunkt sichtbar machen

Referenz: `docs/features/0035-naechster-aufnahme-zeitpunkt-sichtbar.md` · ADR 0036 ·
CONTEXT.md (Aufnahme-Zeitpunkt, Guss-Foto, feste Fotozeit)

## Schritt 1 — Tests (RED)

**Core** (`tests/core/test_camera_schedule.py`, Muster der bestehenden Schedule-Tests):
- `next_photo_target(now, schedules, photo_times, after_offset)` → frühestes zukünftiges Ziel,
  korrekte Aufnahmezeit (`Start + Dauer + Offset`), strukturiertes Label (Typ + Zeitplan-Name).
- Guss-Foto vs. feste Fotozeit korrekt typisiert; Name nur beim Guss-Foto gesetzt.
- Kein Ziel (keine aktiven Zeitpläne, keine festen Zeiten) → `None`.
- Inaktiver Zeitplan erzeugt **kein** Guss-Ziel.
- Caption-Hilfe: Guss-Ziel-Label enthält den Zeitplan-Namen, feste Fotozeit die Uhrzeit.

**UI** (`tests/ui/test_telegram_ui.py`, gemockt `telegram_client`/`database`):
- `/status` rendert die „📷 Nächstes Foto"-Zeile direkt unter „Nächster Guss" (Text mit
  Aufnahmezeit + Anlass).
- Zeile **entfällt**: keine Kamera registriert; bzw. keine Aufnahme-Zeitpunkte.
- Offline-Kamera → Zeile bleibt.
- Fotozeiten-Ansicht: zwei Abschnitte; feste Zeiten mit 🗑️, Guss-Fotos **ohne** Löschen-Button;
  nur aktive Zeitpläne; leere Abschnitte weggelassen; beide leer → bisherige Leer-Meldung;
  ➕-Button immer vorhanden.

## Schritt 2 — Core: Ziel-Funktionen erweitern

- `_guss_targets`/`_absolute_targets` so erweitern, dass sie neben `target_dt` ein **strukturiertes
  Label** liefern (Typ `guss`/`fix`, Zeitplan-Name beim Guss, Uhrzeit bei fest). Rückwärtskompatibel
  zu den bestehenden Aufrufern halten.
- Neue reine Funktion `next_photo_target(...)` über dieselben Ziel-Quellen.

## Schritt 3 — Caption: Anlass statt Startzeit

- `find_matching_photo_target` so anpassen, dass die zurückgegebene Beschriftung beim Guss-Foto
  den **Zeitplan-Namen** nennt („📷 Nach dem Guss „Rasen"") und bei fester Fotozeit die Uhrzeit
  („📷 Foto um 18:00") behält. Dedup-/Aufrufpfad im `camera_receiver` unverändert lassen.

## Schritt 4 — /status: „Nächstes Foto"-Zeile

- In `handle_status` die Zeile direkt unter der „Nächster Guss"-Zeile rendern: nächster
  Aufnahme-Zeitpunkt via `next_photo_target` (DB: Kameras, aktive Zeitpläne, feste Fotozeiten).
- heute/morgen + Uhrzeit-Stil; Markdown-Escape des Namens; Zeile entfällt ohne Kamera/Ziele.

## Schritt 5 — Fotozeiten-Ansicht: zwei Abschnitte

- `handle_aufnahmen` in „⏰ Feste Zeiten" (löschbar, unverändert) und „🌿 Nach Güssen" (read-only,
  aktive Zeitpläne, berechnete Aufnahmezeit + Name) aufteilen.
- Leere Abschnitte auslassen; beide leer → bisherige Leer-Meldung; ➕-Button immer.

## Schritt 6 — `telegram-nachrichten.html`

- Guss-Foto-Caption (neuer Wortlaut mit Name) und feste-Fotozeit-Caption in der Referenz
  aktualisieren (Regel `telegram_messages.md`).

## Schritt 7 — Doku

- ADR 0036 und CONTEXT.md (Guss-Foto, feste Fotozeit) sind bereits geschrieben — bei Umsetzung
  nur verifizieren/Status aktualisieren.

## Definition of Done

- [ ] Alle Tests grün (bestehende + neue), Coverage nicht regriert
- [ ] `next_photo_target` + strukturierte Ziel-Labels umgesetzt
- [ ] /status zeigt „Nächstes Foto" (mit korrekten Leer-/Offline-Fällen)
- [ ] Fotozeiten-Ansicht mit festen Zeiten + read-only Guss-Fotos
- [ ] Guss-Foto-Caption nennt den Zeitplan; feste Fotozeit nennt die Uhrzeit
- [ ] `telegram-nachrichten.html` aktualisiert
- [ ] Beads-Issue geschlossen
- [ ] Feature- und Plan-Dokument nach `completed/` verschoben
