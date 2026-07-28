# Feature: Aktionsfähige Benachrichtigungen

## Problemstellung (Problem Statement)

Die Push-Benachrichtigungen des Bots sind einseitige Durchsagen. Wenn der Bot meldet „Bewässerung gestartet", muss der Benutzer ins Hauptmenü wechseln und „Sofort Stopp" suchen, um zu reagieren. Ein Watchdog-Alarm („Ventil meldet sich nicht") bietet keine direkte Möglichkeit, den Status zu prüfen oder die Warnung stummzuschalten. Ein Regen-Skip lässt keine Option „trotzdem gießen" zu. Genau im Moment, in dem der Benutzer informiert wird und reagieren möchte, fehlt die Handlungsmöglichkeit — die Benachrichtigung ist eine Sackgasse.

## Lösung (Solution)

Push-Benachrichtigungen erhalten kontextbezogene Inline-Buttons, die die jeweils naheliegende Folgeaktion direkt anbieten. Aus einseitigen Durchsagen wird eine Fernbedienung: Der Benutzer handelt unmittelbar aus der Benachrichtigung heraus, ohne ins Menü zu wechseln. Technisch baut das vollständig auf vorhandener Infrastruktur auf — Inline-Keyboards und der bestehende `callback_query`-Verarbeitungspfad.

## User Stories

1. Als Benutzer möchte ich aus der „Bewässerung gestartet"-Nachricht heraus mit einem Tipp stoppen können — besonders bei einem **unbeaufsichtigt** gestarteten Zeitplan-Guss, wo die Meldung mein einziger Berührungspunkt ist.
2. Als Benutzer möchte ich bei „Ventil von außen geöffnet" mit einem Tipp **schließen** können — ein Sicherheitsereignis, bei dem ich sofort reagieren will.
3. Als Benutzer möchte ich bei einem Watchdog-Alarm direkt „Status prüfen" auslösen können, um schnell mehr zu erfahren.
4. Als Benutzer möchte ich bei einem regenbedingten Skip die Option „Zeitplan jetzt gießen" haben (mit den Werten genau dieses Zeitplans), falls ich die Bewässerung bewusst erzwingen will.
5. Als Benutzer möchte ich, dass ein bereits gedrückter Aktions-Button erkennbar quittiert wird (kein doppeltes Auslösen, keine veraltete Aktion).
6. Als Benutzer möchte ich, dass Aktions-Buttons nur dort erscheinen, wo eine sinnvolle Folgeaktion existiert — sonst bleibt die Nachricht schlicht.

> **Nicht (mehr) enthalten (Recherche 2026-07-28):** „wiederkehrende Warnung stummschalten" — die Watchdog-Alarme feuern bereits nur *einmal* pro Episode (flanken-getriggert), es gibt keine Wiederholung zu unterdrücken. Eine „niedrige Batterie"-Push-Meldung existiert gar nicht (nur Anzeige in Status/Bericht). **Folgeaktionen nach Kopplung** (Ventil/Kamera) sind in ein eigenes Folgeticket (55t) ausgegliedert. Details unter *Implementierungs-Entscheidungen*.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Aufbau auf Bestand:** Inline-Keyboards (`reply_markup`) an `broadcast_notification` durchreichen; neue `callback_data`-Präfixe im bestehenden `_process_callback_query`-Pfad. Kein neuer Transportweg. Die Zuordnung *Ereignis → Button(s)* wird als kleine **Registry** gehalten (analog zur cy1-`WizardSpec`), nicht als handverdrahtetes `reply_markup=` in ~10 Handlern.

- **Button-Zuordnung — priorisierter Katalog (Recherche 2026-07-28):** Von ~26 Push-Meldungen trägt bislang genau eine einen Button (Regen-Übersteuerung). Die übrigen Aktionen existieren größtenteils schon als Callbacks; „andocken" statt neu bauen.

  **Pilot (höchster Wert):**
  - ⚠️ *Ventil von außen geöffnet* (`_on_unexpected_valve_opened`) → `🛑 Schließen`. Sicherheit, unerwartet, Ein-Tipp-Behebung. An `stop_extern_<name>`.
  - 🚿 *Wasser marsch! / Guss gestartet* — **Zeitplan & manuell** (`_on_watering_started`) → `🛑 Stoppen`. Der unbeaufsichtigte Zeitplan-Start ist der kanonische mtb-Fall (die Meldung ist der einzige Berührungspunkt). An `stop_valve_all`/`_watering_ctrl.stop_watering()`.

  **Stark:**
  - 🌫️ *Nebel-Intervall gestartet* (`_on_nebel_interval_started`) → `🛑 Nebel stoppen` (`nebel_stop`/`stop_nebel_<name>`).
  - ⚠️ *Ventil-Verbindung verloren* (`_on_inactivity_alert`) → `🔄 Status` (`handle_status`).
  - 🌧 *Guss übersprungen* (`_on_watering_skipped`) → `🚿 Zeitplan jetzt gießen` — führt den **übersprungenen** Zeitplan mit dessen Dauer/Menge/Ventil aus (nicht generische Defaults).

  **Optional / später:**
  - ⚠️ *Kamera-Inaktivität / -Verzug*, *Regensensor nicht erreichbar* → `🔄 Status`.
  - 💧 *Guss reduziert* (`_on_watering_scaled`) → `🚿 Voll gießen` (nachträgliches Override; schwächer, der Guss lief bereits reduziert).
  - ⚠️ *Update unterbrochen / fehlgeschlagen* → `🔄 Status` bzw. `🔁 Erneut`.
  - ⚠️ *Guss fehlgeschlagen*, *Fehler bei Zeitplan* → `🔄 Status`.

  **Eigenes Folgeticket (55t) — nicht in mtb:** Folgeaktionen nach erfolgreicher/fehlgeschlagener **Kopplung** (Ventil „Kurz testen"/„Zeitplan anlegen", Kamera „Foto jetzt"/„Einstellungen", „Erneut koppeln"). Kommen aus den Pairing-Workern (`notify_fn`), nicht aus `broadcast_notification` — bewusst separat gehalten.

  **Bewusst ohne Button:** alle terminalen/Info-Meldungen (…beendet/gestoppt/wiederhergestellt/wieder pünktlich/geschlossen), 🌧 *Regen erkannt* / 🌤 *Regen vorbei*, 🚀 *Update aktiv*, 🏁 *Guss fertig*, Tagesbericht, Foto-Zustellung.

- **Idempotenz & Veralterung:** Ein Aktions-Button wird quittiert (`answer_callback_query`) und die Meldung nach der Aktion editiert (Buttons weg + „✓"-Zeile, ADR 0038/0039). Abgelaufene Aktionen (z. B. „Stoppen" ohne laufenden Guss) liefern einen sachlichen Hinweis statt eines Fehlers. „Stoppen" wirkt bewusst als **Alles-Stopp** (der Nutzer will „Wasser aus"), nicht gezielt-per-Guss.

- **Aus dem Umfang genommen (Recherche 2026-07-28):**
  - **Stummschaltung** — alle Watchdog-Alarme sind bereits **flanken-getriggert** (Flag in System-Metadaten): sie feuern *einmal* pro Episode und melden die Erholung eigens. Es gibt keine wiederkehrenden Warnungen, also nichts zu „muten"; statt `🔇 stumm` tragen die Alarme `🔄 Status`.
  - **Niedrige Batterie → Erledigt** — es existiert **keine** Batterie-Push-Meldung; der Schwellwert erscheint nur in Status & Tagesbericht. Kein Auslöser, an den ein Button hängen könnte (bräuchte erst ein eigenes „Batterie-Alarm"-Feature).
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
