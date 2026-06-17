# 29. Telegram Design-System / Nachrichten-Konventionen

Wir legen ein verbindliches Design-System für alle Nachrichten des Telegram-Bots fest, um eine einheitliche Benutzererfahrung zu schaffen.

## Kontext

Die Bot-Nachrichten sind über die Zeit organisch gewachsen und uneinheitlich geworden: gemischte Anrede („du" vs. „Sie"), uneinheitliche Überschriften, zwei Benachrichtigungs-Titel-Muster, gemischte Datums- und Einheitenformate, drei verschiedene Listenstile sowie mehrfach belegte Emojis. Zusätzlich nutzt der Bestand `**fett**`, was im verwendeten `parse_mode: "Markdown"` (Legacy) kein gültiges Format ist und nur durch die Nachsicht des Parsers nicht sichtbar bricht.

## Entscheidung

**Markdown-Konvention.** Wir bleiben bei Legacy-`Markdown`. Fett ist ausschließlich `*einfach*`, Kursiv `_unterstrich_`, Monospace `` `backticks` ``. `**doppelt**` ist verboten und wird im Bestand korrigiert. Zu escapen sind nur `_ * \` [`.

**Anrede & Ton.** Durchgängig „du". Drei feste Ton-Register, jeder Nachrichtentyp gehört genau einem an:
- **Verspielt** (Garten-Energie, darf ein einzelnes „!" tragen): Guss gestartet/fertig, Regen-Skip, Tagesbericht-Einstieg, Zeitplan gespeichert, Foto.
- **Neutral-freundlich** (klar & „du", kein „!"): `/status` (außer Headline), Zeitplan-Liste, Assistenten-Schritte, Setup.
- **Sachlich-klar** (kein Wortwitz, Problem + Handlungsanweisung): Watchdog-Alarme, Notfall-Abschaltung, Zeitplan-Fehler, Dienst-Störung, Eingabefehler.

Verbot der Vermenschlichung: keine Formulierungen wie „satt getrunken" / „durstig".

**Überschriften.** Genau ein Format: `*<Emoji> Titel*` — ein Emoji, fett, kein Doppelpunkt. Schluss-Satzzeichen nur im verspielten Register (einzelnes „!").

**Datum & Einheiten.** Zeiten ohne Sekunden, immer mit „Uhr"; Relativzeit in Klammern (`vor 8 Min`). Einheiten mit Leerzeichen davor (`22.4 °C`, `1.4 mm`, `25 l`, `87 %`); Dezimal-Punkt bleibt (kein Komma).

**Emoji-Semantik.** Im Nachrichtentext hat jedes Emoji genau eine Bedeutung: 🟢 ok · 🟡 Achtung · 🔴 aus/Fehler · ⚠️ Alarm · 🌧 Regen · 🌡 Temperatur · 💧 Wassermenge · 🔋 Batterie · 📡 Ventil · 📷 Kamera · 📅 Zeitplan · 🚿 Guss. Der regenbedingte Skip nutzt 🌧 (nicht 🌤️). Die Ampelfarben sind dem Gesundheits-Status vorbehalten — die Hauptmenü-Buttons nutzen daher 🚿 „Bewässern starten" und 🛑 „Sofort Stopp" statt 🟢/🔴.

**Garten-Ampel (3-Stufen-Gesundheitsmodell).** Die `/status`-Headline zeigt die schlimmste aktive Stufe:
- 🟢 grün: alle Geräte aktiv, Batterien über `BATTERY_WARNING_THRESHOLD`, Dienste online, keine Anomalie.
- 🟡 gelb: Batterie ≤ `BATTERY_WARNING_THRESHOLD` oder Signal „kritisch" (LQI < 60), Gerät meldet aber noch.
- 🔴 rot: Broker/Mittelweg-Dienst offline, aktiver Watchdog-Alarm (über Timeout still) oder Ventil-Anomalie.

**Progressive Disclosure.** Technische Werte (LQI-Zahl, Geräte-ID/`mqtt_name`, exakte Zeitstempel) erscheinen nur für Geräte, die nicht grün sind. Gesunde Geräte bleiben einzeilig und qualitativ. Je gesünder das System, desto ruhiger und kürzer die Nachricht.

**Reichweite.** Vollständige, einmalige Migration des Bestands (`ui/telegram_ui.py`, `adapters/daily_report.py`) als eigenes, testbares Feature. Danach ist das Design-System verbindlich für alle neuen und geänderten Nachrichten.

## Konsequenzen

- Einheitliche, vorhersehbar lesbare Nachrichten; behebt zugleich den latenten `**`-Rendering-Bug.
- Selbst-eskalierende `/status`-Anzeige: ruhig im Normalfall, fokussiert im Problemfall.
- Migration ist ein einmaliger Kraftakt über viele Format-Strings — als eigenes Feature gebündelt und testbar gehalten.
- Pflege: Das Design-System ist über `.claude/rules/telegram_messages.md` verbindlich; Prinzipien und Zielbild liegen in `docs/reference/telegram-design-system.html`, der Ist-Stand in `docs/reference/telegram-nachrichten.html`.
- Neuer Domänenbegriff **Garten-Ampel** in `CONTEXT.md`.
