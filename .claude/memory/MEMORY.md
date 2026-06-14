# Memory Index

- [Project overview](project_overview.md) — garden irrigation daemon on Raspberry Pi Zero W; Python, Hexagonal Architecture, Zigbee via MQTT, Telegram bot
- [Architecture decisions session 2026-06-11](project_adr_session_20260611.md) — ADRs 0016 and 0017 written; ARCHITECTURE.md and enforcement rules updated after refactor
- [Feature 0006 Implementierungsstand](project_feature_0006_status.md) — Multi-Ventil: Schritte 1–6 abgeschlossen (75/75 Tests grün), Schritte 7–9 (scheduler, daily_report, telegram_ui) ausstehend
- [QuickChart.io version requirement](project_quickchart_version.md) — POST payload must include `"version": "4"` for Chart.js v3+ syntax; omitting it causes HTTP 400
- [Deployment pattern](project_deployment_pattern.md) — Python/DB changes: restart service only; setup.sh is first-time OS setup only
- [Release-Zyklus: kein direktes Deployment](feedback_release_cycle.md) — Änderungen warten auf Release via git push origin main:release; deploy-garden Skill nur als Notfall-Fallback
- [QuickChart.io Einschränkungen](project_quickchart_version.md) — version "4" Pflicht; JS-Formatter in datalabels werden nicht ausgeführt
