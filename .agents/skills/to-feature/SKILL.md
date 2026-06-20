---
name: to-feature
description: Übersetzt den aktuellen Konversations-Kontext und das Codebase-Verständnis in ein strukturiertes Feature-Dokument und speichert dieses als lokale Markdown-Datei im Ordner docs/features/.
---

Dieser Skill nimmt den aktuellen Konversations-Kontext sowie das Verständnis der Codebase und erstellt daraus ein Feature-Dokument. Führe **kein** Interview mit dem Benutzer durch – synthetisiere einfach das, was du bereits weißt.

## Ablauf

1. **Codebase untersuchen**:
   Untersuche das Repository, um den aktuellen Zustand der Codebase zu verstehen. Verwende im gesamten Feature-Dokument die Fachbegriffe aus dem Domain-Glossar (`CONTEXT.md`) und halte dich an bestehende ADRs im betroffenen Bereich.

2. **Test-Nahtstellen (Seams) entwerfen**:
   Skizziere die Nahtstellen (Seams), an denen du das Feature testen wirst. Bevorzuge bestehende Nahtstellen gegenüber neuen. Verwende die am höchsten gelegene Nahtstelle. Müssen neue Nahtstellen geschaffen werden, schlage diese am höchstmöglichen Punkt vor.
   Stimme dich mit dem Benutzer ab, ob diese Nahtstellen seinen Erwartungen entsprechen.

3. **Feature-Dokument lokal speichern**:
   Schreibe das Feature-Dokument unter Verwendung des unten stehenden Templates und speichere es als lokale Markdown-Datei im Verzeichnis `docs/features/` ab.
   
   **Dateinamenskonvention**:
   `docs/features/00XX-feature-name.md` (wobei `00XX` eine fortlaufende Nummer ist, z. B. `docs/features/0001-volume-based-watering.md`). Wähle `00XX` als nächste freie Nummer über alle Docs in `docs/features/` und `docs/features/completed/` hinweg.
   Der Ordner `docs/features/` existiert bereits.

4. **Beads-Issue anlegen**:
   Lege für das neue Feature ein Beads-Issue an, damit die Arbeit im durchsuchbaren Backlog auftaucht und von `implement-feature` (und Sandcastle) gefunden wird:

   ```bash
   bd create --title="<Feature Name>" --type=feature --priority=2 \
     --description="<1–2 Sätze Kurzfassung>. Referenz: docs/features/00XX-feature-name.md"
   ```

   - Die `Referenz:`-Zeile MUSS den exakten Pfad des gerade geschriebenen Feature-Docs enthalten — `implement-feature` und der Sandcastle-Reviewer lesen sie, um die Spec zu finden.
   - Nenne dem Benutzer die erzeugte Issue-ID.
   - Bestehen Abhängigkeiten zu anderen offenen Issues, ergänze sie mit `bd dep add <neues-issue> <blocker>`.

<feature-template>

# Feature: [Feature Name]

## Problemstellung (Problem Statement)

Das Problem, vor dem der Benutzer aus seiner Perspektive steht.

## Lösung (Solution)

Die Lösung des Problems aus der Perspektive des Benutzers.

## User Stories

Eine AUSFÜHRLICHE, nummerierte Liste von User Stories. Jede User Story sollte in folgendem Format vorliegen:

1. Als ein <User> möchte ich <Feature>, um <Nutzen> zu haben.

*Beispiel:*
1. Als Benutzer des Telegram-Bots möchte ich den aktuellen Wasserfluss-Status einsehen können, um sicherzustellen, dass die Bewässerung korrekt läuft.

Diese Liste von User Stories sollte extrem umfangreich sein und alle Aspekte des Features abdecken.

## Implementierungs-Entscheidungen (Implementation Decisions)

Eine Liste der getroffenen Implementierungsentscheidungen. Dies kann Folgendes umfassen:

- Module, die gebaut/geändert werden.
- Schnittstellen dieser Module, die geändert werden.
- Technische Klarstellungen des Entwicklers.
- Architektur-Entscheidungen.
- Schema-Änderungen der Datenbank.
- API-Verträge.
- Spezifische Interaktionen.

Füge KEINE spezifischen Dateipfade oder Code-Snippets ein. Diese können sehr schnell veralten.
*Ausnahme*: Wenn ein Prototyp ein Snippet erzeugt hat, das eine Entscheidung präziser kodiert als Prosa (z. B. Zustandsautomat, Reducer, Schema, Typen-Shape), füge es in die entsprechende Entscheidung ein und erwähne kurz, dass es aus einem Prototyp stammt. Reduziere es auf die entscheidungsrelevanten Teile – keine lauffähige Demo, nur die wichtigen Bits.

## Test-Entscheidungen (Testing Decisions)

Eine Liste der getroffenen Testentscheidungen. Enthält:

- Eine Beschreibung dessen, was einen guten Test ausmacht (nur das externe Verhalten testen, nicht die Implementierungsdetails).
- Welche Module getestet werden.
- Vorarbeiten/Referenzen für die Tests (d. h. ähnliche Testarten in der Codebase).

## Nicht im Leistungsumfang (Out of Scope)

Eine Beschreibung der Dinge, die für dieses Feature-Dokument nicht im Leistungsumfang enthalten sind.

## Weitere Anmerkungen (Further Notes)

Alle weiteren Anmerkungen zum Feature.

</feature-template>
