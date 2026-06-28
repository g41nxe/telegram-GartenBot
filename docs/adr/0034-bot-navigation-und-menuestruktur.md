# 34. Bot-Navigation und Menüstruktur

Wir legen die Navigations- und Menüstruktur des Telegram-Bots verbindlich fest: einheitlich deutsche, nach Domäne gruppierte Befehle, klar geschnittene Untermenüs und eine systemweit einheitliche Ventil-Bedienung. Dieser ADR bündelt die Gesamtentscheidung des Bot-UX-Redesigns (Feature 0031).

## Kontext

Die Telegram-Befehle sind organisch gewachsen: gemischte Sprachen (`/photo`, `/report`, `/setup` neben `/zeitplan`, `/giesscheck`), Kamera-Funktionen über mehrere Standalone-Befehle verstreut, ein überladenes registriertes `/`-Menü und Legacy-Befehle (`/add`, `/delete`, `/toggle`), die seit Feature 0021 durch Wizard-UI ersetzt sind. Gleichzeitig ist die Multi-Ventil-Fähigkeit (ADR 0015) in der UI nur teilweise sichtbar: Zeitpläne erhielten in v1.11.0 eine Ventil-Auswahl, der manuelle Sofort-Guss und der Stopp jedoch nicht. Der Sofort-Nebel (ADR 0033) lebt unstrukturiert in der Zeitplan-Ansicht.

## Entscheidung

1. **Deutsch und nach Domäne gruppiert.** Alle Befehle werden auf Deutsch umbenannt (sauberer Schnitt, keine Aliases). Kamera-Funktionen bündeln sich im Untermenü „📷 Kamera"; Kopplung/Schwellen/Update im Untermenü „⚙️ Einstellungen". Das registrierte `/`-Menü schrumpft auf vier Einträge (`/tagesbericht`, `/zeitplaene`, `/einstellungen`, `/stopp`) — nur, was nicht ohnehin per Tastatur erreichbar ist.

2. **„Bewässern" als gemeinsamer Einstieg nach dem Muster Art → Ventil → Details.** Der Tastatur-Button „🚿 Bewässern" fragt zuerst die Art (`🚿 Guss` / `🌫️ Sofort-Nebel`), dann das Ventil, dann die zweigspezifischen Details (Guss: Zeit-/Volumenlimit; Nebel: Stoß-Dauer/Pause/Laufzeit). Der Sofort-Nebel zieht damit aus der Zeitplan-Ansicht in „Bewässern" um; die Zeitplan-Ansicht zeigt nur noch Zeitpläne.

3. **Systemweite Einzel-Ventil-Konvention.** Die gesamte Telegram-UI — Zeitpläne wie manuelle Bewässerung — wählt **genau ein** Ventil aus einer **ungefilterten** Ventil-Liste (`get_all_valves()`, keine Guss/Nebel-Rolle im Schema). Bei genau einem gekoppelten Ventil entfällt die Auswahl (Auto-Selektion, vgl. ADR 0015). Die Mehrfach-Ventil-Zuweisung mit Ausführungsmodus (sequenziell/parallel) aus ADR 0015 bleibt eine im Datenmodell vorhandene, in der UI bewusst nicht exponierte Fähigkeit und ist den Zeitplänen vorbehalten (Amendment in ADR 0015).

4. **„Stopp" als querschnittlicher Notfall-Aus.** „🛑 Stopp" listet **alle aktiven Aktuierungen** — laufende Güsse, **extern/manuell geöffnete Ventile** *und* ein laufendes Nebel-Fenster — als einzeln stoppbare Einträge plus „Alle stoppen". Die Zähl-/Skip-Logik betrachtet alle Quellen: keine aktiv → Hinweis; genau eine → sofort stoppen; mehrere → Auswahl. Die begriffliche Trennung Kühlen ≠ Bewässern (ADR 0033) gilt im Normalfluss; der Notfall-Stopp steht bewusst darüber (Amendment in ADR 0033). Dass ein **extern geöffnetes** Ventil über Stopp geschlossen werden darf, ist ein bewusster nutzer-initiierter Eingriff (Amendment in ADR 0032 — die automatische Erkennung bleibt „nur melden").

5. **Emoji- und Ton-Konventionen unverändert (ADR 0029).** Die Hauptmenü-Buttons werden zu „🚿 Bewässern" / „🛑 Stopp" gekürzt; 🚿 bleibt der Bewässerungs-Oberbegriff (Guss und Nebel darunter), 🛑 der Stopp-Marker, 📅 für Gieß-Zeitpläne reserviert, ⏰ für Fotozeiten. Bestätigungen folgen weiter ADR 0013 (Reply-Keyboard).

## Konsequenzen

- Vorhersehbare, durchgängig deutsche Navigation; ein aufgeräumtes `/`-Menü.
- Alle Bewässerungs-Aktionen (Guss und Nebel, manuell wie stoppen) liegen an einem Ort; die Zeitplan-Ansicht bleibt auf Zeitpläne fokussiert.
- Einheitliche Ventil-Bedienung in der gesamten UI; ADR 0015 wird auf den real implementierten Einzel-Ventil-Stand eingenordet.
- „Stopp" wird zum verlässlichen Gesamt-Aus; erfordert schmale Lese-Schnittstellen zu Guss- und Nebel-Steuerung (`get_active_valve_names()`, `get_active_window()`) — reine Lese-Methoden in `core/`, architektur-konform (ADR 0008/0017).
- Das Redesign bleibt überwiegend ein UX-/Routing-Feature; die einzigen Verhaltensänderungen (Sofort-Nebel-Takt, Ventil-Auswahl, querschnittlicher Stopp, Nebel-Restart-Unterdrückung) sind in Feature 0031 und den Amendments zu 0015/0033 explizit umrissen.
