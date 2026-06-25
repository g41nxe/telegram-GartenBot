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

### Volumen-Quelle: Guss-Volumen aus `actual_irrigation_amount` der laufenden Session

Das Sonoff SWV-ZFE meldet **kein** instantanes `flow_rate`-Feld (L/min). Es liefert mehrere Volumenfelder, von denen nur **eines** als Guss-Volumen taugt. Ein MQTT-Mitschnitt eines realen Gusses hat das eindeutig belegt:

- `real_time_irrigation_volume`: kumulativer, geräteweiter Zähler. Er wird **während** eines Gusses **nicht** aktualisiert (steht still) und springt erst **~6 s nach** dem Schließen um die Session-Menge nach oben. Für eine Echtzeit-Volumensteuerung ist er damit unbrauchbar — und sein verspäteter Sprung vergiftet sogar den Folge-Guss.
- `irrigation_schedule_status.actual_irrigation_amount`: die **live** mitlaufende Menge der **aktuellen** Bewässerungs-Session. Sie startet bei jeder Session bei 0, zählt im ~6-Sekunden-Takt hoch (~2-L-Schritte) und ist beim Session-Ende der korrekte Gesamtwert. `irrigation_schedule_status.schedule_status` durchläuft dabei `start → running → end`.

Der `WateringController` liest daher das **Guss-Volumen** aus `actual_irrigation_amount`, und zwar **nur**, solange `schedule_status == "running"`. Diese Bedingung filtert die verspäteten `end`-Reports der Vorsession und den Kaltstart (`start`/`None`) sauber heraus.

- Pro gültigem Report gilt `guss_volumen = max(bisheriges_guss_volumen, actual_irrigation_amount)`. Das `max()` sichert Monotonie gegen einzelne Funk-Ausreißer ab.
- Es ist **keine** Baseline/Delta-Rechnung nötig, weil `actual_irrigation_amount` pro Session ohnehin bei 0 startet. Das Gerät setzt es beim nächsten Guss zuverlässig zurück (im Mitschnitt bestätigt: neuer `start` → `actual = None/0`, neue `start_time`).

Der `flow_rate`-Pfad (`_integrate_flow`, flow_rate × elapsed_time) bleibt ausschließlich als Fallback für den `SimulatedMqttAdapter` und potenzielle künftige Geräte mit echter Durchflussrate erhalten; die reale Hardware sendet kein `flow_rate`. Die "Volumen-Deckelung" (60-Sekunden-Cap) gilt nur für diesen Fallback-Pfad.

## Konsequenzen

- **Vorteile**:
  - **Höchste Betriebssicherheit**: Das Zeitlimit dient automatisch als dynamisches Fail-Safe für den Durchflusssensor (und umgekehrt).
  - **Maximale Flexibilität**: Der Benutzer entscheidet selbst über das Sicherheitsfenster und die gewünschte Gießintensität.
  - **Einheitliches Datenbankschema**: Das Datenbankschema verwaltet für alle Zyklen permanent beide Werte (`duration_minutes` und `target_volume_liters`), was die Datenhaltung vereinheitlicht.
- **Nachteile**:
  - Geringfügig höhere Komplexität im Code durch die parallele Überwachung (Threading und Timer).
  - Das Software-Volumenlimit hat die Granularität der Geräte-Reports (~6 s / ~2 L), also einen geringen Überschuss; das Zeitlimit bleibt der harte Backstop.
- **Gelernte Lehre (zwei Iterationen)**: Zuerst wurde der kumulative `real_time_irrigation_volume` direkt als Guss-Volumen gewertet → Volumenlimits lösten am Altbestand aus, Historie verfälscht. Eine Baseline/Delta-Korrektur darauf behob den Absolutwert, scheiterte aber, weil dasselbe Feld **während** des Gusses still steht und erst verspätet springt → kurze Güsse meldeten 0 L, der verspätete Sprung vergiftete den Folge-Guss. Erst der Wechsel auf `actual_irrigation_amount` der laufenden Session (per MQTT-Mitschnitt verifiziert) löst das Problem grundlegend. Beide Fehl-Iterationen blieben unentdeckt, weil der `SimulatedMqttAdapter` ein anderes Volumen-Modell (flow_rate, sekündlich) abbildet als die reale Hardware — siehe Feature 0028.
