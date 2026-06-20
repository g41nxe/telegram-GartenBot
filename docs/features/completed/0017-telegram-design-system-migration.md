# Feature: Telegram Design-System — Migration des Bestands

## Problemstellung (Problem Statement)

Die Nachrichten des Telegram-Bots sind organisch gewachsen und uneinheitlich: gemischte Anrede („du" vs. „Sie"), uneinheitliche Überschriften, zwei Benachrichtigungs-Titel-Muster, gemischte Datums- und Einheitenformate, drei Listenstile und mehrfach belegte Emojis. Zusätzlich nutzt der Bestand `**fett**`, was im verwendeten `parse_mode: "Markdown"` (Legacy) kein gültiges Format ist und nur durch die Nachsicht des Parsers nicht sichtbar bricht. Der Benutzer erlebt dadurch keine einheitliche Experience.

## Lösung (Solution)

Alle bestehenden benutzersichtbaren Nachrichten in `telegram_ui.py`, `daily_report.py`, `valve_pairing.py` und `camera_pairing.py` werden in einem zusammenhängenden, testbaren Schritt auf das in ADR 0029 festgelegte Design-System umgestellt. Das Zielbild ist in `docs/design/telegram-design-system.html` (SOLL) dokumentiert, der vollständige Ist-Stand in `docs/design/telegram-nachrichten.html` (IST). Die Migration verändert ausschließlich Wortlaut, Formatierung und Aufbau der Nachrichten — keine Steuerungslogik, keine Event-Verträge, keine Tastatur-Callbacks (mit Ausnahme der zwei umbenannten Hauptmenü-Buttons).

## User Stories

1. Als Benutzer möchte ich, dass der Bot mich durchgängig mit „du" anspricht, damit die Kommunikation persönlich und konsistent wirkt.
2. Als Benutzer möchte ich, dass jede Nachricht demselben Aufbau folgt (Überschrift, Felder, Einheiten), damit ich Informationen schnell und vorhersehbar erfasse.
3. Als Benutzer möchte ich, dass Fett-/Kursivformatierung korrekt dargestellt wird, ohne sichtbare Sternchen oder kaputte Formatierung.
4. Als Benutzer möchte ich, dass positive Nachrichten freundlich-verspielt klingen, Warnungen und Fehler aber sachlich und klar bleiben.
5. Als Benutzer möchte ich in `/status` zuerst eine Gesamteinschätzung (Garten-Ampel) sehen und technische Details nur, wenn ein Gerät ein Problem hat.
6. Als Benutzer möchte ich einheitliche Datums-/Zeitangaben (ohne Sekunden, mit „Uhr") und Einheiten (mit Leerzeichen), damit nichts gemischt wirkt.
7. Als Benutzer möchte ich im Hauptmenü Buttons sehen, deren Symbole nicht mit den Status-Ampelfarben kollidieren.
8. Als Benutzer möchte ich, dass jedes Emoji im Nachrichtentext genau eine Bedeutung hat, damit ich Symbole intuitiv lese.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Verbindliche Grundlage:** ADR 0029. Das SOLL-Referenzdokument dient als visuelle Vorlage, die IST-Referenz als vollständige Inventarliste der zu migrierenden Nachrichten.
- **Markdown:** Durchgängig Legacy-`Markdown`. Fett `*einfach*`, Kursiv `_unterstrich_`. Alle `**…**` werden ersetzt. Bestehende Escaping-Stellen (Release-Notes) bleiben.
- **Anrede & Ton-Register:** „du" überall. Drei Register (verspielt / neutral-freundlich / sachlich-klar) gemäß ADR 0029, jeder Nachrichtentyp gehört genau einem an. Keine Vermenschlichung.
- **Überschriften:** Genau ein Format `*<Emoji> Titel*` (ein Emoji, kein Doppelpunkt). Schluss-„!" nur im verspielten Register.
- **Garten-Ampel & Progressive Disclosure:** `/status` erhält eine Headline mit der schlimmsten aktiven Stufe (🟢/🟡/🔴). Technische Werte (LQI-Zahl, `mqtt_name`/Geräte-ID, exakte Zeitstempel) werden nur für nicht-grüne Geräte eingeblendet. Die Stufen-Auslöser nutzen vorhandene Signale (`BATTERY_WARNING_THRESHOLD`, LQI < 60, Watchdog-Flag, `valve_abnormal_state`, Broker-/Bridge-Status).
- **Einheiten & Zeit:** Leerzeichen vor Einheit (`22.4 °C`, `1.4 mm`, `25 l`, `87 %`); Dezimal-Punkt bleibt. Zeiten ohne Sekunden, mit „Uhr"; Relativzeit in Klammern.
- **Hauptmenü-Buttons:** 🚿 „Bewässern starten" und 🛑 „Sofort Stopp" ersetzen 🟢/🔴, damit die Ampelfarben dem Gesundheits-Status vorbehalten bleiben. Die Button-Texte selbst und ihre Routing-Bedingungen in `_process_message` bleiben unverändert (Erkennung über den Text inkl. neuer Emojis).
- **Regen-Skip-Emoji:** 🌧 statt 🌤️.
- **Kein Logik-Eingriff:** Event-Typen, Callback-Daten, Wizard-Schrittlogik und DB bleiben unangetastet. Reines Präsentations-Refactoring.
- **Hilfsfunktionen:** Wiederkehrende Formatierungen (z. B. Ampel-Headline, Geräte-Zeile kompakt vs. aufgeklappt) werden in kleine Helfer in der UI-Schicht ausgelagert, um Konsistenz zu erzwingen und Tests zu erleichtern.

## Test-Entscheidungen (Testing Decisions)

- **Was ein guter Test prüft:** Beobachtbares Verhalten der erzeugten Texte — enthält eine Nachricht die korrekte Überschrift/Register/Markdown-Konvention, zeigt `/status` die richtige Ampelstufe, blendet Progressive Disclosure die Technik nur im Problemfall ein. Nicht: exakte Wortgleichheit ganzer Sätze (zu spröde).
- **Test-Nahtstelle (Seam):** Die bestehenden UI-Tests (`tests/ui/test_telegram_ui.py`) und Tagesbericht-Tests (`tests/adapters/test_daily_report.py`). Nachrichten-erzeugende Funktionen liefern Strings zurück bzw. rufen ein gemocktes `telegram_client`; Tests prüfen Teilstrings/Strukturmerkmale.
- **Negativ-Prüfung Markdown:** Ein Test stellt sicher, dass keine erzeugte Nachricht `**` enthält (Regression-Schutz für den Legacy-Markdown-Bug).
- **Garten-Ampel:** Tabellengetriebene Tests für die Stufen-Auslöser (grün/gelb/rot) und die Auswahl der schlimmsten Stufe.
- **Progressive Disclosure:** Tests, dass technische Werte bei grünem Gerät fehlen und bei nicht-grünem Gerät erscheinen.
- **Referenz-Abgleich:** Nach der Migration wird die IST-Referenz (`telegram-nachrichten.html`) auf das neue Aussehen aktualisiert (Pflicht laut `.claude/rules/telegram_messages.md`).
- **TDD & Coverage:** Rot-Grün-Refaktor pro Helfer; Coverage darf nicht regredieren.

## Nicht im Leistungsumfang (Out of Scope)

- **Aktionsfähige Benachrichtigungen** (Inline-Buttons in Push-Nachrichten) — eigenes Feature.
- **Neue Funktionalität** jeglicher Art: keine neuen Befehle, keine neuen Datenfelder, keine Logikänderungen.
- **Migration auf MarkdownV2** — bewusst verworfen (ADR 0029).
- **Telegram-Befehlsmenü** (`setMyCommands`) — separat zu betrachten.

## Weitere Anmerkungen (Further Notes)

- Grundlage: ADR 0029. Referenzdokumente: `docs/design/telegram-design-system.html` (SOLL), `docs/design/telegram-nachrichten.html` (IST).
- Der neue Domänenbegriff **Garten-Ampel** ist in `CONTEXT.md` definiert.
- Da viele Format-Strings betroffen sind, empfiehlt sich eine Migration in Etappen pro Modul/Nachrichtengruppe, jeweils mit grünen Tests, um die Änderung überschaubar und überprüfbar zu halten.
