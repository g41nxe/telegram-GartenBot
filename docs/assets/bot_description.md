# Bot‑Beschreibung

**Smart Garden Bewässerungs‑Daemon** – dein nerdiger Pixel‑Art‑Bot für die Gartenbewässerung.

Der Bot steuert das **Sonoff Hydro ONE**‑Ventil über **Zigbee 2 MQTT** und lässt dich über Telegram bequem alle Funktionen nutzen – komplett **offline‑first** und ohne offene Ports.

### Hauptfunktionen
- **🟢 First‑to‑Hit‑Limit** – Kombination aus Zeit‑ und Volumen‑Grenzwert, das Ventil schließt beim Erreichen des ersten Limits.
- **📡 Mehrfach‑Ventil‑Support** – beliebig viele Ventile koppeln und benennen; Zeitpläne steuern sie sequentiell oder parallel.
- **📅 Geführter Zeitplan‑Assistent** – interaktive Wizard‑Tastaturen zum Erstellen komplexer Bewässerungspläne.
- **🌦️ Wetter‑Skip** – Open‑Meteo‑Daten prüfen Regen‑Vorhersage, bei Überschreitung des Schwellenwertes wird der Lauf übersprungen.
- **🔌 Live‑Verbindungsanzeige** – Echtzeit‑Dashboard (`/status`) zeigt MQTT‑Broker‑Status, Batterie und Signalstärke pro Ventil.
- **🔴 Sofort‑Stopp** (`/stop`) – Schließt alle aktiven Ventile sofort und bricht alle Scheduler‑Threads ab.

### Warum dieser Bot?
- **Intelligent & sicher** – schützt vor Über‑ und Unterbewässerung.
- **Ressourcenschonend** – reine Python‑Standardbibliotheken, ideal für den Raspberry Pi Zero W.
- **Nerd‑Friendly** – Pixel‑Art‑Design, klare Log‑Ausgaben und umfangreiche Test‑Suite.

Starte jetzt mit `/start` und lasse deinen Garten effizient und trocken‑frei wachsen!
