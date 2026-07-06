# Feature: Diagnose-Paket per `/diagnose` (Ferndiagnose ohne SSH)

Beads-Issue: `telegram-GartenBot-sc7` · Begriff: **Diagnose-Paket** (`CONTEXT.md`)

## Problemstellung (Problem Statement)

Wenn sich der Bewässerungs-Daemon unerwartet verhält (z. B. ein Tagesbericht mit offensichtlich falschen Wetterwerten), braucht die Fehlersuche die Journal-Einträge und den Datenbank-Zustand der Steuerzentrale. Die Steuerzentrale ist jedoch bewusst ohne offene Ports aufgebaut und physisch nicht immer erreichbar — der Benutzer steht dann mit einer sichtbaren Anomalie da, kann aber die Ursache nicht untersuchen. Genau in dem Moment, in dem Diagnosedaten gebraucht werden, sind sie unerreichbar.

## Lösung (Solution)

Ein neuer Telegram-Befehl `/diagnose` erzeugt auf der Steuerzentrale ein **Diagnose-Paket** — ein Archiv mit Journal-Auszügen (Bewässerungs-Daemon und Mittelweg-Dienst), einem konsistenten Schnappschuss der Datenbank, der fachlichen Konfiguration und einem System-Steckbrief — und sendet es als Datei direkt in den anfragenden, autorisierten Chat. Der Benutzer erhält damit von überall die vollständige Diagnose-Grundlage, ohne SSH- oder physischen Zugriff. Teilausfälle beim Einsammeln degradieren zu einem unvollständigen Paket mit ausgewiesener Lückenliste — der Befehl scheitert nie im Ganzen, solange mindestens ein Baustein einsammelbar ist.

## User Stories

1. Als Benutzer des Telegram-Bots möchte ich mit `/diagnose` ein Diagnose-Paket anfordern, um Logs und Daten der Steuerzentrale zu erhalten, ohne physischen oder SSH-Zugriff zu benötigen.
2. Als Benutzer möchte ich sofort eine Quittung erhalten („Diagnose-Paket wird erstellt…"), um zu wissen, dass mein Befehl angekommen ist, auch wenn die Erstellung einige Sekunden dauert.
3. Als Benutzer möchte ich das Diagnose-Paket als Datei im Chat erhalten, um es auf einem PC zu speichern und zu analysieren.
4. Als Benutzer möchte ich im Paket die letzten Journal-Zeilen des Bewässerungs-Daemons finden, um Fehler (z. B. fehlgeschlagene Wetterabrufe) zeitlich und inhaltlich nachvollziehen zu können.
5. Als Benutzer möchte ich zusätzlich das Journal des Mittelweg-Dienstes einsehen können, um Funk- und Ventil-Probleme zu diagnostizieren, die nur dort sichtbar sind.
6. Als Benutzer möchte ich einen konsistenten Schnappschuss der Datenbank erhalten, um Zeitpläne, Bewässerungs-Historie und Wetter-Cache offline inspizieren zu können, ohne den laufenden Bewässerungs-Daemon zu stören oder eine korrupte Kopie zu riskieren.
7. Als Benutzer möchte ich die fachliche Konfiguration im Paket sehen, um Schwellenwerte und Einstellungen bei der Analyse zu berücksichtigen.
8. Als Benutzer möchte ich einen System-Steckbrief (Version, Python-Version, Laufzeit, freier Speicher, Zustand der drei Dienste), um Standard-Rückfragen sofort beantwortet zu haben.
9. Als Benutzer möchte ich sicher sein, dass niemals Geheimnisse (Bot-Token, Zugangsdaten, `.env`) im Paket landen, um es bedenkenlos aufbewahren und weitergeben zu können.
10. Als Benutzer möchte ich bei Teilausfällen (z. B. fehlende Journal-Berechtigung) trotzdem ein unvollständiges Paket mit klar ausgewiesener Lückenliste erhalten, um in Notlagen nicht mit leeren Händen dazustehen.
11. Als Benutzer möchte ich, dass nur autorisierte Chats den Befehl auslösen können und das Paket ausschließlich an den Anfragenden gesendet wird, damit Diagnosedaten nicht unkontrolliert verteilt werden.
12. Als Benutzer möchte ich `/diagnose` im registrierten Befehlsmenü des Telegram-Bots finden, um den Befehl auch Monate später ohne Erinnerung an den genauen Namen wiederzufinden.
13. Als Benutzer möchte ich, dass der Telegram-Bot während der Paket-Erstellung bedienbar bleibt, um parallel z. B. `/status` abfragen zu können.
14. Als Benutzer möchte ich bei Übergröße des Pakets zumindest die Journal-Auszüge erhalten (die Datenbank wird dann weggelassen und das ausgewiesen), damit das Telegram-Größenlimit die Diagnose nicht verhindert.
15. Als Benutzer möchte ich in der Antwort die Paketgröße und eventuelle Lücken genannt bekommen, um die Vollständigkeit sofort einschätzen zu können.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Neues Adapter-Modul „Diagnose"** mit einer reinen Sammel-Funktion: Sie liefert die Archiv-Bytes plus eine Lückenliste (welche Bausteine fehlten und warum). Jeder Baustein wird unabhängig eingesammelt; ein Fehler in einem Baustein erzeugt einen Lücken-Eintrag statt eines Gesamtabbruchs.
- **Bausteine des Pakets**: Journal-Auszug Bewässerungs-Daemon (letzte ~2000 Zeilen), Journal-Auszug Mittelweg-Dienst (letzte ~500 Zeilen), Datenbank-Schnappschuss, fachliche Konfiguration (`garden.conf`), System-Steckbrief.
- **Journal-Beschaffung** über einen `journalctl`-Subprozess ohne root-Rechte. Verweigerte Berechtigung oder fehlendes Kommando führt zum Lücken-Eintrag (Degradations-Politik).
- **Datenbank-Schnappschuss** ausschließlich über die SQLite-Online-Backup-API (konsistent bei laufendem Daemon); niemals eine Roh-Kopie der laufenden WAL-Datei.
- **Harte Ausschlussliste**: `.env`/Zugangsdaten und Kamera-Bilder gelangen unter keinen Umständen ins Archiv; ein Test erzwingt dies dauerhaft.
- **Größen-Wächter**: Überschreitet das Archiv die sichere Grenze unterhalb des Telegram-Upload-Limits (50 MB), wird der Datenbank-Baustein entfernt, neu gepackt und der Verzicht in Antwort und Lückenliste ausgewiesen.
- **Telegram-Client erhält die neue Fähigkeit „Dokument senden"** (multipart-Upload, analog zum bestehenden Foto-Versand, inklusive Token-Guard).
- **UI-Ablauf**: Neuer Befehls-Handler im Dispatcher; sofortige Quittungs-Nachricht; anschließend Einsammeln, Packen und Senden in einem **Hintergrund-Thread** (`daemon=True`, Thread-Hygiene-Regel), damit der Polling-Thread reaktiv bleibt; währenddessen Chat-Action „lädt Dokument hoch".
- **Zustellung nur an den anfragenden Chat** (kein Broadcast) — etabliertes Antwort-Muster der Befehle.
- **Befehls-Registrierung**: `/diagnose` wird ins registrierte `/`-Menü aufgenommen (vierter Eintrag). De-dup-Regel (ADR 0034) ist erfüllt: kein gleichwertiger Tastatur-Button; als Rettungswerkzeug bewusst über den robustesten Zugang (getippter Befehl) erreichbar statt über ein Untermenü.
- **Kein Core-Anteil, keine Ereignis-Kanal-Events**: reines Anfrage-Antwort-Muster wie `/status`; es entstehen keine Domänenregeln.
- **Setup-Härtung**: Das Installationsskript nimmt den Dienst-Benutzer künftig in die Journal-Lesegruppe auf, damit frische Installationen die Journal-Lücke gar nicht erst haben (Bestandsinstallationen bleiben unverändert und werden von der Degradations-Politik aufgefangen).

## Test-Entscheidungen (Testing Decisions)

- **Verhalten statt Implementierung testen**: Geprüft wird die Inhaltsliste des erzeugten Archivs, die Lückenliste, die gesendeten Nachrichten/Dokumente und die Ausschluss-Garantie — nicht interne Aufrufreihenfolgen.
- **Nahtstellen (von oben nach unten)**:
  1. **UI-Handler + Dispatcher** (höchste Naht): `/diagnose` mit gemocktem Telegram-Client und gemockter Sammel-Funktion → Quittung gesendet, Dokument gesendet, Lücken in der Antwort ausgewiesen. Referenzmuster: bestehende Handler-Tests in `tests/ui/test_telegram_ui.py`.
  2. **Sammel-Funktion** (Kern-Naht): temporäre Datenbank + gemockter Subprozess → Archiv enthält erwartete Einträge; Journal-Fehler erzeugt Lücke statt Abbruch; `.env` erscheint nie im Archiv (auch wenn im Arbeitsverzeichnis vorhanden); Übergröße wirft die Datenbank ab.
  3. **Dokument-Versand im Telegram-Client**: gemockter HTTP-Layer, Assertions auf multipart-Aufbau und Token-Guard. Referenzmuster: `tests/ui/test_telegram_client.py`.
  4. **Wiring-Smoke**: Befehlsregistrierung enthält `diagnose` (Regel 6, ARCHITECTURE.md).
- **Thread-Verhalten**: Die Sammel-Funktion wird in Tests synchron aufgerufen (kein sleep-basiertes Testen); der Hintergrund-Thread wird über das Daemon-Flag und den Handler-Vertrag abgesichert.

## Nicht im Leistungsumfang (Out of Scope)

- **Auto-Trigger** (automatisches Diagnose-Paket bei Fehlerhäufung) — bewusst verschoben; eigenes Folge-Feature auf derselben Sammel-Logik.
- **GitHub-Upload-Transport** (dauerhafte Ablage von Paketen als Release-Assets) — Option 2 der Recherche; bei Bedarf später mit Transport-Naht andockbar.
- **Mosquitto-Journal** und **Kamera-Bilder** im Paket.
- **Rotierender Datei-Logger** im Bewässerungs-Daemon (Absicherung gegen Journal-Berechtigungsprobleme für die Zukunft).
- **Nachträgliche Rechte-Korrektur auf Bestandsinstallationen** (Gruppen-Mitgliedschaft erfordert einmaligen Shell-Zugriff; die Degradations-Politik überbrückt das).

## Weitere Anmerkungen (Further Notes)

- **Unmittelbarer Anwendungsfall**: Der Wetter-Fehler im Tagesbericht („Sonnig / Klar · 0–0 °C · 0 %" bei gleichzeitigem Regen im Chart). Da das OTA-Update den Dienst nur neu startet (kein Reboot), übersteht das Journal die Installation dieses Features — die fraglichen Zeilen von heute Morgen sind nach `/update` → `/diagnose` voraussichtlich noch enthalten.
- **Privatsphäre-Abwägung**: Das Daemon-Journal enthält die geloggte Wetter-URL inklusive Standort-Koordinaten. Bewusst akzeptiert, da das Paket ausschließlich an den autorisierten, anfragenden Chat geht.
- **Telegram-Limit**: Bot-Uploads sind auf 50 MB begrenzt; der Größen-Wächter hält gezielt Abstand darunter.
- **Doku-Pflichten (DoD)**: Sitemap (`telegram-sitemap.html`, neuer registrierter Befehl), Nachrichten-Referenz (`telegram-nachrichten.html`, Quittung/Antwort/Fehlerfälle), README + `bot_description.md` (Befehlslisten), De-dup-Regeldatei (gültige Befehle: + `/diagnose`), `CONTEXT.md` (bereits erledigt: Begriff „Diagnose-Paket", Status bei Abschluss auf aktiv setzen).
