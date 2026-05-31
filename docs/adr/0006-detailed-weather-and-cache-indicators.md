# 6. Detaillierte Wetteranzeige und Cache-Indikatoren im Telegram-Bot

Wir erweitern die Statusübersicht des Telegram-Bots um aktuelle Wetterdaten (Temperatur und qualitative Beschreibung) und fügen bei Offline-Zuständen eine transparente Angabe zur Aktualität der Daten (Wetterdaten-Stand) hinzu.

## Kontext

Der Benutzer wünscht eine aussagekräftigere Wetteranzeige, die über die reine Niederschlagsmenge hinausgeht. Da der Dienst offline-fähig und robust gegen Netzwerkausfälle sein soll, ist es für den Benutzer kritisch zu erkennen, wie aktuell die angezeigten Wetterdaten sind, wenn keine Live-Abfrage möglich ist.

## Entscheidung

Wir führen folgende Anpassungen durch:
1. **WMO-Übersetzungstabelle**: Wir implementieren eine lokale Zuordnungstabelle im Bewässerungs-Daemon, die WMO-Wettercodes der Open-Meteo API in deutsche Beschreibungen (z. B. `☀️ Sonnig`, `☁️ Bedeckt`) übersetzt.
2. **Erweiterter Status**: Der Bot benennt die Sektion in "Wetter" um und zeigt die aktuelle Temperatur sowie die qualitative Beschreibung an.
3. **Wetterdaten-Stand**: Wir speichern den genauen Abrufzeitpunkt (`timestamp`) in der Tabelle `weather_history`. Der Bot zeigt diesen im Status an (z. B. `(Stand: 12:45 Uhr)`), damit der Benutzer die Aktualität der Daten sofort bewerten kann, insbesondere bei Ausfällen der Internetverbindung.

## Konsequenzen

- **Vorteile**: Exzellente Benutzererfahrung, hohe Transparenz bei Netzwerkausfällen und volle Offline-Fähigkeit ohne Performance-Einbußen.
- **Nachteile**: Geringfügiger Anstieg der Komplexität beim Parsen der API-Antwort und eine leichte Vergrößerung des SQLite-Datenbank-Schemas.
