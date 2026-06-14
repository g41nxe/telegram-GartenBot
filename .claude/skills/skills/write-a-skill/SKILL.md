---
name: write-a-skill
description: Hilft beim Entwerfen, Strukturieren, Schreiben und Installieren neuer Agenten-Skills im Ordner .agents/skills/ nach den Qualitätsstandards des Projekts.
---

Dieser Skill unterstützt den Agenten dabei, neue Fähigkeiten (Skills) für das Gartenbewässerungs-System zu entwerfen, zu schreiben und im Projekt zu installieren. Jede neue Fähigkeit muss hohen Qualitätsansprüchen genügen und sich nahtlos in die bestehenden Agenten-Werkzeuge einfügen.

## Ablauf

### 1. Bedarfsanalyse & Konzeption (Dialog mit dem Benutzer)
Bevor Code oder Dokumente geschrieben werden, kläre im Dialog mit dem Benutzer folgende Aspekte:
- **Zielsetzung**: Welches konkrete Problem löst der neue Skill?
- **Zielgruppe/Kontext**: Wann wird dieser Skill getriggert? (Z. B. bei bestimmten Befehlen, Refactoring-Phasen, Deployment-Schritten).
- **Abhängigkeiten**: Greift der Skill auf externe APIs, lokale Skripte (z. B. PowerShell/Bash) oder spezifische Ordner zu?
- **Sprachregelung**: Der Skill muss auf Deutsch dokumentiert werden (sofern nicht anders gewünscht) und die Fachbegriffe aus `CONTEXT.md` (z. B. "Steuerzentrale", "Ventil", "Funk-Koordinator") zwingend korrekt verwenden.

### 2. Struktur eines Skills festlegen
Ein Agenten-Skill befindet sich immer im Verzeichnis `.agents/skills/<skill-name>/` und besteht aus:
- **`SKILL.md` (Pflicht)**: Die Hauptinstruktion für den Agenten mit YAML-Metadaten.
- **Hilfsdateien (optional)**: Zusätzliche Markdown-Dateien für komplexe Leitfäden (wie `mocking.md` oder `tests.md` bei TDD) oder Skripte.

### 3. Schreiben der `SKILL.md` (Unter Verwendung des Templates)
Erstelle die `SKILL.md` nach folgendem standardisierten Aufbau:

```markdown
---
name: [skill-name-kebab-case]
description: [Kurze, prägnante Beschreibung auf Deutsch für die Skill-Liste]
---

# [Skill Name in Headline-Schreibweise]

[Eine kurze Einführung, was dieser Skill macht und in welchem Kontext er dem Agenten hilft.]

## Ablauf / Prozess

Schritt-für-Schritt-Prozess, den der Agent ausführen muss, wenn dieser Skill aktiv ist:

1. **[Schritt 1]**:
   Detaillierte Handlungsanweisung. Welche Dateien müssen analysiert werden? Welche Regeln gelten?
   
2. **[Schritt 2]**:
   Interaktion mit dem Benutzer oder Ausführung von Befehlen.
   
3. **[Schritt 3]**:
   Ergebnissicherung und Verifikation.

## Richtlinien & Best Practices

- **Regel 1**: Verwendung der korrekten Domain-Begriffe gemäß `CONTEXT.md`.
- **Regel 2**: Keine Annahmen treffen, im Zweifel Benutzer fragen.
- **Regel 3**: [Spezifische technische Vorgaben für diesen Skill]

<optional-section-name>
(Optional: Z. B. Templates für Ausgaben, Code-Beispiele oder spezifische Fehlersuch-Prozeduren)
</optional-section-name>
```

### 4. Qualitätssicherung & Terminologie-Check
Prüfe den Entwurf des neuen Skills vor der finalen Installation gegen folgende Kriterien:
- [ ] Enthält die Datei korrekte YAML-Metadaten (`name` und `description`) am Anfang?
- [ ] Entspricht der Verzeichnisname exakt dem `name`-Feld im YAML-Header?
- [ ] Werden verbotene Begriffe vermieden (z. B. "Pi" -> "Steuerzentrale", "Schalter" -> "Ventil")?
- [ ] Sind alle Verweise auf lokale Skripte oder Hilfsdateien absolut oder relativ korrekt aufgelöst?

### 5. Installation
- Erstelle das Verzeichnis `.agents/skills/<skill-name>/`.
- Schreibe die `SKILL.md` und eventuelle Hilfsdateien hinein.
- Aktualisiere ggf. den Implementierungsplan/die Dokumentation des Projekts, um den neuen Skill vorzustellen.
