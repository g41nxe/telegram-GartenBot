# 4. Telegram-Bot als primäre Benutzeroberfläche

Wir implementieren einen Telegram-Bot als primäre Benutzeroberfläche zur Steuerung und Überwachung des Bewässerungs-Daemons, anstelle eines klassischen Web-Cockpits.

## Kontext

Der Zugriff auf die Steuerzentrale von außerhalb des eigenen Heimnetzwerks (z. B. von unterwegs) erfordert üblicherweise komplexe Netzwerkkonfigurationen wie DynDNS, Portweiterleitungen oder ein VPN (WireGuard), was Sicherheitsrisiken birgt. Zudem ist die Auslieferung einer interaktiven Web-App und die Implementierung von Push-Benachrichtigungen auf dem ressourcenbeschränkten Raspberry Pi Zero W aufwändig und fehleranfällig.

## Entscheidung

Wir integrieren eine Telegram-Bot-Schnittstelle direkt in den Python-Dienst (Bewässerungs-Daemon) mittels einer asynchronen Bibliothek (z. B. `python-telegram-bot` oder `telebot`). Der Bot kommuniziert gesichert per Long Polling (ausgehende HTTPS-Verbindung) mit den Telegram-Servern.
Über benutzerdefinierte Chats, Befehle und interaktive Inline-Tastaturen (Buttons) steuert und überwacht der Benutzer das System weltweit. Der Zugriff wird strikt auf autorisierte Telegram-User-IDs beschränkt.

## Konsequenzen

- **Vorteile**:
  - **Sicherheit**: Keine offenen Ports im Heimnetzwerk, kein VPN für den Außenzugriff erforderlich.
  - **Funktionalität**: Native Push-Nachrichten bei Statusänderungen oder Warnungen direkt auf das Smartphone.
  - **Ressourceneffizienz**: Nahezu kein CPU- und RAM-Verbrauch im Vergleich zu einem Webserver mit Polling.
  - **Entwicklungsgeschwindigkeit**: Die gesamte UI-Struktur (Buttons, Text) wird von Telegram bereitgestellt, kein CSS/JavaScript-Frontend-Code notwendig.
- **Nachteile**:
  - Abhängigkeit von der Verfügbarkeit des Telegram-Dienstes und ein aktiver Telegram-Account sind zwingend erforderlich.
