---
name: feedback-release-cycle
description: Nicht direkt auf den Pi deployen — es gibt einen separaten Release-Zyklus via git push origin main:release
metadata: 
  node_type: memory
  type: feedback
  originSessionId: afaafa50-33d1-417c-801d-524486fe3f03
---

Nicht direkt per SCP/SSH auf den Pi deployen — das Projekt hat einen separaten Release-Zyklus.

**Why:** Ab 2026-06-14 gibt es einen OTA-Release-Prozess (Feature 0011/0012): `git push origin main:release` triggert eine CI-Pipeline, die ein Release-Archiv baut. Der Pi lädt das Update via `/update`-Befehl im Telegram-Bot.

**How to apply:** Nach einem Commit niemals automatisch `scp` oder `ssh systemctl restart` ausführen. Stattdessen den Benutzer darauf hinweisen dass die Änderung committed ist und beim nächsten Release auf den Pi kommt. Der deploy-garden Skill bleibt als manueller Fallback erhalten (z.B. für Notfälle oder Erstsetup), soll aber nicht proaktiv angeboten werden.
