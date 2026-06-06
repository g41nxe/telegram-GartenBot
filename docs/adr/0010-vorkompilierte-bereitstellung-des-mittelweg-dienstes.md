# 10. Vorkompilierte Bereitstellung des Mittelweg-Dienstes (Zigbee2MQTT)

Wir verlagern die TypeScript-Kompilierung von Zigbee2MQTT von dem ressourcenschwachen Raspberry Pi Zero W auf die lokale Entwicklungsmaschine (Windows Host) und übertragen die gebauten Artefakte als komprimiertes Archiv.

## Kontext

Der Raspberry Pi Zero W ist mit einem Single-Core ARMv6-Prozessor und 512 MB RAM ausgestattet. Bei der Standard-Installation von Zigbee2MQTT treten zwei signifikante Engpässe auf:
1. **npm install:** Die Auflösung und Installation aller Abhängigkeiten dauert sehr lange. (Zudem muss dafür temporär der Swap-Speicher auf 1024 MB erhöht werden, was die Lebensdauer der SD-Karte beeinträchtigt).
2. **TypeScript-Kompilierung (npm run build):** Das Ausführen des TypeScript-Compilers (`tsc`) bringt die CPU des Pi Zero W für 5 bis 15 Minuten an den Anschlag und schlägt ohne erhöhten Swap-Speicher aufgrund von Out-of-Memory (OOM) Fehlern fehl.

Da der kompilierte JavaScript-Code (`dist/`-Ordner) plattformunabhängig ist, kann dieser Schritt vollständig auf dem Entwicklungsrechner ausgeführt werden. Native C/C++ Module (wie z. B. `@serialport/bindings-cpp`) sind jedoch plattformabhängig und müssen weiterhin auf dem Pi selbst für die ARMv6-Linux-Architektur kompiliert bzw. installiert werden.

## Entscheidung

Wir führen folgenden optimierten Deployment-Prozess ein:

1. **Lokaler Build:**
   Das Windows-Bereitstellungsskript (`deploy.ps1`) führt vor der Übertragung automatisch `npm run build` im lokalen Zigbee2MQTT-Verzeichnis (`temp_z2m/`) aus.

2. **Selektive Archivierung:**
   Die kompilierten Quellcodedateien aus `temp_z2m/` (inklusive des neu erstellten `dist/`-Verzeichnisses, aber **ohne** `node_modules` und `.git`) werden in ein komprimiertes Archiv namens `zigbee2mqtt.tar.gz` verpackt. Dies spart Bandbreite und verhindert, dass Windows-spezifische native Binärdateien auf den Pi kopiert werden.

3. **Integrierte Erkennung im Setup-Skript:**
   Das Installationsskript auf dem Pi (`setup.sh`) wird so erweitert, dass es nach der übertragenen Datei `zigbee2mqtt.tar.gz` sucht:
   - **Falls vorhanden:** Das Archiv wird direkt nach `/opt/zigbee2mqtt` entpackt, und der `git clone`-Schritt wird übersprungen.
   - **Falls nicht vorhanden (Fallback):** Das Skript fällt auf das Standardverhalten zurück (Klonen aus dem GitHub-Repository).

4. **NPM-Installation auf dem Pi:**
   Nach dem Entpacken wird auf dem Pi `npm install --omit=dev --ignore-scripts` ausgeführt. Da das `dist/`-Verzeichnis bereits vorhanden ist, wird die Ausführung von `npm run build` auf dem Pi komplett übersprungen.

## Konsequenzen

* **Vorteile:**
  - **Dramatische Zeitersparnis:** Die Einrichtungszeit von Zigbee2MQTT auf dem Pi sinkt von ~20 Minuten auf unter 3 Minuten.
  - **SD-Karten-Schonung:** Da der TypeScript-Compiler nicht auf dem Pi läuft, entfällt der immense Schreib- und Leseaufwand auf dem Swap-Speicher.
  - **Abwärtskompatibilität:** Die Möglichkeit, das Setup direkt auf dem Pi komplett neu aus den GitHub-Quellen aufzubauen, bleibt unberührt, falls kein lokales Archiv übertragen wurde.

* **Nachteile:**
  - Auf der lokalen Windows-Entwicklungsmaschine müssen Node.js und ein passender Paketmanager installiert sein, um den Build-Schritt auszuführen.
