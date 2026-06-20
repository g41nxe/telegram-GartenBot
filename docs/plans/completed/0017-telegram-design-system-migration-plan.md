# Plan: Feature 0017 — Telegram Design-System Migration

## Kontext

Reine Präsentations-Migration: Wortlaut, Formatierung und Aufbau aller Telegram-Nachrichten werden auf ADR 0029 gebracht.
**Keine Logik-, Event- oder Callback-Daten-Änderungen.**

Verbindliche Grundlage: `docs/design/telegram-design-system.html` (SOLL).

---

## Betroffene Dateien

| Datei | Änderungstyp |
|---|---|
| `src/daemon/ui/telegram_ui.py` | Helfer + `/status` + Nachrichten + Routing |
| `src/daemon/adapters/daily_report.py` | Tagesbericht-Texte |
| `tests/ui/test_telegram_ui.py` | Neue Tests |
| `tests/adapters/test_daily_report.py` | Neue Tests |
| `docs/design/telegram-nachrichten.html` | IST-Referenz aktualisieren |

---

## Schritt 1 — RED: Garten-Ampel Helfer

**Neue Tests in `tests/ui/test_telegram_ui.py`:**

```python
class TestGartenAmpel(unittest.TestCase):

    def test_gruen_wenn_alle_geraete_ok(self):
        """Alles grün: Dienste online, Batterie OK, LQI OK, kein Watchdog."""
        ...
        self.assertEqual(_garden_ampel_level(...), "green")

    def test_gelb_bei_niedriger_batterie(self):
        """Gelb wenn Batterie <= BATTERY_WARNING_THRESHOLD."""
        ...
        self.assertEqual(_garden_ampel_level(...), "yellow")

    def test_gelb_bei_kritischem_lqi(self):
        """Gelb wenn LQI < 60."""
        ...
        self.assertEqual(_garden_ampel_level(...), "yellow")

    def test_rot_wenn_dienst_offline(self):
        """Rot wenn services_ok=False."""
        ...
        self.assertEqual(_garden_ampel_level(...), "red")

    def test_rot_bei_watchdog_alarm(self):
        """Rot wenn valve['watchdog_active'] == True."""
        ...
        self.assertEqual(_garden_ampel_level(...), "red")

    def test_rot_gewinnt_ueber_gelb(self):
        """Wenn ein Gerät rot und ein anderes gelb: Gesamtergebnis rot."""
        ...
        self.assertEqual(_garden_ampel_level(...), "red")
```

**Neue Funktion in `telegram_ui.py`:**

```python
def _garden_ampel_level(valves: list, services_ok: bool) -> str:
    """Gibt 'green', 'yellow' oder 'red' zurück (schlimmste Stufe gewinnt)."""
    from .. import config as _cfg
    threshold = getattr(_cfg, "BATTERY_WARNING_THRESHOLD", 20)

    if not services_ok:
        return "red"
    worst = "green"
    for v in valves:
        if v.get("watchdog_active") or v.get("valve_abnormal_state"):
            return "red"
        battery = v.get("battery") or 100
        lqi = v.get("linkquality") or 100
        if battery <= threshold or lqi < 60:
            worst = "yellow"
    return worst
```

→ Tests rot laufen lassen, dann Funktion implementieren, Tests grün.

---

## Schritt 2 — RED: `/status` Migration + Progressive Disclosure

**Neue Tests in `TestStatusCommand`:**

```python
def test_status_headline_gruen(self):
    """Headline enthält 'Alles im grünen Bereich' wenn alles ok."""
    ...

def test_status_headline_rot(self):
    """Headline enthält 'Es gibt ein Problem' wenn Dienst offline."""
    ...

def test_status_ventil_kompakt_wenn_gruen(self):
    """Grünes Ventil: nur Name + Status-Indikatoren, keine ID/LQI-Zahl."""
    ...

def test_status_ventil_aufgeklappt_wenn_rot(self):
    """Nicht-grünes Ventil: enthält mqtt_name (ID) und LQI-Zahl."""
    ...

def test_status_keine_sekunden_in_zeitstempel(self):
    """Zeitstempel im Status enthalten keine ':SS'-Sekunden."""
    ...

def test_status_uhr_suffix(self):
    """Zeitangaben enden mit ' Uhr'."""
    ...

def test_no_double_asterisk_in_status(self):
    """Status-Nachricht enthält kein **."""
    ...
```

**Umbau `handle_status()` in `telegram_ui.py`:**

```
Titel:     🌱 *Dein Garten auf einen Blick*
Datum:     Mi, 18.06. · 14:32 Uhr

Headline:  🟢 Alles im grünen Bereich — Dienste online
           🟡 N Gerät(e) brauchen Aufmerksamkeit
           🔴 Es gibt ein Problem

📡 *Ventile*
  Grün:    Terrasse · 🟢 aktiv · 🔋 voll · 📶 gut
  Gelb/Rot:
    🟡 Terrasse — seit 2.5 h kein Signal
       🔋 18 % · 📶 kritisch (48 LQI)
       Letztes Signal: 17.06. um 12:18 Uhr
       ID: garden_valve

📷 *Kameras*
  Grün:    Nordseite · 🟢 14:15 Uhr
  Offline: 🔴 Nordseite — seit 2.5 h kein Bild

🌡 *Wetter*   leicht bewölkt, 22.4 °C · 💧 0 mm
   _später 15 Uhr: bedeckt, 0.2 mm (15 %)_

📜 *Zuletzt*  ✅ 06:00 Rasen (12 Min)
_v1.2.1_
```

Helfer-Funktionen:
```python
def _format_valve_compact(valve: dict) -> str: ...
def _format_valve_expanded(valve: dict) -> str: ...
def _format_camera_compact(cam: dict) -> str: ...
def _format_camera_expanded(cam: dict) -> str: ...
def _status_headline(level: str, services_ok: bool) -> str: ...
```

---

## Schritt 3 — Regression-Test: Kein `**` in erzeugten Nachrichten

**Ein neuer Test in `tests/ui/test_telegram_ui.py`:**

```python
def test_keine_doppelten_asterisken_in_irgendeiner_nachricht(self):
    """Kein Nachrichten-erzeugendes Handle gibt ** zurück (Markdown-Regression)."""
    # Prüft alle collected send_message-Aufrufe der wichtigsten Handler
    ...
    for call in mock_client.send_message.call_args_list:
        text = call[0][1] if len(call[0]) > 1 else call.kwargs.get("text", "")
        self.assertNotIn("**", text, f"Doppel-Asterisk gefunden: {text[:80]}")
```

**Danach globale `**` → `*` Korrektur in `telegram_ui.py`:**

- Alle `**Text**` → `*Text*` (manuelle Review, da manche `**` auch in Code-Spans stehen)
- `🌤️` in history_text → `🌧`
- `🌤️ **Wetter:**` → `🌡 *Wetter*`
- `📜 **Letzte Zyklen:**` → `📜 *Zuletzt*`
- Sekunden aus `%H:%M:%S` → `%H:%M` und `+ " Uhr"` wo passend

---

## Schritt 4 — Hauptmenü-Buttons + Routing

**Tests:**
```python
def test_hauptmenue_hat_guss_button(self):
    kb = get_main_keyboard()
    texts = [b["text"] for row in kb["keyboard"] for b in row]
    self.assertIn("🚿 Bewässern starten", texts)
    self.assertNotIn("🟢 Bewässern starten", texts)

def test_hauptmenue_hat_stopp_button(self):
    kb = get_main_keyboard()
    texts = [b["text"] for row in kb["keyboard"] for b in row]
    self.assertIn("🛑 Sofort Stopp", texts)
    self.assertNotIn("🔴 Sofort Stopp", texts)
```

**Änderungen:**
- `get_main_keyboard()`: `"🟢 Bewässern starten"` → `"🚿 Bewässern starten"`, `"🔴 Sofort Stopp"` → `"🛑 Sofort Stopp"`
- Routing in `_process_message()`: alter Text + neuer Text beide matchen (Rückwärtskompatibilität während Rollout)
- Whitelist in den `text.startswith("/") or text in [...]`-Guards aktualisieren

---

## Schritt 5 — Ereignis-Benachrichtigungen

**Tests in `TestEventNotifications`:**
```python
def test_watering_started_format(self):
    """Guss-gestartet enthält '🚿' und '*Wasser marsch!*'."""
    ...

def test_watering_completed_volume_format(self):
    """Volumenlimit-Abschluss enthält '🏁' und die Literzahl mit ' l'."""
    ...

def test_watering_skipped_uses_regen_emoji(self):
    """Regen-Skip enthält 🌧, nicht 🌤️."""
    ...

def test_watchdog_alarm_sachlich(self):
    """Watchdog-Alarm enthält '⚠️' und Gerätename."""
    ...
```

**Änderungen in `telegram_ui.py`:**

| Funktion | Vorher | Nachher |
|---|---|---|
| `_on_watering_started` | `🟢 **Bewässerung gestartet!**` | `🚿 *Wasser marsch!*` |
| `_on_watering_completed` (Volumen) | `🏁 **Wassermenge erreicht!**` | `🏁 *Fertig — X l sind durch*` |
| `_on_watering_completed` (Zeit) | `🏁 **Zeitlimit erreicht!**` | `🏁 *Zeitlimit erreicht*` |
| `_on_watering_stopped` | (aktuell) | `🛑 *Guss gestoppt*` |
| `_on_watering_failed` | `⚠️ **Notfall-Abschaltung ausgelöst!**` | `⚠️ *Notfall-Abschaltung*` |
| `_on_watering_skipped` | `🌤️ **Zeitplan ... übersprungen!**` | `🌧 *Heute übernimmt der Regen*` |
| `_on_schedule_failed` | (aktuell) | `⚠️ *Zeitplan "..." fehlgeschlagen*` |
| Watchdog-Alarm | (aktuell) | `⚠️ *Ventil "..." meldet sich nicht*` |
| Watchdog-Entwarnung | (aktuell) | `🟢 *... ist wieder da*` |

---

## Schritt 6 — Zeitplan-Assistent & Manuelle Bewässerung

**Tests:** Headline-Format, keine `**`, korrekte Register.

**Wichtigste Änderungen:**
- Alle Schritte-Titel: `**Neuen Zeitplan ... (Schritt X/6)**` → `🆕 *Neuer Zeitplan — Schritt X/6*`
- Manuelle Bewässerung: `🟢 **Manuelle Bewässerung starten (Schritt X/2)**` → `🚿 *Bewässern starten — Schritt X/2*`
- Assistenten-Abschluss: `✅ Gespeichert — Zeitplan "..." ist aktiv.`
- Lösch-Bestätigung: `🗑️ *Zeitplan löschen*` + sachlicher Text
- `/start`: `👋 *Willkommen in deinem Garten!*`
- Unbekannter Befehl: `🤔 *Das kenne ich nicht*`

---

## Schritt 7 — `daily_report.py` Migration

**Tests in `tests/adapters/test_daily_report.py`:**
```python
def test_daily_report_kein_doppelasterisk(self):
    """Tagesbericht enthält kein **."""
    ...

def test_daily_report_headline_format(self):
    """Tagesbericht beginnt mit '🌱 *Guten Morgen'."""
    ...
```

**Änderungen:**
- Titel: `📊 **Täglicher Statusbericht vom ...**` → `🌱 *Guten Morgen — dein Tagesbericht*`
- Alle `**` → `*`
- Watchdog-Warnungen: `🚨 **...**` → `⚠️ *...*`
- Garten-Ampel Headline am Ende des Berichts

---

## Schritt 8 — IST-Referenz aktualisieren

`docs/design/telegram-nachrichten.html` vollständig auf das neue Format bringen.
Jede Sprechblase zeigt die neuen Texte, Quellfunktion annotiert.

---

## Verifikation nach jedem Schritt

```powershell
python -m unittest discover -v tests
```

Nach Abschluss aller Schritte:
```powershell
.\scripts\run_coverage.ps1
```

Coverage darf nicht regredieren.
