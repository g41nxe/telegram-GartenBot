# Implementierungsplan: Kontextsensible Gieß-Hinweise (Feature 0020)

## Referenzen

- Feature-Spec: `docs/features/0020-kontextsensible-giess-hinweise.md`
- Eingriffspunkte: `src/daemon/ui/telegram_ui.py`
- Kernlogik: `src/daemon/adapters/weather.py::should_skip_watering()`
- Bestehende Tests: `tests/ui/test_telegram_ui.py`, `tests/core/test_watering_advice.py`

## Übersicht

Drei Aufrufstellen in `telegram_ui.py` rufen `_watering_ctrl.start_watering(...)` im manuellen Pfad auf:

| Zeile | Kontext |
|---|---|
| ~1172 | `man_custom_volume` — Texteingabe (Wizard Schritt 2, benutzerdefiniertes Volumen) |
| ~1276 | `water_<dur>` Callback — Schnellstart-Buttons |
| ~1493 | `man_vol_<vol>` Callback — Volumenauswahl im Wizard |

Vor jedem dieser Starts wird künftig `should_skip_watering()` aufgerufen. Spricht das Ergebnis dagegen, wird statt des Sofortstarts eine Rückfrage gesendet. Der Benutzer kann bestätigen oder abbrechen.

## Architektur-Entscheidungen

- `should_skip_watering()` liegt in `adapters/weather.py` — die UI darf Adapter direkt lesen (kein Verstoß; Adapter→UI ist erlaubt, nicht umgekehrt)
- Kein neues Event nötig — die Rückfrage ist ein UI-interner Zustand
- Pending-Parameter (dur, vol) werden in `manual_states[chat_id]` mit `step: "man_rain_confirm"` gespeichert
- Neuer Callback-Prefix: `man_rain_go` (Trotzdem gießen), Abbrechen nutzt bestehenden `man_cancel`

## Schritte

### Schritt 1 — Hilfsfunktion `_check_rain_context()` in `telegram_ui.py`

Neue private Funktion, die `should_skip_watering()` aufruft und einen benutzerlesbaren Hinweistext zurückgibt:

```python
def _check_rain_context() -> tuple[bool, str]:
    """Gibt (skip, hinweistext) zurück. skip=True wenn Regen dagegen spricht."""
    try:
        skip, detail = should_skip_watering()
        return skip, detail
    except Exception:
        return False, ""
```

Import von `should_skip_watering` am Dateianfang ergänzen.

### Schritt 2 — Rückfrage-Keyboard und Nachricht

Neue Hilfsfunktion für das Bestätigungs-Keyboard:

```python
def _get_rain_confirm_keyboard() -> dict:
    return {"inline_keyboard": [[
        {"text": "🚿 Trotzdem gießen", "callback_data": "man_rain_go"},
        {"text": "❌ Abbrechen",        "callback_data": "man_cancel"},
    ]]}
```

Nachrichtentext-Vorlage (ADR 0029 — sachlich-klar, konkrete Zahlen aus `detail`):
```
⚠️ *Regen in Sicht*

{detail}

Trotzdem gießen?
```

### Schritt 3 — Aufrufstellen umbauen

An allen drei `start_watering`-Stellen denselben Guard einbauen:

```python
skip, detail = _check_rain_context()
if skip:
    _state_set(manual_states, chat_id, {
        "step": "man_rain_confirm",
        "duration": dur,
        "volume": vol,
    })
    telegram_client.send_message(
        chat_id,
        f"⚠️ *Regen in Sicht*\n\n{detail}\n\nTrotzdem gießen?",
        _get_rain_confirm_keyboard(),
    )
    return
# kein Regen — Guss sofort starten wie bisher
success, response = _watering_ctrl.start_watering(dur, vol, "manual")
```

Beim `water_<dur>`-Callback (Schnellstart, kein Volumen) `vol=0` verwenden — konsistent mit bisherigem Verhalten.

### Schritt 4 — Neuer Callback-Handler `man_rain_go`

In `_process_callback_query` nach dem `man_cancel`-Block:

```python
elif data == "man_rain_go":
    state = _state_get(manual_states, chat_id)
    if state and state.get("step") == "man_rain_confirm":
        dur = state["duration"]
        vol = state["volume"]
        _state_del(manual_states, chat_id)
        telegram_client.answer_callback_query(cb_id, "Starte Bewässerung...")
        if _watering_ctrl:
            success, response = _watering_ctrl.start_watering(dur, vol, "manual")
        else:
            success, response = False, "Guss-Steuerung nicht initialisiert."
        if not success:
            telegram_client.send_message(chat_id, f"❌ Fehler: {response}", get_main_keyboard())
    else:
        telegram_client.answer_callback_query(cb_id, "Sitzung abgelaufen.")
        telegram_client.send_message(chat_id, "❌ Sitzung abgelaufen.", get_main_keyboard())
```

### Schritt 5 — Tests in `tests/ui/test_telegram_ui.py`

Neue Testklasse `TestRainContextWarning`:

| Test | Was geprüft wird |
|---|---|
| `test_rain_context_shows_confirmation` | Bei `should_skip_watering()=True` wird Rückfrage gesendet, kein `start_watering`-Aufruf |
| `test_no_rain_context_starts_directly` | Bei `should_skip_watering()=False` startet Guss direkt ohne Rückfrage |
| `test_rain_go_callback_starts_watering` | `man_rain_go`-Callback ruft `start_watering` mit gespeicherten Werten auf |
| `test_rain_cancel_aborts` | `man_cancel` nach Rückfrage löscht State, kein `start_watering` |
| `test_rain_go_expired_session` | `man_rain_go` ohne gültigen State → Fehlermeldung, kein Crash |
| `test_hint_contains_mm_values` | Hinweistext enthält konkrete mm-Werte aus `should_skip_watering()` |

Mocking: `should_skip_watering` via `unittest.mock.patch` auf `True`/`False` setzen.
Alle drei Aufrufpfade (Schnellstart, Wizard Dauer→Volumen, Custom-Texteingabe) testen.

## Dateien geändert

- `src/daemon/ui/telegram_ui.py` — Hilfsfunktionen + Guard + neuer Callback-Handler
- `tests/ui/test_telegram_ui.py` — neue Testklasse

## Definition of Done

- [ ] Alle neuen Tests grün
- [ ] Bestehende Tests unverändert grün
- [ ] Coverage nicht regriert (`.\scripts\run_coverage.ps1`)
- [ ] `telegram-nachrichten.html` um Rückfrage-Nachricht ergänzt
- [ ] Manuelle Smoke-Tests durch Benutzer bestätigt
