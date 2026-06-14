---
name: release
description: Führt durch den Release-Prozess — vergleicht release..master, liest neue Feature-Docs, schlägt CHANGELOG-Eintrag vor, bestimmt automatisch die nächste Versionsnummer, committet, taggt und pusht den Release-Branch.
---

Du bist auf dem `master`-Branch. Führe die folgenden Schritte der Reihe nach aus.

## Schritt 1: Änderungen seit letztem Release ermitteln

Führe aus:
- `git log release..master --oneline` — alle Commits seit letztem Merge
- `git diff release..master --name-only -- docs/features/completed/` — neu abgeschlossene Features

Lies nur die Feature-Dokumente, deren Implementierung tatsächlich in `git log release..master` auftaucht — d.h. es muss ein `feat:`-Commit in diesem Range existieren, der inhaltlich zum Dokument passt. Feature-Dokumente, die im Diff erscheinen, aber keinen passenden `feat:`-Commit haben, werden ignoriert (sie wurden vermutlich nur verschoben, nicht jetzt implementiert).

## Schritt 2: Nächste Version bestimmen

Ermittle den letzten Tag:
```bash
git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0"
```

Bestimme den Bump anhand der Änderungen:
- **Minor** (`v1.X.0`): Mindestens ein neues Feature in `docs/features/completed/` oder ein `feat:`-Commit
- **Patch** (`v1.0.X`): Nur Fixes, Chores, Docs

Schlage die neue Version vor und erkläre die Begründung in einem Satz. Warte auf Bestätigung oder Korrektur durch den Benutzer.

## Schritt 3: Changelog-Vorschlag erstellen

Synthetisiere aus Feature-Titeln und Commit-Messages einen Changelog-Vorschlag:

```
## vX.Y.Z — YYYY-MM-DD

- <Stichpunkt 1>
- <Stichpunkt 2>
```

Halte Stichpunkte kurz (max. 80 Zeichen) und benutzerfreundlich. Warte auf Bestätigung oder Korrekturen.

## Schritt 4: CHANGELOG.md aktualisieren

Füge den bestätigten Eintrag am Anfang von `CHANGELOG.md` ein, gefolgt von `---`. Bestehende Einträge bleiben unberührt.

## Schritt 5: Committen, taggen und pushen

```bash
git add CHANGELOG.md
git commit -m "chore: Release vX.Y.Z"
git tag vX.Y.Z
git push origin master:release
git push origin vX.Y.Z
```

Melde dem Benutzer: „Release vX.Y.Z ausgelöst — du erhältst eine Telegram-Benachrichtigung wenn das Build fertig ist."
