---
name: release
description: Führt durch den Release-Prozess — vergleicht release..master, liest neue Feature-Docs, schlägt CHANGELOG-Eintrag vor, committet und pusht den Release-Branch.
---

Du bist auf dem `master`-Branch. Führe die folgenden Schritte der Reihe nach aus.

## Schritt 1: Änderungen seit letztem Release ermitteln

Führe aus:
- `git log release..master --oneline` — alle Commits seit letztem Merge
- `git diff release..master --name-only -- docs/features/completed/` — neu abgeschlossene Features

Lies die neuen Feature-Dokumente vollständig. Notiere Titel und Kernaussage jedes neuen Features.

## Schritt 2: Changelog-Vorschlag erstellen

Synthetisiere aus Feature-Titeln und Commit-Messages einen Changelog-Vorschlag:

```
## YYYY-MM-DD

- <Stichpunkt 1>
- <Stichpunkt 2>
```

Verwende das heutige Datum. Halte Stichpunkte kurz (max. 80 Zeichen) und benutzerfreundlich — keine technischen Dateinamen oder Commit-Hashes.

Zeige dem Benutzer den Vorschlag und warte auf Bestätigung oder Korrekturen.

## Schritt 3: CHANGELOG.md aktualisieren

Füge den bestätigten Eintrag am Anfang von `CHANGELOG.md` ein, gefolgt von `---` auf eigener Zeile. Bestehende Einträge bleiben unberührt.

Format:
```
## YYYY-MM-DD

- Stichpunkt

---

## (vorheriger Eintrag)
...
```

## Schritt 4: Committen und pushen

```bash
git add CHANGELOG.md
git commit -m "chore: Release YYYY-MM-DD"
git push origin master:release
```

Melde dem Benutzer: „Release ausgelöst — du erhältst eine Telegram-Benachrichtigung wenn das Build fertig ist."
