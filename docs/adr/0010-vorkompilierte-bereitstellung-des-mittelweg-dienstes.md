# 10. Vorkompilierte Bereitstellung des Mittelweg-Dienstes (Zigbee2MQTT)

Wir verlagern die TypeScript-Kompilierung von Zigbee2MQTT von dem ressourcenschwachen Raspberry Pi Zero W auf die lokale Entwicklungsmaschine (Windows Host) und übertragen die gebauten Artefakte als komprimiertes Archiv.

## Kontext

Der Raspberry Pi Zero W ist mit einem Single-Core ARMv6-Prozessor und 512 MB RAM ausgestattet. Bei der Standard-Installation von Zigbee2MQTT treten zwei signifikante Engpässe auf:
1. **npm install:** Die Auflösung und Installation aller Abhängigkeiten dauert sehr lange. (Zudem muss dafür temporär der Swap-Speicher auf 1024 MB erhöht werden, was die Lebensdauer der SD-Karte beeinträchtigt).
2. **TypeScript-Kompilierung (npm run build):** Das Ausführen des TypeScript-Compilers (`tsc`) bringt die CPU des Pi Zero W für 5 bis 15 Minuten an den Anschlag und schlägt ohne erhöhten Swap-Speicher aufgrund von Out-of-Memory (OOM) Fehlern fehl.

Darüber hinaus nutzen neuere Versionen von Zigbee2MQTT (wie `v2.10.1`) beim Laden der `package.json` die neue ES-Modules Import-Attribute-Syntax (z. B. `with { type: "json" }` in `index.js`). Diese Syntax wird erst ab **Node.js v20.10.0** unterstützt. Die zuvor installierte Version `v20.9.0` führt beim Starten des Dienstes zu einem kritischen `TypeError` ("needs an import assertion").

Da der kompilierte JavaScript-Code (`dist/`-Ordner) plattformunabhängig ist, kann dieser Schritt vollständig auf dem Entwicklungsrechner ausgeführt werden. Native C/C++ Module (wie z. B. `@serialport/bindings-cpp`) sind jedoch plattformabhängig und müssen weiterhin auf dem Pi selbst für die ARMv6-Linux-Architektur kompiliert bzw. installiert werden. Hierbei muss sichergestellt sein, dass die Node.js-Version auf dem Pi die neue Syntax unterstützt.

## Entscheidung

Wir führen folgenden optimierten Deployment-Prozess ein:

1. **Lokaler Build:**
   Das Windows-Bereitstellungsskript (`deploy.ps1`) führt vor der Übertragung automatisch `npm run build` im lokalen Zigbee2MQTT-Verzeichnis (`vendor/zigbee2mqtt/`) aus.

2. **Selektive Archivierung:**
   Die kompilierten Quellcodedateien aus `vendor/zigbee2mqtt/` (inklusive des neu erstellten `dist/`-Verzeichnisses, aber **ohne** `node_modules` und `.git`) werden in ein komprimiertes Archiv namens `zigbee2mqtt.tar.gz` verpackt. Dies spart Bandbreite und verhindert, dass Windows-spezifische native Binärdateien auf den Pi kopiert werden.

3. **Integrierte Erkennung im Setup-Skript:**
   Das Installationsskript auf dem Pi (`setup.sh`) wird so erweitert, dass es nach der übertragenen Datei `zigbee2mqtt.tar.gz` sucht:
   - **Falls vorhanden:** Das Archiv wird direkt nach `/opt/zigbee2mqtt` entpackt, und der `git clone`-Schritt wird übersprungen.
   - **Falls nicht vorhanden (Fallback):** Das Skript fällt auf das Standardverhalten zurück (Klonen aus dem GitHub-Repository).

4. **NPM-Installation auf dem Pi:**
   Nach dem Entpacken wird auf dem Pi `npm install --omit=dev --ignore-scripts` ausgeführt. Da das `dist/`-Verzeichnis bereits vorhanden ist, wird die Ausführung von `npm run build` auf dem Pi komplett übersprungen.

5. **Node.js-Upgrade auf dem Pi:**
   Das Skript `setup.sh` wird so angepasst, dass es auf dem Pi das inoffizielle ARMv6-Build von **Node.js v20.11.1** (das die ES-Modules Import-Attribute unterstützt) herunterlädt und installiert. Eine integrierte Abfrage erzwingt ein Upgrade, falls eine ältere Node.js-Version (wie v20.9.0) erkannt wird.

## Quellcode-Anpassungen des Mittelweg-Dienstes (Vendoring)

Da Zigbee2MQTT als lokaler Quellcode im Repository unter `vendor/zigbee2mqtt` verwaltet ("gevendort") wird, haben wir direkte Kontrolle über die Quellcodedateien und Abhängigkeiten. Dies war notwendig, um folgende Inkompatibilitäten auf dem Raspberry Pi Zero W zu beheben:

### CommonJS / ESM Kompatibilität (Debounce-Downgrade)
* **Problem:** Auf dem Raspberry Pi Zero W ist Node.js standardmäßig auf Version `v20.11.1` beschränkt (höchste verfügbare inoffizielle Version für ARMv6). Diese Node.js-Version besitzt noch keine vollständige Unterstützung für `require()` von ES-Modulen (die erst ab Node.js v20.19.0 backportiert wurde).
* **Konsequenz:** Die Bibliothek `debounce@^3.0.0` ist ein reines ES-Modul. Beim Starten von Zigbee2MQTT scheiterte der Import mit der Fehlermeldung `ERR_REQUIRE_ESM`.
* **Lösung:** In `vendor/zigbee2mqtt/package.json` wurde das Paket `debounce` von Version `^3.0.0` auf die CommonJS-kompatible Version `^1.2.1` downgegradet. Nach Ausführung von `npm install` im Vendoring-Verzeichnis wurde die `package-lock.json` aktualisiert, wodurch der Dienst auch auf älteren Node.js-Runtimes fehlerfrei startet.

### Kompatibilitätspfad für Coordinator-Firmware Upgrades
* **Problem:** Wenn die Firmware des Funk-Koordinators (ZBDongle-E) von der veralteten EZSP v8 auf v7.4 (EZSP v13+) aktualisiert wird, führt das direkte Starten mit dem Standard-Treiber `adapter: ember` zu einem Backup-Formatkonflikt (`Current backup file is from an unsupported EZSP version`), was das gesamte Zigbee-Netzwerk unbrauchbar machen kann.
* **Lösung:** Bei einem Firmware-Upgrade muss Zigbee2MQTT beim ersten Start explizit mit `adapter: ezsp` gestartet werden. Nach erfolgreicher Konvertierung des Backups kann und sollte für den Normalbetrieb auf `adapter: ember` gewechselt werden (bzw. der adapter-Typ aus der Konfiguration gelöscht werden, da `ember` in Zigbee2MQTT v2.x der Standard-Treiber für diese Chipsätze ist).

## Konsequenzen

* **Vorteile:**
  - **Dramatische Zeitersparnis:** Die Einrichtungszeit von Zigbee2MQTT auf dem Pi sinkt von ~20 Minuten auf unter 3 Minuten.
  - **SD-Karten-Schonung:** Da der TypeScript-Compiler nicht auf dem Pi läuft, entfällt der immense Schreib- und Leseaufwand auf dem Swap-Speicher.
  - **Abwärtskompatibilität:** Die Möglichkeit, das Setup direkt auf dem Pi komplett neu aus den GitHub-Quellen aufzubauen, bleibt unberührt, falls kein lokales Archiv übertragen wurde.
  - **Sichergestellte Laufzeit-Kompatibilität:** Durch das automatische Node.js-Upgrade auf v20.11.1 werden import-Fehler bei neueren Zigbee2MQTT-Bibliotheken zuverlässig verhindert.

* **Nachteile:**
  - Auf der lokalen Windows-Entwicklungsmaschine müssen Node.js und ein passender Paketmanager installiert sein, um den Build-Schritt auszuführen.
