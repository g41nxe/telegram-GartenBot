# 7. Gießmengen-Steuerung (Mengen-Guss) mit 15-Minuten-Notfall-Abschaltung

Wir erweitern den Bewässerungs-Daemon um die Möglichkeit, die Bewässerung entweder nach Zeit (Zeit-Guss) oder nach Durchflussmenge in Litern (Mengen-Guss) zu steuern. Jeder Mengen-Guss wird durch eine softwareseitige Notfall-Abschaltung nach maximal 15 Minuten hart abgesichert.

## Kontext

Das Sonoff Hydro ONE Ventil besitzt einen eingebauten Durchflussmesser, der über Zigbee2MQTT die geflossene Wassermenge in Litern überträgt. Die Möglichkeit, nach Litern zu bewässern, ermöglicht eine präzisere und bedarfsgerechtere Bewässerung als eine reine Zeitsteuerung. 
Sollte jedoch der Durchflusssensor blockieren oder die Funkverbindung während des Gießens abbrechen, würde die Zielwassermenge niemals erreicht und das Ventil bliebe dauerhaft offen, was zu Überflutungen führen kann.

## Entscheidung

Wir führen zwei Betriebsmodi für die Zeitsteuerung und manuelle Steuerung ein:
- **Zeit-Guss (`time`)**: Bewässerung für eine Dauer von $X$ Minuten.
- **Mengen-Guss (`volume`)**: Bewässerung bis zum Durchfluss von $Y$ Litern (Vorschläge: `10l`, `25l`, `50l`, `80l`).

**Notfall-Abschaltung**: Bei jedem Start eines Mengen-Gusses wird ein unumstößlicher Software-Sicherheitstimer auf **exakt 15 Minuten** gesetzt. Ist die Zielwassermenge nach 15 Minuten nicht erreicht (z. B. aufgrund eines Sensorfehlers, Druckabfalls oder verstopfter Schläuche), schließt der Daemon das Ventil sofort und sendet eine Notfall-Warnung per Telegram-Push: `⚠️ Notfall-Abschaltung nach 15 Minuten ausgelöst! Zielwassermenge von Y Litern wurde nicht erreicht.`

## Konsequenzen

- **Vorteile**: Hochpräzises Bewässerungsmanagement basierend auf echten Durchflussdaten; vollständiger Schutz vor Überflutungen durch die 15-Minuten-Abschaltung selbst bei mechanischen Sensorfehlern.
- **Nachteile**: Größere Mengen-Güsse, die bei sehr geringem Wasserdruck länger als 15 Minuten dauern würden, werden vorzeitig abgebrochen (gärtnerisch in Kleingärten jedoch absolut vernachlässigbar; bei Bedarf können zwei Zyklen nacheinander geplant werden).
