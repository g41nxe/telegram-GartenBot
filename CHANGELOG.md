## v1.1.2 — 2026-06-14

- Architektur-Bereinigung: Scheduler-Fassade über Guss-Steuerung aufgelöst
- `telegram_bot.py` Pass-Through entfernt, Verdrahtung direkt in `main.py`
- `send_daily_report()` entkoppelt: kein sleep/MQTT-Prefetch mehr im Adapter
- README und CLAUDE.md auf aktuellen Modulstand gebracht

---

## v1.1.1 — 2026-06-14

- OTA-Bestätigung per Telegram nach erfolgreichem Update
- Release-Build zeigt jetzt die korrekte Versionsnummer

---

## v1.1.0 — 2026-06-14

- Wetterchart zeigt jetzt 2h Vergangenheit + 22h Vorhersage
- Regenschwelle auf 2.0mm gesenkt (konfigurierbar via RAIN_THRESHOLD_MM)
- Tagesbericht: Leerzeilen zwischen den Abschnitten

---

## v1.0.1 — 2026-06-14

- Wassermengenmessung korrigiert (SWV-ZFE meldet Liter, nicht L/min)

---

## 2026-06-14

- Release-Notes im /update-Dialog (aus CHANGELOG.md)
- Automatische Telegram-Benachrichtigung nach Update (Erfolg und Rollback)
- /release-Skill für geführten Release-Workflow
- Gieß-Empfehlung berücksichtigt jetzt auch Regen der letzten 24h
- Wetterchart-Verbesserungen (0°-Linie, sauberere Labels)

---
