# Feature: Aktionsfähige Benachrichtigungen

## Problemstellung (Problem Statement)

Die Push-Benachrichtigungen des Bots sind einseitige Durchsagen. Wenn der Bot meldet „Bewässerung gestartet", muss der Benutzer ins Hauptmenü wechseln und „Sofort Stopp" suchen, um zu reagieren. Ein Watchdog-Alarm („Ventil meldet sich nicht") bietet keine direkte Möglichkeit, den Status zu prüfen oder die Warnung stummzuschalten. Ein Regen-Skip lässt keine Option „trotzdem gießen" zu. Genau im Moment, in dem der Benutzer informiert wird und reagieren möchte, fehlt die Handlungsmöglichkeit — die Benachrichtigung ist eine Sackgasse.

## Lösung (Solution)

Push-Benachrichtigungen erhalten kontextbezogene Inline-Buttons, die die jeweils naheliegende Folgeaktion direkt anbieten. Aus einseitigen Durchsagen wird eine Fernbedienung: Der Benutzer handelt unmittelbar aus der Benachrichtigung heraus, ohne ins Menü zu wechseln. Technisch baut das vollständig auf vorhandener Infrastruktur auf — Inline-Keyboards und der bestehende `callback_query`-Verarbeitungspfad.

## User Stories

1. Als Benutzer möchte ich aus der „Bewässerung gestartet"-Nachricht heraus mit einem Tipp stoppen können, ohne ins Menü zu wechseln.
2. Als Benutzer möchte ich bei einem Watchdog-Alarm direkt „Status prüfen" auslösen können, um schnell mehr zu erfahren.
3. Als Benutzer möchte ich eine wiederkehrende Warnung (z. B. niedrige Batterie) direkt aus der Nachricht für eine Weile stummschalten können, damit ich nicht wiederholt erinnert werde.
4. Als Benutzer möchte ich bei einem regenbedingten Skip die Option „Trotzdem gießen" haben, falls ich die Bewässerung bewusst erzwingen will.
5. Als Benutzer möchte ich, dass ein bereits gedrückter Aktions-Button erkennbar quittiert wird (kein doppeltes Auslösen, keine veraltete Aktion).
6. Als Benutzer möchte ich, dass Aktions-Buttons nur dort erscheinen, wo eine sinnvolle Folgeaktion existiert — sonst bleibt die Nachricht schlicht.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Aufbau auf Bestand:** Inline-Keyboards (`reply_markup`) an `broadcast_notification` durchreichen; neue `callback_data`-Präfixe im bestehenden `_process_callback_query`-Pfad behandeln. Kein neuer Transportweg.
- **Button-Zuordnung (Erstausbau):**
  - Guss gestartet → `🛑 Stoppen` (ruft die bestehende `stop_watering`-Logik).
  - Watchdog-Alarm (Ventil/Kamera) → `🔄 Status` und `🔇 24 h stummschalten`.
  - Regen-Skip → `🚿 Trotzdem gießen` (startet einen manuellen Guss mit Standardwerten bzw. öffnet den manuellen Assistenten).
  - Niedrige Batterie / wiederkehrende Warnung → `✅ Erledigt` (quittiert, unterdrückt Wiederholung bis zur Erholung).
- **Idempotenz & Veralterung:** Ein Aktions-Button wird quittiert (`answer_callback_query`); abgelaufene/irrelevante Aktionen (z. B. „Stoppen", obwohl der Guss bereits beendet ist) liefern eine klare, sachliche Rückmeldung statt eines Fehlers.
- **Stummschaltung:** Der Stummschalt-Zustand wird wie bestehende Watchdog-Flags in den System-Metadaten gehalten (Flanken-/Zeitlogik analog zum Inaktivitäts-Watchdog), nicht im Speicher.
- **Design-System-Konform:** Button-Beschriftungen und Begleittexte folgen ADR 0029 (Register, Emoji-Semantik, „du"). Aktions-Emojis kollidieren nicht mit den Status-Ampelfarben.
- **Sicherheitsrelevante Aktionen:** „Trotzdem gießen" respektiert das Hardware-Sicherheits-Timeout und die bestehenden Volumen-/Zeitgrenzen; keine Umgehung der Flood-Prevention.
- **Architektur:** Die Benachrichtigungs-Handler in der UI-Schicht bleiben Abonnenten des Ereignis-Kanals; sie reichern die Nachricht lediglich um ein Inline-Keyboard an. Keine Kopplung von Core an die UI.

## Test-Entscheidungen (Testing Decisions)

- **Test-Nahtstelle (Seam):** `tests/ui/test_telegram_ui.py` mit gemocktem `telegram_client`. Tests prüfen, dass die richtige Benachrichtigung das erwartete Inline-Keyboard trägt und dass der zugehörige `callback_data`-Zweig die korrekte Aktion (z. B. `stop_watering`) auslöst.
- **Idempotenz:** Test, dass „Stoppen" ohne laufenden Guss eine sachliche Hinweismeldung liefert statt eines Fehlers.
- **Stummschaltung:** Tests für Setzen/Ablauf des Stummschalt-Flags und dass während der Stummschaltung keine Wiederholungs-Warnung gesendet wird.
- **Kein Logik-Bypass:** Test, dass „Trotzdem gießen" die bestehenden Grenzwerte/das Sicherheits-Timeout respektiert.
- **Referenz-Pflege:** Neue/aktionsfähige Benachrichtigungen werden in der IST-Referenz nachgezogen (Pflicht laut `.claude/rules/telegram_messages.md`).

## Nicht im Leistungsumfang (Out of Scope)

- **Migration der Bestandsnachrichten** auf das Design-System (eigenes Feature 0017) — dieses Feature setzt darauf auf, ergänzt aber nur die Aktions-Buttons.
- **Komplexe mehrstufige Dialoge** aus Benachrichtigungen heraus (z. B. vollständiger Guss-Assistent inline) — zunächst nur Ein-Tipp-Aktionen.
- **Kontextsensible Vorschläge** („heute Nacht Regen erwartet, trotzdem gießen?") — eigene Idee, nicht Teil dieses Features.

## Weitere Anmerkungen (Further Notes)

- Dieses Feature wurde in einer Produktdesign-Bewertung als der höchste Hebel pro Aufwand identifiziert: Es verändert das Produktgefühl vom „Anschlagbrett" zur „Fernbedienung", ohne neue Infrastruktur zu benötigen.
- Baut auf der ereignisgetriebenen Architektur (ADR 0008) und den Bestätigungs-Tastaturen (ADR 0013) auf.
- Sinnvoll umzusetzen **nach** Feature 0017, damit die neuen Buttons direkt dem Design-System entsprechen.
