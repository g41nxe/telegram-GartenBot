# Feature: Regen-Übersteuerung mit Guss-Vorwarnung

## Problemstellung (Problem Statement)

Der Scheduler bewertet jeden geplanten Guss über die Gieß-Empfehlung und überspringt oder reduziert ihn bei ausreichendem Regen — **automatisch und kommentarlos**. Der Benutzer erfährt davon erst über die nachgelagerte Meldung, **nachdem** die Entscheidung gefallen ist. Will der Benutzer einen Guss bewusst durchsetzen (z. B. weil die Vorhersage unsicher ist, der Boden lokal trotzdem trocken ist oder frisch gepflanzt wurde), bleibt ihm nur, die Regen-Automatik ganz abzuschalten — ein grober Hebel mit der Gefahr, ihn zu vergessen. Es fehlt ein gezielter, einmaliger Eingriff im richtigen Moment: **bevor** der Guss übersprungen wird.

## Lösung (Solution)

Etwa fünf Minuten vor dem geplanten Start eines Gusses prüft der Daemon die Gieß-Empfehlung vorab. **Nur** wenn der Guss dadurch übersprungen **oder** reduziert würde, sendet der Bot eine **Guss-Vorwarnung**: eine kurze Nachricht mit den Details des anstehenden Gusses (Zeitplan, Ventil, vorgesehene Dauer/Menge, Regen-Begründung) und einem Button **„🚿 Regen ignorieren"**. Drückt der Benutzer ihn innerhalb des Fensters, wird die automatische Regen-Entscheidung für **genau diesen Lauf** aufgehoben (**Regen-Übersteuerung**): Der Guss läuft zu seiner regulären Zeit mit den **Original-Werten**, als gäbe es keinen Regen. Reagiert der Benutzer nicht, bleibt das automatische Verhalten (Skip/Reduzierung) bestehen — der Normalfall ändert sich nicht. Die Übersteuerung gilt nur einmalig; der nächste Lauf wird wieder frisch bewertet.

## User Stories

1. Als Benutzer möchte ich kurz **vor** einem geplanten Guss gewarnt werden, wenn dieser wegen Regen übersprungen würde, damit ich rechtzeitig eingreifen kann, statt es erst hinterher zu erfahren.
2. Als Benutzer möchte ich denselben Hinweis auch erhalten, wenn der Guss wegen Regen **reduziert** würde, damit ich auch eine Teil-Reduzierung aufheben kann.
3. Als Benutzer möchte ich aus der Guss-Vorwarnung heraus mit **einem Tipp** den vollen Guss erzwingen, ohne die Regen-Automatik dauerhaft abzuschalten.
4. Als Benutzer möchte ich, dass die Übersteuerung den **vollständigen ursprünglich geplanten Guss** ausführt (Original-Dauer, -Menge und das richtige Ventil), nicht irgendeinen Standard-Guss.
5. Als Benutzer möchte ich, dass die Übersteuerung **nur diesen einen Lauf** betrifft und am nächsten Tag wieder regulär bewertet wird, damit ich nicht versehentlich die Regen-Logik dauerhaft deaktiviere.
6. Als Benutzer möchte ich in der Vorwarnung die **konkreten Details** sehen (Zeitplanname, Startzeit, Ventil, vorgesehene Dauer/Menge sowie die Regen-Begründung mit mm-Werten), um informiert zu entscheiden.
7. Als Benutzer möchte ich **keine** Vorwarnung erhalten, wenn der Guss ohnehin voll läuft (kein nennenswerter Regen), damit ich nicht mit unnötigen Nachrichten überflutet werde.
8. Als Benutzer möchte ich, dass ein **zu spät** gedrückter Button (Guss bereits übersprungen oder gelaufen) keinen verspäteten Guss auslöst, sondern mir nur sachlich mitteilt, dass der Eingriff zu spät kam.
9. Als Benutzer möchte ich, dass die Übersteuerung einen **Daemon-Neustart** im Vorwarn-Fenster übersteht, damit mein Eingriff nicht durch einen Neustart verloren geht.
10. Als Benutzer mit mehreren Zeitplänen möchte ich, dass jede betroffene Bewässerung ihre **eigene** Vorwarnung mit eigenem Übersteuerungs-Button bekommt, damit ich gezielt pro Zeitplan entscheiden kann.
11. Als Benutzer möchte ich, dass die Vorlaufzeit der Vorwarnung **konfigurierbar** ist, falls mir fünf Minuten zu kurz oder zu lang sind.
12. Als Benutzer möchte ich, dass ein übersteuerter Guss in der späteren „Wasser marsch!"-Meldung und im Tagesbericht als **regulär gelaufener** Guss erscheint (nicht als übersprungen/reduziert).

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Vorgelagerte Prüfung im Scheduler.** Die Scheduler-Schleife (1-Minuten-Poll) erhält eine zweite Prüfung: Trifft `now` auf `Startzeit − RAIN_WARNING_LEAD_MINUTES` (neuer Config-Wert, Standard 5) eines aktiven Zeitplans, läuft die **bestehende** Gieß-Empfehlung (keine neue Entscheidungslogik). Ergibt sie Skip **oder** Reduzierung (Faktor < 1), wird die Vorwarnung ausgelöst; ergibt sie vollen Guss, passiert nichts.
- **Neues Domänen-Event `WateringRainWarning`.** Trägt die Identität und die Original-Werte des anstehenden Gusses: Zeitplan-ID, Name, Startzeit, Ventil(e), Original-Dauer, Original-Menge sowie die Begründungs-Reasons der Gieß-Empfehlung. Lebt bei den übrigen Scheduler-Events.
- **`WateringSkipped` wird um `schedule_id` erweitert.** Ohne sie lässt sich der übersprungene Lauf nicht eindeutig identifizieren. `WateringScaled` trägt die Original-Werte bereits; für eine eindeutige Zuordnung erhält auch es die `schedule_id`.
- **Event-getriebene Benachrichtigung.** Die Telegram-UI abonniert `WateringRainWarning` (wie die bestehenden `WateringSkipped`/`WateringScaled`-Handler) und sendet die Guss-Vorwarnung als Broadcast mit Inline-Keyboard. Der Scheduler ruft die UI **nicht** direkt auf.
- **Übersteuerung als persistentes Flag.** Der Button-Callback setzt ein Flag in den System-Metadaten, eindeutig je Zeitplan und Kalendertag (z. B. Schlüssel `rain_override:<schedule_id>:<datum>`). Damit übersteht der Eingriff einen Daemon-Neustart im 5-Minuten-Fenster. Bewusst **kein** In-Memory-Zustand (Muster wie die Watchdog-Flags).
- **Ausführung umgeht die Bewertung.** Beim regulären Auslösen eines Zeitplans liest der Scheduler **vor** dem Wetter-Check das Übersteuerungs-Flag. Gesetzt → der Guss läuft mit den Original-Werten (Dauer, Menge, Ventil(e), Ausführungsmodus sequenziell/parallel), die Gieß-Empfehlung wird komplett übergangen; das Flag wird anschließend **verbraucht** (gelöscht). Nicht gesetzt → unveränderter Ablauf inkl. Skip/Reduzierung.
- **T−5 ist nur informativ.** Maßgeblich für die tatsächliche Ausführung bleibt die Bewertung zur Zeit T — außer das Flag ist gesetzt. Ändert sich das Wetter in den fünf Minuten, entsteht so keine veraltete Entscheidung. Konsequenz: Die Bewertung läuft für einen betroffenen Zeitplan zweimal (rein lesend, günstig).
- **Idempotenz & Veralterung.** Der Button wird quittiert (`answer_callback_query`). Ein erneuter Tipp oder ein Tipp **nach** dem Lauf (Flag bereits verbraucht bzw. Lauf vorbei) löst keinen weiteren Guss aus, sondern liefert eine sachliche Rückmeldung.
- **Begründungstext nach ADR 0029.** Knapp, sachlich-klar, mit konkreten mm-Werten und Schwelle; „du"-Anrede; Emoji-Semantik konsistent (🚿 für Guss, 🌧 für Regen).
- **Architektur-konform (ADR 0008/0017).** Entscheidung in `core` bzw. im Scheduler; UI abonniert Events und stellt die Rückfrage; die Kopplung UI↔Scheduler erfolgt **nicht** als Direktaufruf, sondern über das gemeinsam genutzte System-Metadaten-Flag (geschrieben von der UI, gelesen vom Scheduler). Bestätigungs-/Aktions-Keyboard analog ADR 0013.
- **Grundlage in ADR 0035** festgehalten; Baustein für die in Feature 0018 skizzierte „Trotzdem gießen"-Geste (gemeinsame Callback-Logik).

## Test-Entscheidungen (Testing Decisions)

- **Guter Test = externes Verhalten.** Geprüft wird, *ob* bei drohendem Skip/Reduzierung eine Vorwarnung entsteht, *ob* der Button das Flag setzt und *ob* ein gesetztes Flag den vollen Original-Guss auslöst — nicht die internen Zwischenschritte.
- **Nahtstelle 1 — Gieß-Empfehlung (bestehend).** Die zugrunde liegende Bewertung (Skip/Reduzierung/voll) ist bereits in `tests/core/test_watering_advice.py` abgedeckt und wird **nicht** dupliziert.
- **Nahtstelle 2 — Scheduler-Funktionen (bestehend).** Analog zu `TestNebelScheduling` (direkter Aufruf von Scheduler-Funktionen mit gestelltem `now`): (a) die neue Vorab-Prüfung publiziert `WateringRainWarning` genau dann, wenn `now == Start − Lead` **und** die Bewertung Skip/Reduzierung ergibt — sonst nicht; (b) das reguläre Auslösen mit gesetztem Übersteuerungs-Flag startet den vollen Original-Guss und ruft die Gieß-Empfehlung **nicht** auf; ohne Flag bleibt der Skip/Reduzierungs-Pfad unverändert; das Flag ist danach verbraucht.
- **Nahtstelle 3 — Telegram-UI (bestehend).** In `tests/ui/test_telegram_ui.py` (gemockter `telegram_client`): der `WateringRainWarning`-Handler sendet die Vorwarnung mit dem Übersteuerungs-Button und den konkreten Details/mm-Werten; der Button-Callback setzt das Metadaten-Flag; ein „zu spät"-Tipp (kein anstehender Lauf / Flag bereits verbraucht) sendet nur die sachliche Rückmeldung, ohne einen Guss zu starten.
- **Persistenz.** Test, dass das gesetzte Flag aus den System-Metadaten gelesen wird (überlebt damit einen Neustart) und nach der Ausführung entfernt ist.
- **Coverage** darf nicht regredieren.

## Nicht im Leistungsumfang (Out of Scope)

- **Kontextsensible Hinweise beim *manuellen* Guss** — das ist Feature 0020 (Rückfrage vor dem Sofort-Guss), ein eigener Aufrufkontext.
- **Vollständige Umsetzung von Feature 0018** (alle aktionsfähigen Benachrichtigungen) — dieses Feature liefert nur den konkreten Vorwarn-/Übersteuerungs-Baustein.
- **Dauerhaftes Abschalten der Regen-Logik** eines Zeitplans (persistenter Schalter) — bewusst nicht; die Übersteuerung ist immer einmalig.
- **Verspätetes Nachholen** eines bereits übersprungenen Gusses nach Ablauf des Fensters.
- **Übersteuerung der Nebel-Steuerung** — Nebel-Fenster kennen keine Regen-Überspringlogik (CONTEXT.md), daher nicht betroffen.
- **Neue Entscheidungslogik** — es wird ausschließlich die bestehende Gieß-Empfehlung wiederverwendet.

## Weitere Anmerkungen (Further Notes)

- **Terminologie** (CONTEXT.md): **Guss-Vorwarnung** = die Benachrichtigung ~5 Min vorher; **Regen-Übersteuerung** = der einmalige Eingriff, der den Regen-Skip/-Reduzierung für diesen Lauf aufhebt. Beide bewusst ohne Anglizismus.
- **Doppelte Bewertung** (T−5 und T) ist akzeptiert: rein lesend, günstig, und vermeidet veraltete Entscheidungen, falls sich das Wetter im Fenster ändert.
- **Vorlaufzeit** `RAIN_WARNING_LEAD_MINUTES` (Standard 5) liegt in `config/garden.conf` (generischer, nicht-geheimer Wert, ADR 0030).
- **Synergie:** Der hier entstehende „🚿 Regen ignorieren"-Callback und das Vorwarn-Muster sind die konkrete Vorarbeit für Feature 0018.
- **Telegram-Nachrichten:** Die neue Guss-Vorwarnung (und ihre „zu spät"-Variante) sind in `docs/design/telegram-nachrichten.html` zu ergänzen (Regel `telegram_messages.md`).
