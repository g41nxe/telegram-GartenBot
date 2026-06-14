---
name: write-feature-doc
description: Hilft beim Erstellen und Aktualisieren einheitlicher, hochwertiger und benutzerfreundlicher Feature-Leitfäden auf Deutsch im Ordner docs/features/.
---

<what-to-do>

Wenn du aufgefordert wirst, ein Feature zu dokumentieren oder einen neuen Leitfaden zu erstellen, nutze dieses standardisierte Format. Erstelle die Dokumente auf Deutsch im Ordner `docs/features/` mit der Benennung `00XX-feature-name.md`.

Stelle sicher, dass du das folgende Struktur-Template exakt einhältst:

```markdown
# 📅 Leitfaden zur [Feature Name] der Gartenbewässerung

Eine kurze, anschauliche Einführung, was dieses Feature macht, warum es existiert und wie es dem Benutzer hilft.

---

## 1. Übersicht & Funktionsweise
Detaillierte Erklärung der Funktionsweise und der Logik im Hintergrund. Wie arbeitet das System in verschiedenen Szenarien?

## 2. Parameter & Konfiguration
Welche Parameter steuern das Verhalten des Features?

### System-Parameter (Datenbank / API)
*   **[Parameter Name]** (`[code_identifier]`): Beschreibung, Wertebereich, Standardwert und Zweck.
*   **[Parameter Name]** (`[code_identifier]`): ...

### Umgebungsvariablen (`.env`)
*   **[Umgebungsvariable]**: Standardwert und Auswirkung auf das System.

## 3. Befehls-Syntax im Telegram-Bot
Wie bedient der Benutzer dieses Feature im Chat?

### A. [Aktion A]
*   **Befehl / Button**: `/befehl` oder Button-Name.
*   **Beschreibung**: Was passiert bei dieser Aktion?
*   **Beispiel**: `/befehl beispiel_wert`

### B. [Aktion B]
*   ...

## 4. Technische Implementierung (für Entwickler)
Kurzer Abriss für Entwickler, welche Komponenten beteiligt sind:
*   **Module**: Welche Python-Dateien steuern das Feature?
*   **Datenbank**: Welche Spalten/Tabellen werden verwendet?
*   **Schnittstellen**: Welche externen Verbindungen (MQTT, HTTP-APIs) werden genutzt?

## 5. Fehlersuche & Verhalten im Fehlerfall
*   Wie reagiert das Feature bei Verbindungsunterbrechungen (Offline-Fallback)?
*   Typische Log-Meldungen bei Problemen und deren Behebung.
```

</what-to-do>
