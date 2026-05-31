# 5. Zweistufige Sicherheitsabschaltung gegen Gartenüberflutung

Wir sichern das System gegen eine unkontrollierte Überflutung des Gartens bei Systemabstürzen oder Verbindungsabbrüchen durch eine zweistufige Abschaltlogik (Software-Steuerung und Hardware-Notbremse) ab.

## Kontext

Im Außenbereich kann ein dauerhaft geöffnetes Ventil immense Wasserschäden und Kosten verursachen. Wenn die Steuerzentrale während einer aktiven Bewässerung abstürzt oder die Funkverbindung zum Ventil abreißt, kann kein regulärer Ausschaltbefehl mehr gesendet werden.

## Entscheidung

Wir implementieren ein zweistufiges Sicherheitskonzept (Defense-in-Depth):
1. **Software-Ebene (Regulärer Betrieb)**: Der Bewässerungs-Daemon auf der Steuerzentrale verwaltet die exakten Laufzeiten (z. B. 10 oder 15 Minuten) und sendet nach Ablauf der Dauer einen regulären Zigbee-Ausschaltbefehl.
2. **Hardware-Ebene (Sicherheits-Notbremse)**: Wir konfigurieren über den Mittelweg-Dienst (Zigbee2MQTT) die native Hardware-Schutzfunktion (Auto-Close / Inching) des Ventils auf ein festes Sicherheits-Timeout von maximal 30 Minuten. 

Sollte der reguläre Ausschaltbefehl der Software ausbleiben, schließt das Ventil nach exakt 30 Minuten physisch von selbst, ohne dass ein Funksignal oder eine aktive Steuerzentrale notwendig ist. Die maximale Software-Bewässerungsdauer wird auf 25 Minuten limitiert.

## Konsequenzen

- **Vorteile**: Absolute Ausfallsicherheit gegen Überflutungen bei Stromausfall des Pi, Funkstörungen oder Daemon-Abstürzen.
- **Nachteile**: Keine ununterbrochene Bewässerung von mehr als 25 Minuten in einem einzigen Durchlauf möglich (für gewöhnliche Gärten jedoch völlig ausreichend; bei Bedarf müssten zwei separate Intervalle mit kurzer Pause geplant werden).
