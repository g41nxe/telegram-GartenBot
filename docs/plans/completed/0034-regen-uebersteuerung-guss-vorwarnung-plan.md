# Implementierungsplan: Feature 0034 — Regen-Übersteuerung mit Guss-Vorwarnung

Referenz: `docs/features/0034-regen-uebersteuerung-guss-vorwarnung.md` · ADR 0035 · CONTEXT.md (Guss-Vorwarnung, Regen-Übersteuerung)

## Schritt 1 — Tests (RED)

**Scheduler** (`tests/test_irrigation.py`, Muster `TestNebelScheduling` — direkter Aufruf mit gestelltem `now`):
- Bei `now == Start − RAIN_WARNING_LEAD_MINUTES` und Wetter-Bewertung = **Skip** → `WateringRainWarning` wird publiziert (mit `schedule_id`, Name, Zeit, Ventil(e), `duration_original`, `volume_original`, Reasons).
- Dito bei Wetter-Bewertung = **reduziert** (Faktor < 1) → `WateringRainWarning` publiziert.
- Bei Wetter-Bewertung = **voller Guss** → **kein** Event.
- Außerhalb des `T−5`-Zeitpunkts → **kein** Event.
- Inaktiver Zeitplan / Nebel-Modus → **kein** Event.
- `_trigger_scheduled_watering` mit gesetztem Override-Flag → voller **Original**-Guss (Original-Dauer/-Menge, korrekte Ventile, Ausführungsmodus); `evaluate_watering_factor` wird **nicht** aufgerufen; Flag danach **verbraucht**.
- `_trigger_scheduled_watering` **ohne** Flag → unveränderter Skip-/Reduzierungs-Pfad.

**UI** (`tests/ui/test_telegram_ui.py`, gemockter `telegram_client`):
- `_on_watering_rain_warning` sendet Broadcast mit Inline-Button `rainoverride_{id}_{datum}` und konkreten Details (Zeitplan, Ventil, Dauer/Menge, mm-Werte aus den Reasons).
- Callback `rainoverride_{id}_{datum}` setzt das Metadaten-Flag `rain_override:{id}:{datum}` und quittiert.
- „Zu spät"/idempotent: Callback ohne anstehenden Lauf bzw. mit bereits verbrauchtem Flag → sachliche Rückmeldung, **kein** Guss-Start.

**Persistenz** (`tests/adapters` o. `test_irrigation`): Flag wird aus System-Metadaten gelesen (neustart-fest) und nach der Ausführung entfernt.

## Schritt 2 — Event-Schema (`core/scheduler_events.py`)

- Neues Event `WateringRainWarning(schedule_id, schedule_name, time, valve_names, duration_original, volume_original, reasons)`.
- `WateringSkipped` um `schedule_id` erweitern (für eindeutige Zuordnung des übersprungenen Laufs).
- `WateringScaled` um `schedule_id` erweitern (trägt Originalwerte bereits).
- Alle Erzeuger (Scheduler) und Verbraucher (UI-Handler, ggf. `DatabaseLoggerAdapter`) an die neuen Felder anpassen.

## Schritt 3 — Konfiguration

- `RAIN_WARNING_LEAD_MINUTES` in `config.py` (Default 5, try/except) und `config/garden.conf` ergänzen (generischer Wert, ADR 0030).

## Schritt 4 — Scheduler: Vorab-Prüfung (T−5)

- Neue reine Hilfsfunktion (analog `_ensure_nebel_window`), die für einen aktiven Bewässerungs-Zeitplan prüft, ob `now` == `Start − Lead` ist, und bei Skip/Reduzierung (Wiederverwendung der bestehenden Bewertung via `plan_scheduled_run`/`evaluate_watering_factor`) `WateringRainWarning` publiziert.
- Verdrahtung in `_scheduler_loop` (je Minute, je aktivem `mode == "watering"`-Zeitplan).
- Hinweis: Vorwarn-Zeit aus Startzeit − Lead berechnen; Flag-Schlüssel verwendet das **Datum des geplanten Laufs**.

## Schritt 5 — Scheduler: Override bei Ausführung

- In `_trigger_scheduled_watering` **vor** dem Wetter-Check das Flag `rain_override:{schedule_id}:{datum}` lesen.
- Gesetzt → Wetter-Bewertung überspringen, Guss mit Original-Dauer/-Menge über den bestehenden Multi-Ventil-/Ausführungsmodus-Pfad starten, danach Flag löschen.
- Nicht gesetzt → bestehender Pfad (Skip/Reduzierung) unverändert.

## Schritt 6 — UI: Vorwarnung + Callback

- `_on_watering_rain_warning(event)`: `broadcast_notification` mit Text (Details + Regen-Begründung, ADR 0029) und Inline-Keyboard „🚿 Regen ignorieren" → `rainoverride_{id}_{datum}`.
- In `subscribe_event_handlers()` abonnieren.
- Callback `rainoverride_{id}_{datum}` im `_process_callback_query`-Pfad: Flag setzen, `answer_callback_query`; bei bereits gelaufenem/abgelaufenem Lauf sachliche Rückmeldung statt Start.
- Markdown-Escaping für den Zeitplan-/Ventilnamen (bestehendes `_md_escape`).

## Schritt 7 — `telegram-nachrichten.html`

- Neue Karte „Guss-Vorwarnung" (Broadcast) mit Override-Button und der „zu spät"-Variante (Regel `telegram_messages.md`).

## Schritt 8 — Doku

- ADR 0035 und CONTEXT.md (Guss-Vorwarnung, Regen-Übersteuerung) sind bereits geschrieben — bei Umsetzung nur verifizieren/Status aktualisieren.

## Definition of Done

- [ ] Alle Tests grün (bestehende + neue), Coverage nicht regriert
- [ ] `WateringRainWarning` + `schedule_id`-Erweiterungen umgesetzt
- [ ] Scheduler: Vorab-Prüfung (T−5) und Override-Ausführung
- [ ] UI: Guss-Vorwarnung mit „🚿 Regen ignorieren", Flag-Setzung, „zu spät"-Hinweis
- [ ] `RAIN_WARNING_LEAD_MINUTES` konfigurierbar
- [ ] `telegram-nachrichten.html` aktualisiert
- [ ] Beads-Issue geschlossen
- [ ] Feature- und Plan-Dokument nach `completed/` verschoben
