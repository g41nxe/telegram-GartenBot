# Testpläne

Manuelle Feld-/Abnahme-Testpläne — prüfen am echten Pi (Hardware, MQTT, Wetter, Telegram),
was die automatisierten Tests nicht abdecken. Zwei Formate je Plan, wo vorhanden:

- **`.html`** — interaktive Checkliste (abhakbar, Fortschritt bleibt im Browser gespeichert).
- **`.md`** — portable Fassung, direkt im Repo les- und greifbar.

| Plan | Umfang |
|------|--------|
| `testplan-v1.19.0-wizard-engine` | Release-Abnahme v1.19.0: einheitliche Wizard-Engine, alle 8 Bot-Dialoge |
| `testplan-cy1-zeitplan-pilot` | cy1-Pilot: Zeitplan-Assistent (Parität + ADR-0039-Fix), vor der vollen Migration |
| `testplan-v1.18.1-feldtest` | Feld-Session v1.18.1: verhaltenserhaltende Refactors + ccc/6l3-Änderungen |
