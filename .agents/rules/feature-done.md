# Definition of Done — Feature-Abschluss

Wenn eine Feature-Implementierung abgeschlossen ist (alle Tests grün, Code committed), MÜSSEN diese Schritte **im selben Commit** erledigt werden, bevor die Arbeit als fertig gilt:

## Pflichtschritte

### 1. Beads-Issue schließen

Ermittle die Issue-ID aus der Feature-Beschreibung oder dem Beads-JSONL:

```bash
# Wenn bd verfügbar:
bd close <issue-id>

# Wenn bd nicht verfügbar (kaputte Installation): JSONL direkt aktualisieren
# .beads/issues.jsonl — Zeile des Issues anpassen:
#   "status": "open"  →  "status": "closed"
#   "updated_at": "<heute ISO8601>"
#   "closed_at": "<heute ISO8601>"
#   "close_reason": "<kurze Beschreibung>"
```

### 2. Feature-Dokument verschieben

```bash
git mv docs/features/<id>-*.md docs/features/completed/
```

### 3. Plan-Dokument verschieben (falls vorhanden)

```bash
git mv docs/plans/<id>-*-plan.md docs/plans/completed/
# Nur wenn die Datei existiert — nicht alle Features haben einen Plan.
```

### 4. Alles in einem Commit

```
git add .beads/issues.jsonl docs/features/completed/ docs/plans/completed/
git commit -m "chore(docs): Feature <id> als abgeschlossen markieren"
```

## Wann greift diese Regel

- Nach dem letzten Feature-Commit, vor dem Push
- Beim `/release`-Prozess: als Vorprüfung — wenn Features in `docs/features/` liegen, deren Beads-Issue aber `closed` ist, sind sie vergessen worden
- Wenn `implement-feature`-Skill zum Einsatz kommt: die letzten Schritte des Skills folgen dieser Checkliste

## Hinweise

- Die Feature-ID steht im Dateinamen (`docs/features/0023-kamera-bild-historie-loeschen.md` → ID `0023`, Issue-Ref im Dokument selbst)
- Nicht alle Features haben eine Beads-Issue — dann nur Schritt 2 und 3
- `docs/features/completed/` und `docs/plans/completed/` müssen bereits existieren (sie tun es)
