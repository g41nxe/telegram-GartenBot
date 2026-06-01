# 7. Kombinierter Guss (First-to-Hit-Steuerung) nach Zeit und Wassermenge mit Notfall-Abschaltung

Wir steuern jeden Bewässerungslauf (sowohl Zeitpläne als auch manuelle Einsätze) standardmäßig über eine kombinierte Grenzwert-Überwachung (Kombinierter Guss), die sowohl eine maximale Gießzeit (Zeitlimit) als auch eine maximale Wassermenge (Volumenlimit) definiert. Das Ventil schließt sich automatisch, sobald einer der beiden Grenzwerte zuerst erreicht wird (First-to-Hit). Bei jedem Start wird ein zeitbasierter Wächter und ein volumenbasierter Wächter parallel gestartet. Sollte das Zeitlimit ablaufen, bevor die gewünschte Wassermenge erreicht wurde, greift dies als softwareseitige Notfall-Abschaltung (Schutz vor Überflutungen bei Sensor- oder Netzwerkausfall).

## Kontext

Das Sonoff Hydro ONE Ventil besitzt einen eingebauten Durchflussmesser, der über Zigbee2MQTT die geflossene Wassermenge in Litern überträgt. Die Möglichkeit, ein zusätzliches Volumenlimit festzulegen, ermöglicht eine präzisere und bedarfsgerechtere Bewässerung als eine reine Zeitsteuerung.

Sollte jedoch der Durchflusssensor blockieren, der Wasserdruck abfallen, ein Schlauch verstopfen oder die Funkverbindung während des Gießens abbrechen, würde die Zielwassermenge niemals erreicht. Das Ventil bliebe dauerhaft offen, was zu fatalen Überflutungen führen kann. 

Eine reine, starre zeitbasierte Notfall-Abschaltung von beispielsweise 15 Minuten schränkt die Flexibilität stark ein (z. B. wenn an heißen Tagen bewusst länger oder mehr gegossen werden soll). Eine kombinierte Überwachung, bei der der Benutzer für jeden Lauf ein individuelles Zeit- und Volumenlimit festlegen kann, bietet maximale Sicherheit bei gleichzeitig optimaler Flexibilität. Das Zeitlimit dient dabei automatisch als dynamischer, unumstößlicher Sicherheits-Timer.

## Entscheidung

Wir implementieren das Prinzip **"First-to-Hit" (Wer zuerst eintrifft, gewinnt)** für alle Bewässerungszyklen:

1. **Zeitlimit (`duration_minutes`)**: Maximale Laufzeit (über den Bot auf maximal 25 Minuten begrenzt).
2. **Volumenlimit (`target_volume_liters`)**: Maximale Durchflussmenge (Vorschläge: `10l`, `25l`, `50l`, `80l` oder benutzerdefiniert).

Bei jedem Start einer Bewässerung werden zwei Überwachungsprozesse parallel ausgeführt:
- Ein klassischer Software-Timer (`threading.Timer`) für die Dauer in Minuten.
- Ein ständiger Hintergrund-Thread, der alle 2 Sekunden die geflossene Wassermenge über die MQTT-Statusmeldungen des Ventils aufsummiert und mit dem Liter-Limit abgleicht.

### Stabilität der Volumen-Berechnung (Volumen-Deckelung)
Um die Zuverlässigkeit der Durchflussmengen-Integration auch bei kurzzeitigen Funklöchern oder Netzwerk-Latenzen des Mittelweg-Dienstes zu gewährleisten, verwerfen wir bei größeren Zeitabständen zwischen den MQTT-Statusmeldungen (größer oder gleich 60 Sekunden) den Zuwachs nicht. Stattdessen wird das Berechnungszeitfenster auf maximal 60 Sekunden gedeckelt, damit kein geflossenes Wasservolumen unberücksichtigt bleibt.

### Sicherheits-Schließung bei Daemon-Start
Wird beim Starten des Bewässerungs-Daemons über MQTT festgestellt, dass das Ventil geöffnet ist (`state == "ON"`), obwohl laut interner Datenbank kein aktiver Bewässerungslauf gestartet sein dürfte (z.B. nach einem unvorhergesehenen Systemneustart oder Stromausfall), löst der Daemon aus Sicherheitsgründen sofort einen Schließen-Befehl aus. Der Benutzer erhält umgehend eine Telegram-Warnung:
`⚠️ Unerwartet geöffnetes Ventil beim Systemstart erkannt! Sicherheits-Schließung durchgeführt.`

### Notfall-Abschaltung & Fehlerbehandlung während des Gießens
Sobald einer der beiden Wächter anschlägt, wird das Schließen des Ventils ausgelöst und der Benutzer über die genaue Ursache benachrichtigt:
- **Volumenlimit zuerst erreicht**: Der Guss war erfolgreich. Das Ventil schließt planmäßig.
- **Zeitlimit erreicht bei aktivem Volumenlimit**: Dies deutet auf einen Fehler hin (Sensor blockiert, verstopfter Schlauch, Druckabfall). Das Ventil wird sofort geschlossen, und es wird eine Notfall-Warnung per Telegram-Push versendet: `⚠️ Notfall-Abschaltung nach X Minuten ausgelöst! Zielwassermenge von Y Litern wurde nicht erreicht (geflossen: Z Liter).` Dieser Lauf wird in der Historie als `failed` markiert.

## Konsequenzen

- **Vorteile**:
  - **Höchste Betriebssicherheit**: Das Zeitlimit dient automatisch als dynamisches Fail-Safe für den Durchflusssensor (und umgekehrt).
  - **Maximale Flexibilität**: Der Benutzer entscheidet selbst über das Sicherheitsfenster und die gewünschte Gießintensität.
  - **Einheitliches Datenbankschema**: Das Datenbankschema verwaltet für alle Zyklen permanent beide Werte (`duration_minutes` und `target_volume_liters`), was die Datenhaltung vereinheitlicht.
- **Nachteile**:
  - Geringfügig höhere Komplexität im Code durch die parallele Überwachung (Threading und Timer).
