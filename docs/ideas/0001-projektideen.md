# 💡 Ideen & Zukunftsvisionen für den GartenBot

Dieses Dokument enthält eine strukturierte Sammlung aller kreativen Vorschläge und „Out-of-the-Box“-Automatisierungsideen, die im Rahmen des Brainstormings entwickelt wurden. Sie dienen als Fahrplan für zukünftige Erweiterungen des GartenBot-Systems.

---

## 1. Intelligente & Bodenadaptive Guss-Anpassung

*   **Bodenfeuchtigkeits-gesteuerter Skip (Soil Moisture Integration):**
    *   *Konzept:* Einbindung eines Zigbee-Bodenfeuchtigkeitssensors (z. B. Tuya/Xiaomi) via *Mittelweg-Dienst*. Die *Guss-Steuerung* prüft vor dem Start, ob die Bodenfeuchtigkeit bereits über einem definierten Schwellenwert liegt, und überspringt ggf. den Guss.
    *   *Mehrwert:* Verhindert Überwässerung bei feuchter Erde, selbst wenn kein Regen vorhergesagt ist.
*   **Intervall-Bewässerung (Cycle-and-Soak / Split-Guss):**
    *   *Konzept:* Aufteilen eines langen *Kombinierten Gusses* in mehrere kurze Intervalle mit Einwirkpausen (z. B. statt 20 Minuten am Stück: 4 Zyklen à 5 Minuten mit je 10 Minuten Pause).
    *   *Mehrwert:* Ideal für dichte Lehmböden oder Hanglagen. Das Wasser sickert tief ein, statt oberflächlich abzufließen.
*   **Beete-Management & Biologischer Ernte-Wächter:**
    *   *Konzept:* Verwaltung von Anbauflächen und Berechnung der Erntereife basierend auf dem Modell der **Wachstumsgradtage (Growing Degree Days - GDD)**.
    *   *GDD-Formel:* $GDD_{\text{effektiv}} = \max\left(\frac{T_{\max} + T_{\min}}{2} - T_{\text{basis}}, 0\right)$
    *   *Mehrwert:* Der Bot zeigt einen Fortschrittsbalken (`[██████░░░░] 60%`) für Tomaten, Salat und Co. an und sagt den Erntezeitpunkt voraus.

---

## 2. Präventive Sicherheit & Hardware-Diagnose

*   **Echtzeit-Leckage-Erkennung & Rohrbruch-Wächter:**
    *   *Konzept:* Kontinuierliche Überwachung der vom *Ventil* gemeldeten Durchflussmenge (Flow Rate). Alarmierung bei Durchfluss im geschlossenen Zustand (Leck), extrem hohem Durchfluss (Rohrbruch) oder null Durchfluss bei geöffnetem Ventil.
    *   *Mehrwert:* Triggert einen automatischen Notschluss (Sofort-Stopp) und eine Telegram-Warnung zur Schadensbegrenzung.
*   **Frost-Warnung & Winterschutz-Assistent:**
    *   *Konzept:* Der *Wetter-Dienst* prüft stündlich die Tiefsttemperaturen der nächsten 48 Stunden. Sinkt sie unter 2 °C, wird gewarnt.
    *   *Mehrwert:* Schützt das Ventil vor Frostschäden; bietet einen Ein-Klick-Button zur Deaktivierung aller Zeitpläne.
*   **Interaktiver System-Selbsttest (`/diagnose`):**
    *   *Konzept:* Ein geführter Diagnose-Befehl im Telegram-Bot, der DB, MQTT, Ventil-Status, Batterie und API-Erreichbarkeit prüft sowie einen 5-Sekunden-Kurzguss ausführt.
    *   *Mehrwert:* Perfekt zur Inbetriebnahme im Frühling oder zur Fehlersuche aus der Ferne.

---

## 3. Zisternen- & Ressourcen-Management

*   **Priorisiertes Gießen mit Regenwasser:**
    *   *Konzept:* Überwachung des Füllstands der Regentonne/Zisterne mittels Ultraschallsensor. Bei hohem Füllstand wird eine 12V-Pumpe aktiviert. Ist die Tonne leer, schaltet ein 3-Wege-Ventil automatisch auf Leitungswasser um.
    *   *Mehrwert:* Maximale Nutzung von kostenlosem Regenwasser.
*   **Vorausschauendes Entleeren (Storm Prep):**
    *   *Konzept:* Ist die Zisterne voll und meldet der *Wetter-Dienst* Starkregen (> 25 mm), öffnet der Bot das Ventil vorab leicht, um kontrolliert Platz für frisches Wasser zu schaffen und Überlaufen an der Hauswand zu verhindern.
*   **Solarstrom-geführtes Gießen (PV-Integration):**
    *   *Konzept:* Kopplung mit einem Smart Meter (z. B. Shelly). Der Bot startet stromintensive Pumpen bevorzugt dann, wenn die Balkonsolaranlage Überschuss produziert.

---

## 4. Garten-Ökosystem & Wildtierpflege

*   **Der intelligente Kompost-Reaktor:**
    *   *Konzept:* Überwachung der Feuchtigkeit und biologischen Zersetzungswärme (50–65 °C) im Komposthaufen mittels langer Bodensonden.
    *   *Automatisierung:* Befeuchtung per Sprühdüse bei Trockenheit; Telegram-Meldung zum Wenden, wenn der Haufen abkühlt (Sauerstoffmangel).
*   **Vogeltränken- & Insektenhotel-Hygienemanager:**
    *   *Konzept:* Ein steuerbares Magnetventil spült jeden Morgen um 05:30 Uhr mit hohem Druck das stehende, keimanfällige Wasser aus der Vogeltränke und füllt frisches Wasser auf.
    *   *Futter-Warnung:* IR-Lichtschranke im Vogelfutterspender meldet leere Spender per Telegram.
*   **Akustischer Schädlings- & Regenwächter:**
    *   *Konzept:* Ein USB-Richtmikrofon an der *Steuerzentrale* analysiert Frequenzen.
    *   *Automatisierung:* Triggert einen Ultraschallsender bei nächtlichem Wühlmaus-Scharren oder Marder-Nagen. Dient akustisch als lokaler Echtzeit-Regensensor (Prasseln auf Blech), um Bewässerung sofort to stoppen.
*   **Smarte Hochbeet-Thermodecke:**
    *   *Konzept:* Ein 12V-Linearmotor öffnet/schließt die Haube eines Frühbeets temperaturabhängig oder schließt sie bei Unwetterwarnungen des *Wetter-Dienstes* (Hagelschutz).
*   **Vertikaler Erdbeer- / Hydroponik-Turm-Manager:**
    *   *Konzept:* Steuerung einer 12V-Pumpe im exakten Intervall (z. B. alle 15 Min für 45 Sek).
    *   *Analytik:* pH- und EC-Sensoren überwachen die Nährstofflösung und senden Nachfüll-Erinnerungen via Telegram.
