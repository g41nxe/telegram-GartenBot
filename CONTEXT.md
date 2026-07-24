# Gartenbewässerungs-Steuerung

Dieses System steuert lokal die automatisierte Bewässerung eines Gartens unter Berücksichtigung von Zeitplänen und Umweltdaten.

## Language

**Steuerzentrale**:
Der Raspberry Pi Zero W, welcher die Steuerungslogik ausführt, Zeitpläne verwaltet und die Schnittstelle zum Ventil darstellt.
_Avoid_: Server, Zentralrechner, Pi

**Ventil**:
Eines oder mehrere physische Sonoff Hydro ONE Smart-Wasserlaufventile (Zigbee 3.0) zur Freigabe/Sperrung des Wasserdurchflusses und Erfassung der Durchflussmenge. Jedes Ventil besitzt einen eigenen Wunschnamen und eine eindeutige ID im System.
_Avoid_: Schalter, Regler, Sonoff-Gerät

**Funk-Koordinator**:
Der an der Steuerzentrale angeschlossene USB-Zigbee-Dongle, welcher die drahtlose Kommunikation mit dem Ventil ermöglicht.
_Avoid_: Gateway, Hub, Router

**Mittelweg-Dienst**:
Die auf der Steuerzentrale laufende Bridge-Software (Zigbee2MQTT), welche die Zigbee-Funksignale des Ventils in lokale MQTT-Nachrichten übersetzt.
_Avoid_: Funk-Treiber, Bridge-Server

**Bewässerungs-Daemon**:
Der in Python implementierte Hintergrunddienst auf der Steuerzentrale, welcher die Steuerungslogik ausführt, MQTT-Nachrichten verarbeitet, Zeitpläne steuert und Wetterdaten abfragt.
_Avoid_: Backend, Server-Prozess

**Datenbank**:
Die lokale SQLite-Datei, in welcher Zeitpläne, Bewässerungsprotokolle und erfasste Umweltdaten dauerhaft gespeichert werden.
_Avoid_: DB-Server, SQL-Server

**Wetter-Dienst**:
Die externe Online-Wetter-API (z. B. Open-Meteo), über welche der Bewässerungs-Daemon zwei Produkte abruft: lokale Wettervorhersagen (Forecast-Modell) und historische, messbasierte Regenmengen (Archiv/ERA5-Reanalyse), um Bewässerungsentscheidungen zu treffen.
_Avoid_: Wetterstation, Wettersensoren (meint eigene Hardware, nicht die API)

**Telegram-Bot**:
Die primäre, gesicherte Benutzeroberfläche, über welche der Benutzer mit dem Bewässerungs-Daemon über Chat-Befehle und interaktive Buttons kommuniziert und Benachrichtigungen erhält.
_Avoid_: Cockpit, Web-App, Dashboard

**Sicherheits-Timeout**:
Die hardwareseitige Schutzfunktion (Auto-Close / Fail-Safe) des Ventils, die den Wasserfluss nach einer maximalen Schutzdauer (z. B. 30 Minuten) physisch stoppt, falls der reguläre Abschaltbefehl ausbleibt. Beim Sonoff Hydro ONE wird dies über das Parameter-Feld `manual_default_settings.fail_safe` des Mittelweg-Dienstes gesteuert.
_Avoid_: Software-Timer, Abschaltzeit, Inching

**Wetterdaten-Stand**:
Der im Telegram-Bot angezeigte Zeitstempel (Uhrzeit), welcher angibt, wann die Wetter- und Temperaturdaten zuletzt erfolgreich vom Wetter-Dienst abgerufen wurden.
_Avoid_: Abrufzeitpunkt, API-Zeit

**Kombinierter Guss**:
Ein Bewässerungslauf, der durch eine maximale Dauer (Zeitlimit) und eine maximale Wassermenge (Volumenlimit) definiert ist. Die Bewässerung stoppt automatisch, sobald einer der beiden Grenzwerte zuerst erreicht wird. Im parallelen Betrieb gilt dies individuell pro Ventil.
_Avoid_: Dual-Modus, Mengen-Guss, Zeit-Guss

**Guss-Volumen**:
Die im aktuellen Kombinierten Guss tatsächlich geflossene Wassermenge in Litern. Quelle ist `irrigation_schedule_status.actual_irrigation_amount` des Ventils — die live mitlaufende Menge der aktuellen Bewässerungs-Session, die pro Session bei 0 startet und nur gültig ist, solange `schedule_status == "running"`. **Nicht** zu verwechseln mit `real_time_irrigation_volume`, dem kumulativen geräteweiten Zähler, der während eines Gusses still steht und erst verspätet springt. Wird gegen das Volumenlimit geprüft und in der Datenbank protokolliert. Siehe ADR 0007.
_Avoid_: geflossene Menge, current_volume, real_time_irrigation_volume (kumulativer Gerätezähler)

**Mindest-Flussrate**:
Die konfigurierbare untere Schwelle der durchschnittlichen Flussrate (L/min) eines Gusses, unterhalb derer eine Abschaltung durch das Zeitlimit als Defekt gewertet wird (zu wenig oder kein Wasser — Verstopfung, Druckabfall, defektes Ventil) und als Notfall-Abschaltung gemeldet wird. Liegt die erreichte Flussrate darüber, gilt das Erreichen des Zeitlimits als normaler Abschluss des Kombinierten Gusses. Einstellbar über den Telegram-Bot (`MIN_FLOW_RATE_LPM`, Standard 0,5 L/min).
_Avoid_: Durchflussschwelle, Min-Flow

**Assistent**:
Ein mehrstufiger, geführter Eingabe-Dialog im Telegram-Bot (z. B. Zeitplan anlegen, Nebel-Intervall, Ventil-/Kamera-Kopplung, manueller Guss). Ein Assistent führt über genau **eine lebende Prompt-Nachricht**: zu jedem Zeitpunkt gibt es höchstens ein aktives Inline-Keyboard; beim Schritt-Wechsel wird das vorherige Prompt-Keyboard abgeräumt (ADR 0038/0039). Getippte Eingaben des Nutzers bleiben als eigene Nachrichten sichtbar.
_Avoid_: Wizard, Dialog-Flow, Mehrschritt-Formular.

**Ventil-Kopplung**:
Der geführte Einrichtungsvorgang im Telegram-Bot, bei dem ein neues Ventil mit dem Funk-Koordinator verbunden wird. Der Benutzer vergibt vorab einen Wunschnamen. Der Bewässerungs-Daemon aktiviert temporär den Koppelmodus des Mittelweg-Dienstes, wartet auf das Beitrittssignal des Ventils, weist ihm einen eindeutigen Systemnamen (`valve_<ieee_address>`) zu und registriert es in der Datenbank.
_Avoid_: Pairing, Registrierung, Gerät hinzufügen

**Guss-Steuerung**:
Die softwareseitige Kernkomponente des Bewässerungs-Daemons, welche die zeit- und volumenbasierte Grenzüberwachung des Kombinierten Gusses ausführt und den physischen Ventil-Zustand kontrolliert. Sie kann mehrere Ventile parallel oder sequentiell steuern.
_Avoid_: Cycle-Controller, Ventil-Manager

**Ereignis-Kanal**:
Systeminterner Kommunikationskanal zur entkoppelten Weiterleitung von Zustandsmeldungen (z. B. Guss gestoppt, Ventil gekoppelt) von der Guss-Steuerung an die Datenbank und die Präsentationsschicht.
_Avoid_: Event-Bus, Message-Broker

**Füllstandssensor**:
Der batteriebetriebene, WLAN-basierte Ultraschallsensor (M5Stack AtomS3 Lite) zur berührungslosen Erfassung des Abstands zur Flüssigkeitsoberfläche in der Klärgrube.
_Avoid_: Distanzmesser, Sensor-Modul, ESP32, Pegelmesser

**Füllstands-Meldung**:
Das vom Füllstandssensor per MQTT an die Steuerzentrale gesendete Datenpaket mit der gemessenen Distanz (in cm) und der aktuellen Batteriespannung.
_Avoid_: Sensor-Signal, Telemetrie-Paket

**Gieß-Empfehlung**:
Die vom Bewässerungs-Daemon berechnete Einschätzung, ob eine manuelle oder geplante Bewässerung heute sinnvoll ist. Basiert auf dem Regen-Fenster (letzte + nächste 24h), der Tagestemperatur und der Hitzestrecke. Wird auf Anfrage über den Telegram-Bot ausgegeben.
_Avoid_: Gieß-Ratschlag, Bewässerungs-Hinweis, Watering-Advice
_Status_: 🚧 In Umsetzung — geplant in Feature 0009 (`docs/features/0009-giesscheck-bewasserungsempfehlung.md`, ADR 0021). Im Code noch nicht aktiv; aktuell existiert nur die Teil-Funktion `evaluate_rain_window` (Regen-Fenster).

**Guss-Vorwarnung**:
Eine Benachrichtigung ~5 Minuten vor dem geplanten Start eines Gusses, die **nur dann** gesendet wird, wenn die Gieß-Empfehlung den Guss wegen Regen **überspringen oder reduzieren** würde. Sie nennt die Details des anstehenden Gusses (Zeitplan, Ventil, Original-Dauer/-Menge, Regen-Begründung) und bietet die Regen-Übersteuerung an. Reagiert der Nutzer nicht, bleibt das automatische Verhalten (Skip/Reduzierung) bestehen.
_Avoid_: Guss-Erinnerung, Skip-Warnung, Pre-Notification
_Status_: 🚧 Geplant — Feature 0034 (ADR 0035). Noch nicht implementiert.

**Hitzestrecke**:
Die Anzahl aufeinanderfolgender abgeschlossener Vortage, an denen die maximale Tagestemperatur einen konfigurierten Schwellenwert (Standard: 25°C) erreicht oder überschritten hat. Eine Lücke (fehlende Wetterdaten, z.B. Steuerzentrale offline) bricht die Hitzestrecke ab.
_Avoid_: Hitzeperiode, Hitzewelle, Hot-Streak
_Status_: 🚧 In Umsetzung — geplant in Feature 0009 (`docs/features/0009-giesscheck-bewasserungsempfehlung.md`, ADR 0022). Im Code noch nicht implementiert.

**Regen-Fenster**:
Die Summe des gefallenen Niederschlags der letzten 24 Stunden (aus gemessenen Archiv-/Reanalyse-Daten des Wetter-Dienstes) und der vorhergesagten Niederschlagsmenge der nächsten 24 Stunden (aus dem Forecast-Modell). Entspricht dem bestehenden Schwellenwert `RAIN_THRESHOLD_MM` und wird sowohl für die Gieß-Empfehlung als auch für die automatische Überspringlogik des Schedulers verwendet.
_Avoid_: Regen-Periode, Niederschlags-Fenster, Rain-Window

**Regen-Übersteuerung**:
Der bewusste, einmalige Eingriff des Nutzers, der die automatische regenbedingte Überspringung oder Reduzierung eines geplanten Gusses für **genau diesen Lauf** aufhebt — der Guss läuft dann mit seinen Original-Werten (Dauer, Menge, Ventil), als gäbe es keinen Regen. Wird über die Guss-Vorwarnung angeboten und beim Guss-Start verbraucht; der nächste Lauf wird wieder regulär bewertet. Ein zu spät ausgelöster Eingriff hat keine Wirkung (nur Hinweis).
_Avoid_: Regen-Override, Force-Watering, Skip-Bypass
_Status_: 🚧 Geplant — Feature 0034 (ADR 0035). Noch nicht implementiert.

**Inaktivitäts-Watchdog**:
Die Überwachungslogik im Bewässerungs-Daemon, die das Ausbleiben regelmäßiger Lebenszeichen von batteriebetriebenen Geräten (z. B. mehr als 18 Stunden beim Füllstandssensor oder mehr als 24 Stunden bei einem Ventil) erkennt und proaktiv über den Telegram-Bot warnt.
_Avoid_: Offline-Timer, Connection-Checker, Heartbeat-Sensor

**Tagesbericht**:
Der automatisch generierte Statusbericht, der täglich um 08:00 Uhr per Telegram-Bot versendet wird und den Systemzustand, die Wetterlage sowie die Zyklenhistorie der letzten 24 Stunden für den Benutzer zusammenfasst. Gegliedert entlang einer Zeitachse: **Rückblick** (Gestern-Block) → **Ausblick** (Heute-Block) → **Zustand** (Zustands-Block als Abschluss).
_Avoid_: Status-Report, Update-Meldung, Daily-Report

**Gestern-Block (Rückblick)**:
Der erste Abschnitt des Tagesberichts unter der Überschrift `*Gestern*`. Fasst das 24-h-Fenster in **zwei kompakten Zeilen** zusammen (Format wie der Heute-Block, `·`-gebündelt): eine **Aktivitätszeile** (Guss 💧 inkl. Nebel-Intervall 🌫️, falls genebelt) und eine **Wetterzeile** (gefallener Regen 🌧 und Temperatur Ø/max 🌡 kombiniert).
_Avoid_: Verlauf, History-Block, Rückschau.

**Heute-Block (Ausblick)**:
Der zweite Abschnitt des Tagesberichts unter der Überschrift `*Heute*`. Einzeilige Wettervorhersage: Bedingungs-Emoji (aus dem WMO-Wettercode) und -Text, Temperatur-Spanne sowie — bei Regen — erwartete Menge und Wahrscheinlichkeit. Scheitert der Live-Abruf, fällt der Block auf die zuletzt gepollten Cache-Werte zurück und trägt dann — **nur in diesem Ausnahmefall** — den **Wetterdaten-Stand** `(Stand: HH:MM Uhr)`; ist der Cache älter als drei Stunden oder leer, tritt `❌ Keine Wetterdaten verfügbar. Bitte später erneut versuchen.` an die Stelle der Vorhersage (ADR 0042).
_Avoid_: Vorschau, Forecast-Zeile, Prognose-Block.

**Zustands-Block**:
Der abschließende Abschnitt des Tagesberichts. Im Normalfall die einzeilige Bestätigung `✅ System: alles in Ordnung` (ohne Ampel-Headline); im Problemfall werden die Warnungen direkt gelistet (Dienst-Ausfall, Ventil-Anomalie, schwache Batterie, Watchdog). Der **Regensensor** ist dabei eine Issue-Quelle im selben Format wie ein Ventil (`🟡 Regensensor: Batterie schwach (X%)`, `⚠️ Regensensor: kein Signal (Watchdog aktiv)`). Steht bewusst am **Schluss** des Berichts (nicht zuvorderst), da kritische Lagen ohnehin über Echtzeit-Benachrichtigungen gemeldet werden.
_Avoid_: Status-Block, Health-Block, Fußzeile.

**Messquelle-Kennzeichnung**:
Im Tagesbericht stammen Regen und Temperatur des Gestern-Blocks im Normalfall vom lokalen Regensensor und tragen **keinen** Quell-Tag (stiller Standard — die Regel schweigt). Nur die Ausnahme wird benannt: Fällt der Sensor aus, liefern **beide** Werte der Wetter-Dienst (Open-Meteo) und tragen dann den Tag `(Open-Meteo)`. Guss (eigene Historie) wird nie getaggt.
_Avoid_: geschätzt, lokal gemessen, online/offline, ERA5 (benutzersichtbar).

**Software-Update (OTA)**:
Das Over-the-Air Update-Verfahren, das dem Benutzer über den Telegram-Bot ermöglicht, neue Releases direkt von GitHub herunterzuladen und auf der Steuerzentrale vollautomatisch zu installieren. Nach einem Update meldet sich die Steuerzentrale **beim nächsten Daemon-Start** von selbst — erfolgreich mit der neuen Version, oder im Fehlerfall mit dem durchgeführten Rollback (ADR 0044).
_Avoid_: Patching, Neu-Installation, Upgrade-Skript

**Gemeldete Version**:
Die zuletzt per Telegram angekündigte Versionskennung (`announced_version` in den System-Metadaten). Der Daemon vergleicht sie beim Start mit der installierten `VERSION`; nur bei Unterschied meldet er ein aktives Update. So bleibt ein reiner Neustart (ohne Versionswechsel) stumm (ADR 0044).
_Avoid_: letzte Version, Update-Flag.

**Garten-Kamera**:
Die M5Stack Timer Camera F, die batteriebetrieben im Garten Bilder aufnimmt und zur Steuerzentrale sendet.
_Avoid_: Cam, M5-Kamera, Kamera-Modul.

**Kamera-Kopplung**:
Der zeitbegrenzte Registrierungsvorgang im Telegram-Bot, bei dem eine neue Garten-Kamera anhand ihrer MAC-Adresse einem Wunschnamen zugeordnet wird.
_Avoid_: Camera Pairing, Kamera-Registrierung.

**Bild-Historie**:
Das Archiv aller empfangenen Bilder auf der Steuerzentrale, sortiert nach Wunschnamen der Garten-Kamera und Zeitstempel.
_Avoid_: Fotos, Image-Archiv.
_UI-Ausnahme_: Im Telegram-Button „Fotos löschen" (Kamera-Untermenü) — Platzmangel rechtfertigt die kürzere Form.

**Kamera-Überwachung**:
Die Erweiterung des Inaktivitäts-Watchdogs, um Störungen einer Garten-Kamera zu erkennen und über den Telegram-Bot zu melden. Sie kennt zwei Alarmklassen: **Inaktivität** (es kommen überhaupt keine Bilder mehr) und **Aufnahme-Verzug** (Bilder kommen, treffen aber ihre Aufnahme-Zeitpunkte nicht mehr).
_Avoid_: Kamera-Watchdog, Offline-Check.

**Bild-Puffer**:
Der temporäre Speicherort für empfangene Einzelbilder der Garten-Kamera, bevor sie zu einem Zeitraffer-GIF zusammengefasst werden.
_Avoid_: Temp-Ordner, Cache, Raw-Archiv.

**Zeitraffer-Zyklus**:
Das konfigurierbare Intervall (in Tagen), nach dem die gesammelten Bilder des Bild-Puffers in ein GIF umgewandelt und die Rohdaten anschließend gelöscht werden.
_Avoid_: GIF-Intervall, Zusammenfassungs-Tage.

**Aufnahme-Zeitpunkt**:
Ein von der Steuerzentrale berechneter Zeitpunkt, zu dem die Garten-Kamera gezielt für ein Foto geweckt wird — im Gegensatz zum regulären Sende-Intervall (Zeitraffer). Zwei Quellen: nach jedem zeitgesteuerten Guss (Startzeit + Dauer + Nach-Offset) sowie global konfigurierte feste Uhrzeiten. Da die Kamera nur über die dynamisch berechnete Schlafdauer gesteuert werden kann (sie schläft und ist nur beim Aufwachen per `GET /config` erreichbar), nähert sich das Aufwachen dem Aufnahme-Zeitpunkt an — es trifft ihn nie exakt. **Erfüllt** wird ein Aufnahme-Zeitpunkt deshalb vom **ersten Bild, das nach ihm eintrifft**; er bleibt offen, bis der nächste Aufnahme-Zeitpunkt ihn ablöst (ADR 0040). Nur erfüllende Bilder werden per Telegram-Bot zugestellt; reguläre Intervall-Bilder nicht.
_Avoid_: Foto-Termin, Trigger-Zeit, Schnappschuss-Zeit.
_UI-Ausnahme_: Im Telegram-Button „Fotozeiten" (Kamera-Untermenü) — Platzmangel rechtfertigt die kürzere Form.

**Aufnahme-Verzug**:
Die Zeitspanne zwischen einem Aufnahme-Zeitpunkt und dem Bild, das ihn erfüllt. Ein kleiner Verzug ist bauartbedingt normal (der Wecker der Garten-Kamera ist auf ±60 s genau, dazu kommt die Bootzeit). Überschreitet er die Verzugs-Schwelle, meldet ihn die Kamera-Überwachung als Störung: Die Kamera **war da**, aber zu spät — ein Hinweis auf scheiternde Zyklen (schwaches WLAN, schwacher Akku).
_Avoid_: Verspätung, Delay, Latenz.

**Verpasster Aufnahme-Zeitpunkt**:
Ein Aufnahme-Zeitpunkt, der von seinem Nachfolger abgelöst wurde, ohne je ein Bild erhalten zu haben. Er hat **keinen** Aufnahme-Verzug — es gibt kein Bild, dessen Aufnahmezeit man messen könnte. Da jeder Upload in seinem Fenster ihn erfüllt hätte, bedeutet er zwingend: Die Garten-Kamera war über das ganze Fenster **stumm**. Er ist damit der schnelle Stille-Melder — der Inaktivitäts-Watchdog schlägt erst nach `max(3 × Schlafintervall, 1 h)` an, bei 4 h Intervall also erst nach zwölf Stunden.
_Avoid_: Maximaler Verzug, ausgefallene Aufnahme, Foto-Ausfall.

**Guss-Foto**:
Ein Aufnahme-Zeitpunkt, der sich automatisch aus einem aktiven Bewässerungs-Zeitplan ergibt: Startzeit + Dauer + Nach-Offset. Das daraus entstehende Foto wird mit dem Namen des auslösenden Zeitplans beschriftet („Nach dem Guss „Rasen""). Erscheint im Telegram-Bot read-only unter „Nach Güssen" (folgt dem Zeitplan, nicht einzeln editierbar).
_Avoid_: Bewässerungs-Foto, Post-Guss-Bild.

**Feste Fotozeit**:
Ein Aufnahme-Zeitpunkt zu einer global konfigurierten, vom Guss unabhängigen Uhrzeit. Wird im Telegram-Bot direkt angelegt und gelöscht und mit der Uhrzeit beschriftet („Foto um 18:00"). Abzugrenzen vom Guss-Foto, das an einen Zeitplan gebunden ist.
_Avoid_: Absolute Fotozeit, Fix-Uhrzeit.

**Regensensor**:
Der batteriebetriebene, WLAN-basierte Niederschlagsmesser (Aqua Scope RANWIE01), der Regenmengen und Temperatur lokal im Garten erfasst und per MQTT an die Steuerzentrale sendet. Er ist die primäre Quelle für gemessene Niederschlagsmengen; die ERA5-Reanalyse des Wetter-Dienstes dient als automatischer Fallback bei Ausfall.
_Avoid_: Wetterstation, Regenmesser, Sensor-Modul.

**Regen-Messung**:
Eine einzelne Meldung des Regensensors. `rainlevel` ist der **Zuwachs seit der letzten Meldung** in 0,5-mm-Kipps der Regenwippe (nicht kumulativ; `raintotal` ist der Lebenszeit-Zähler des Geräts). Auf die Messung reagiert die **Guss-Steuerung** — sie unterbricht beim ersten Kipp.
_Avoid_: Regenwert, Messpunkt.

**Regenereignis**:
Der zusammenhängende Schauer als **Zustand**: beginnt mit dem ersten Kipp und endet erst, wenn die **Karenzzeit** ohne weiteren Kipp verstrichen ist. Trägt Startzeit, Zeitpunkt des letzten Kipps und die aufsummierte Menge; daran hängen die Benachrichtigungen (ADR 0043). Abzugrenzen von der einzelnen **Regen-Messung**.
_Avoid_: Regenphase, Schauer (als Fachbegriff), Regen-Session.

**Karenzzeit**:
Die Zeitspanne ohne Kipp, nach der ein **Regenereignis** als beendet gilt (Standard 45 Minuten). Sie verhindert, dass Lücken zwischen einzelnen Kipps — bei leichtem Regen regelmäßig länger als das Melde-Intervall — fälschlich als Regenende gelten. Sie zählt nicht zur gemeldeten Regendauer.
_Avoid_: Timeout, Cooldown, Nachlaufzeit.

**Regenmessung**:
Das vom Regensensor per MQTT gesendete Datenpaket mit der Niederschlagsmenge des letzten Intervalls (mm), der kumulierten Gesamtmenge, der Temperatur (°C) und dem Batteriestand (%). Wird bei Regen sofort, sonst alle 6 Stunden gesendet.
_Avoid_: Sensor-Signal, Telemetrie-Paket, Messwert.

**Guss-Unterbrechung**:
Der systemseitige vorzeitige Abbruch eines laufenden Kombinierten Gusses durch einen externen Auslöser (z. B. Regen). Im Unterschied zum manuellen Stopp durch den Benutzer wird eine Guss-Unterbrechung im Ereignis-Kanal als eigenständiges Ereignis (`WateringCycleInterrupted`) veröffentlicht.
_Avoid_: Auto-Stop, Notfall-Abbruch, Rain-Stop.

**Unerwartete Ventilöffnung**:
Das Öffnen eines Ventils außerhalb der Kontrolle des Bewässerungs-Daemons — z. B. über den Knopf am Ventil, die Hersteller-App oder einen anderen MQTT-Client — also ohne aktiven Guss in der Guss-Steuerung. Wird zur Laufzeit flankengesteuert erkannt und per Telegram-Bot gemeldet (Ereignis `UnexpectedValveOpened`, Entwarnung `UnexpectedValveResolved`). Der Daemon schließt das Ventil dabei **nicht** — der hardwareseitige Sicherheits-Timeout dient als Flutschutz (ADR 0032). Abzugrenzen von der Guss-Unterbrechung (externer Abbruch eines *laufenden* Gusses) und der einmaligen Sicherheits-Schließung beim Daemon-Start.
_Avoid_: Fremd-Öffnung, Ventil-Manipulation, Tamper.

**Garten-Ampel**:
Das dreistufige Gesundheitsmodell, das den Gesamtzustand des Systems in der `/status`-Anzeige als Farb-Status zusammenfasst: 🟢 grün (alles aktiv und unauffällig), 🟡 gelb (nicht-kritisch: niedrige Batterie oder kritisches Signal, Gerät meldet aber noch), 🔴 rot (kritisch: Dienst offline, aktiver Inaktivitäts-Watchdog-Alarm oder Ventil-Anomalie). Die Headline zeigt stets die schlimmste aktive Stufe; technische Details werden nur für nicht-grüne Geräte eingeblendet. Definiert in ADR 0029.
_Avoid_: Statusampel, Health-Check, Traffic-Light.

**Nebel-Intervall**:
Eine wiederkehrende Kühlfunktion, die ein Ventil in regelmäßigen Abständen kurz öffnet, um über eine Nebeldüse die Terrasse abzukühlen — **kein** Bewässerungs-Vorgang. Definiert durch eine kurze ON-Dauer (Sekunden, der Nebelstoß) und eine Pause (Minuten) zwischen den Stößen, die innerhalb eines Nebel-Fensters wiederholt werden. Im Gegensatz zum Kombinierten Guss gibt es **kein Volumenlimit, keine Regen-Überspringlogik und keine Mindest-Flussrate-Defekterkennung** — die geflossene Wassermenge ist für die Kühlung bedeutungslos. Mechanisch ist es ein eigener Zeitplan-Modus (`mode = "nebel"`), läuft aber über eine eigene Engine (Nebel-Steuerung). Siehe ADR 0033.
_Avoid_: Sprühzyklus, Misting, Vernebelung, Kühl-Guss, Nebel-Bewässerung.

**Nebelstoß**:
Ein einzelnes, sekundenkurzes Öffnen des Nebel-Ventils innerhalb eines Nebel-Intervalls. Wird **nicht** einzeln protokolliert (würde die Datenbank fluten); nur Beginn und Ende des umgebenden Nebel-Fensters werden festgehalten.
_Avoid_: Sprühstoß, Puls, Burst, Schuss.

**Nebel-Steuerung**:
Die softwareseitige Kernkomponente des Bewässerungs-Daemons, die den ON/Pause-Burst-Zyklus eines Nebel-Intervalls mit sekundengenauem Timing fährt (eigener `threading.Timer`-Loop, injizierte `publish_fn`). Pendant zur Guss-Steuerung, aber für die Kühlung statt die Bewässerung. Solange sie ein Ventil bedient, „beansprucht" sie es, damit die Guss-Steuerung dessen reguläre Nebelstöße nicht als Unerwartete Ventilöffnung fehldeutet.
_Avoid_: Nebel-Controller, Misting-Controller, Spray-Engine.

**Nebel-Fenster**:
Der durch Start- und Endzeit (an ausgewählten Wochentagen) definierte Tageszeitraum, in dem ein geplantes Nebel-Intervall aktiv ist. Wird zustandslos aus dem Zeitplan abgeleitet: nach einem Daemon-Neustart prüft der Scheduler, ob die aktuelle Zeit in einem Nebel-Fenster liegt, und nimmt den Takt wieder auf.
_Avoid_: Nebel-Zeitraum, Kühlphase, Sprüh-Fenster.

**Sofort-Nebel**:
Ein manuell über den Telegram-Bot gestartetes Nebel-Intervall außerhalb jedes Zeitplans. Der Benutzer wählt beim Start eine Laufzeit; eine konfigurierte Maximaldauer begrenzt ihn zusätzlich als Backstop. Ein Sofort-Nebel wird **nicht** persistiert und verfällt bei einem Daemon-Neustart.
_Avoid_: Manuell-Nebel, Ad-hoc-Nebel, Test-Nebel.

**Diagnose-Paket**:
Ein auf Anfrage über den Telegram-Bot (Befehl `/diagnose`) erzeugtes Archiv zur Ferndiagnose der Steuerzentrale ohne direkten Zugriff. Enthält Journal-Auszüge des Bewässerungs-Daemons und des Mittelweg-Dienstes, einen konsistenten Schnappschuss der Datenbank, die fachliche Konfiguration sowie einen System-Steckbrief (Version, Laufzeit, freier Speicher, Dienst-Zustände). Enthält niemals Geheimnisse (Zugangsdaten). Wird nur an den anfragenden, autorisierten Chat gesendet. Fällt ein Baustein beim Einsammeln aus, entsteht ein unvollständiges Paket mit ausgewiesener Lückenliste — der Befehl scheitert nie im Ganzen, solange mindestens ein Baustein einsammelbar ist.
_Avoid_: Debug-Dump, Log-Export, Support-Bundle.
