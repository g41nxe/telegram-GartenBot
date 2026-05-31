# 8. Kombinierter Guss (First-to-Hit-Steuerung) nach Zeit und Wassermenge

Wir steuern jeden Bewässerungslauf (sowohl Zeitpläne als auch manuelle Einsätze) standardmäßig über eine kombinierte Grenzwert-Überwachung (Kombinierter Guss), die sowohl eine maximale Gießzeit (Zeitlimit) als auch eine maximale Wassermenge (Volumenlimit) definiert. Das Ventil schließt sich automatisch, sobald einer der beiden Grenzwerte zuerst erreicht wird.

## Kontext

Die vorherige Planung sah eine starre, softwareseitige Notfall-Abschaltung von 15 Minuten für reine Wassermengen-Steuerungen vor. Dies schränkt jedoch die Flexibilität ein (z. B. wenn an heißen Tagen bewusst länger oder mehr gegossen werden soll). Eine kombinierte Überwachung, bei der der Benutzer für jeden Lauf ein individuelles Zeit- und Volumenlimit festlegen kann, bietet maximale Sicherheit bei gleichzeitig optimaler Flexibilität.

## Entscheidung

Wir implementieren das Prinzip **"First-to-Hit" (Wer zuerst eintrifft, gewinnt)**:
- **Zeitlimit (`duration_minutes`)**: Maximale Laufzeit.
- **Volumenlimit (`target_volume_liters`)**: Maximale Durchflussmenge.

Bei jedem Bewässerungsstart werden zwei Überwachungsprozesse parallel gestartet:
1. Ein klassischer Software-Timer (`threading.Timer`) für die Dauer in Minuten.
2. Ein ständiger Hintergrund-Thread, der alle 5 Sekunden die geflossene Wassermenge über die MQTT-Statusmeldungen des Ventils aufsummiert und mit dem Liter-Limit abgleicht.

Sobald einer der beiden Wächter anschlägt (Zeit abgelaufen ODER Literlimit erreicht), wird das Schließen des Ventils ausgelöst und der Benutzer über die genaue Ursache benachrichtigt (z. B. *"Abschaltung nach 50 Litern in 11 Minuten"* oder *"Abschaltung nach Ablauf von 15 Minuten bei geflossenen 12 Litern"*).

## Konsequenzen

- **Vorteile**:
  - Maximale Flexibilität: Der Benutzer entscheidet selbst über das Sicherheitsfenster und die gewünschte Gießintensität.
  - Höchste Betriebssicherheit: Zeitlimits dienen automatisch als dynamisches Fail-Safe für den Durchflusssensor (und umgekehrt).
- **Nachteile**:
  - Das Datenbank-Schema muss permanent beide Werte verwalten (was die Datenhaltung jedoch vereinheitlicht, da es keine unterschiedlichen Spaltenlayouts pro Modus mehr gibt).
