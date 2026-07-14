# Implementierungsplan: Feature 0041 — Diagnose-Paket per `/diagnose`

Referenz: `docs/features/0041-diagnose-paket.md` · CONTEXT.md (Diagnose-Paket) · ADR 0034 (Bot-Navigation/De-dup) · Beads `telegram-GartenBot-sc7`

## Schritt 1 — Tests (RED): Sammel-Logik (neuer Adapter „Diagnose")

`tests/adapters/test_diagnose.py` (Muster: temporäre DB wie `tests/adapters/test_database.py`, gemockter `subprocess`):
- **Happy Path:** `collect_diagnose_paket()` liefert ZIP-Bytes; Archiv enthält `journal_daemon.txt`, `journal_zigbee2mqtt.txt`, `garden.db`, `garden.conf`, `system_info.txt`; Lückenliste leer.
- **Journal verweigert** (`CalledProcessError`/`FileNotFoundError`): ZIP ohne die betroffene Journal-Datei, Lücke benannt, kein Abbruch.
- **DB-Schnappschuss schlägt fehl:** Lücke benannt, übrige Bausteine vorhanden.
- **`.env`-Garantie:** `.env` existiert im Arbeitsverzeichnis → erscheint **nie** im Archiv.
- **DB-Konsistenz:** Schnappschuss entsteht über die SQLite-Backup-API; die Kopie ist öffnbar und enthält die Tabellen der Quelle.
- **Größen-Wächter:** injizierbare Maximalgröße; Überschreitung → Paket ohne `garden.db` neu gepackt, Lücke benannt.
- **Totalausfall:** kein Baustein einsammelbar → `(None, Lücken)`.

## Schritt 2 — Tests (RED): Dokument-Versand im Telegram-Client

`tests/ui/test_telegram_client.py` (Muster: bestehende Tests mit Token-Override + gemocktem `urlopen`):
- multipart-Aufbau: `document`-Feld mit Dateiname, `chat_id`, optionale `caption`.
- Token-Guard: leerer Token → kein HTTP-Aufruf, `False`.
- HTTP-Fehler → `False`, keine Exception.

## Schritt 3 — Tests (RED): UI-Handler, Dispatcher, Wiring

`tests/ui/test_telegram_ui.py` (Muster: gemockter `telegram_client`):
- `/diagnose` → sofortige Quittung an den anfragenden Chat; Arbeit startet in Hintergrund-Thread (`daemon=True`).
- Synchrone Kernfunktion (vom Thread-Start getrennt geschnitten): sendet `send_chat_action`, ruft Sammel-Funktion, sendet Dokument an den anfragenden Chat; Antwort nennt Größe und Lücken.
- Totalausfall der Sammel-Funktion → klare Fehlermeldung statt Dokument.
- Dispatcher routet `/diagnose`; Wiring-Smoke: Befehlsregistrierung enthält `diagnose`.

## Schritt 4 — GREEN: Adapter „Diagnose"

- `collect_diagnose_paket(max_bytes)` → `(bytes | None, missing: list[str])`; Bausteine unabhängig via `zipfile` in Memory.
- Journale per `journalctl -u <unit> -n <N> --no-pager`-Subprozess (2000/500 Zeilen, ohne root).
- DB-Schnappschuss: SQLite-Backup-API in Temp-Datei, dann ins Archiv (nie Roh-Kopie der WAL-Datei).
- System-Steckbrief: Version (bestehende `config`-Versionsquelle), Python-Version, Uptime, freier Speicher, `systemctl is-active` der drei Dienste; Fehler je Zeile tolerant.
- DB-Pfad über das Datenbank-Modul (bestehende Praxis, Präzedenz `daily_report`).

## Schritt 5 — GREEN: `send_document` im Telegram-Client

- Multipart-Upload analog `send_photo` (Feld `document`, `application/zip`, Dateiname mit Zeitstempel), Token-Guard, 30 s Timeout (größere Datei).

## Schritt 6 — GREEN: UI + Dispatcher + Registrierung

- Handler: Quittung → Hintergrund-Thread (`daemon=True`) → Kernfunktion (chat_action, sammeln, senden, Antwort mit Größe/Lücken).
- Dispatcher-Zweig `/diagnose`; Befehlsregistrierung um `diagnose` erweitern (4. Eintrag).

## Schritt 7 — Setup-Härtung

- Installationsskript: Dienst-Benutzer in die Journal-Lesegruppe aufnehmen (nur Wirkung für frische Installationen; Bestand wird von der Degradations-Politik aufgefangen).

## Schritt 8 — Doku (DoD-Pflichten)

- `telegram-sitemap.html`: `/diagnose` als registrierter Befehl.
- `telegram-nachrichten.html`: Karte mit Quittung, Erfolgs-Antwort (Größe), Lücken-Variante, Totalausfall-Fehler.
- README („Bedienung", Troubleshooting-Zeile) + `docs/assets/bot_description.md` + gültige-Befehle-Liste in `.agents/rules/telegram_messages.md`.
- `CONTEXT.md`: Status des Begriffs „Diagnose-Paket" auf aktiv setzen.

## Schritt 9 — Volle Suite + Coverage

- `python -m pytest tests` grün; `run_coverage` ohne Regression.

## Definition of Done

- [ ] Alle Tests grün (bestehende + neue), Coverage nicht regriert
- [ ] Sammel-Logik mit Degradations-Politik und `.env`-Garantie
- [ ] `send_document` mit Token-Guard
- [ ] `/diagnose`: Quittung, Hintergrund-Thread, Dokument, Lücken-Ausweis
- [ ] Befehl registriert (4. Menü-Eintrag)
- [ ] Setup-Härtung (Journal-Lesegruppe)
- [ ] Doku aktualisiert (Sitemap, Nachrichten, README, bot_description, Regeldatei, CONTEXT.md)
- [ ] Beads-Issue geschlossen, Feature- und Plan-Doc nach `completed/`
