# 1. Lokale Ventilsteuerung über Zigbee 3.0

Wir steuern das Ventil (Sonoff Hydro ONE) lokal über Zigbee 3.0 mittels eines an der Steuerzentrale (Raspberry Pi Zero W) angeschlossenen Funk-Koordinators (USB-Dongle) und des Mittelweg-Dienstes (Zigbee2MQTT), statt die herstellerseitige WLAN/eWeLink-Cloud-API zu verwenden.

## Kontext

Das Sonoff Hydro ONE Ventil besitzt kein eigenes WLAN-Modul, sondern kommuniziert über den energiesparenden Zigbee 3.0 Standard. Eine Steuerung direkt über die integrierte WLAN-Schnittstelle der Steuerzentrale ist physisch nicht möglich.

## Entscheidung

Wir erwerben einen USB-Funk-Koordinator für die Steuerzentrale und richten Zigbee2MQTT ein. Dadurch können wir das Ventil direkt im Garten ansteuern, ohne auf eine externe Internetverbindung oder Hersteller-Cloud angewiesen zu sein.

## Konsequenzen

- **Vorteile**: Volle Offline-Fähigkeit, extrem geringe Latenz, keine Abhängigkeit von Drittanbieter-Servern, hohe Datensicherheit.
- **Nachteile**: Zusätzliche Hardwarekosten für den USB-Funk-Koordinator; Initialaufwand für das Aufsetzen des Mittelweg-Dienstes auf der Steuerzentrale.
