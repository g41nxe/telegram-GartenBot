# Feature: Kontextsensible Gieß-Hinweise

## Problemstellung (Problem Statement)

Der Bot ist proaktiv bei Ereignissen, aber blind für den Kontext einer manuell ausgelösten Aktion. Startet der Benutzer abends einen manuellen Guss, obwohl in der Nacht kräftiger Regen vorhergesagt ist oder bereits genug gefallen ist, sagt der Bot nichts — er führt die Aktion kommentarlos aus. Genau die Intelligenz, die der Scheduler über die automatische Überspringlogik bereits besitzt (Regen-Fenster, Gieß-Empfehlung), wird bei der manuellen Bedienung nicht genutzt. Der Benutzer verschenkt dadurch Wasser oder übergießt, ohne einen Hinweis zu bekommen.

## Lösung (Solution)

Wenn der Benutzer einen manuellen Guss starten will und der Kontext klar dagegenspricht, blendet der Bot vor dem Öffnen des Ventils einen kurzen, sachlichen Hinweis mit Rückfrage ein — z. B. „Heute Nacht sind 8 mm Regen erwartet. Trotzdem gießen?" — mit den Optionen „🚿 Trotzdem gießen" und „❌ Abbrechen". Spricht der Kontext nicht dagegen, startet der Guss wie bisher ohne Zwischenfrage (keine Reibung im Normalfall). Die Bewertung nutzt die bereits vorhandene, getestete Logik (Regen-Fenster / Gieß-Empfehlung) und wird nicht neu erfunden.

## User Stories

1. Als Benutzer möchte ich vor einem manuellen Guss gewarnt werden, wenn in den nächsten Stunden ausreichend Regen erwartet wird, um unnötiges Gießen zu vermeiden.
2. Als Benutzer möchte ich gewarnt werden, wenn in den letzten 24 h bereits genug Regen gefallen ist, bevor ich manuell gieße.
3. Als Benutzer möchte ich den Hinweis mit einem Tipp übergehen können („Trotzdem gießen"), wenn ich die Bewässerung bewusst will.
4. Als Benutzer möchte ich, dass im unkritischen Fall kein zusätzlicher Bestätigungsschritt erscheint, damit der normale Guss schnell bleibt.
5. Als Benutzer möchte ich, dass der Hinweis konkret begründet ist (erwartete/gefallene mm), damit ich eine informierte Entscheidung treffe.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Wiederverwendung der Kernlogik:** Die Bewertung stützt sich auf die bestehende Regen-Fenster-/Gieß-Empfehlungs-Logik in `core/` (reine Funktion, ADR 0021) bzw. `weather.should_skip_watering()`. Keine neue Entscheidungslogik, nur ein neuer Aufrufkontext.
- **Eingriffspunkt:** Im manuellen Guss-Flow der Telegram-UI, unmittelbar vor `WateringController.start_watering()`. Liefert die Bewertung „würde übersprungen / nicht empfohlen", wird statt des Sofortstarts eine Bestätigungs-Nachricht mit Inline-Keyboard gesendet.
- **Bestätigungs-Keyboard:** „🚿 Trotzdem gießen" (führt den Start mit den zuvor gewählten Werten aus) und „❌ Abbrechen". Konsistent mit den bestehenden Bestätigungs-Tastaturen (ADR 0013).
- **Begründungstext:** Knapp und sachlich-klar nach ADR 0029, mit konkreten Zahlen (z. B. erwartete mm der nächsten 24 h, gefallene mm der letzten 24 h, Schwelle).
- **Architektur:** Die Entscheidung bleibt in `core`; die UI ruft sie auf und stellt die Rückfrage dar. Kein Adapter ruft einen anderen direkt; falls nötig wird die minimale Callable/Datenstruktur injiziert (ADR 0017).
- **Abgrenzung zur Skip-Logik:** Der Scheduler überspringt automatisch (ohne Rückfrage). Der manuelle Pfad überspringt nicht automatisch, sondern fragt nach — der Benutzer behält die Kontrolle.
- **Synergie mit Feature 0018:** Die „🚿 Trotzdem gießen"-Aktion ist dieselbe Geste wie der dort vorgeschlagene Button am Regen-Skip; beide Features teilen die Callback-Logik.

## Test-Entscheidungen (Testing Decisions)

- **Test-Nahtstelle (Seam):** Der Ereignis-Kanal / die UI-Handler in `tests/ui/test_telegram_ui.py`; die zugrunde liegende Bewertung ist bereits in `tests/core/test_watering_advice.py` abgedeckt.
- **Was geprüft wird:** Bei „Kontext spricht dagegen" wird die Rückfrage gesendet (kein sofortiger Ventil-Befehl); bei „Kontext unkritisch" startet der Guss direkt ohne Zwischenfrage. „Trotzdem gießen" löst den Start mit den korrekten Werten aus; „Abbrechen" tut nichts.
- **Begründung im Text:** Test, dass die konkreten mm-Werte/Schwellen in der Rückfrage erscheinen.
- **Keine Doppelbewertung:** Die Kernlogik wird nicht dupliziert — Tests prüfen, dass die bestehende Funktion aufgerufen wird.
- **Coverage** darf nicht regredieren.

## Nicht im Leistungsumfang (Out of Scope)

- **Kontextprüfung für geplante (automatische) Güsse** — die laufen bereits über die bestehende Überspringlogik.
- **Proaktive Hinweise ohne Nutzeraktion** (z. B. „heute Abend besser nicht gießen") — eigenständige Idee, nicht Teil dieses Features.
- **Temperatur-/Hitzestrecken-basierte Mengenempfehlung** — separates Thema.

## Weitere Anmerkungen (Further Notes)

- Offene Detailfrage für die Planung: Welche Bedingung genau die Rückfrage auslöst — dieselbe Schwelle wie der Scheduler-Skip (`RAIN_THRESHOLD_MM`) oder eine eigene, evtl. striktere Schwelle für den manuellen Fall.
- Offene Detailfrage: ob auch die Tagestemperatur/Hitzestrecke in die Rückfrage einfließt oder zunächst nur das Regen-Fenster.
- Dieses Feature macht die vorhandene Intelligenz des Systems an der Stelle sichtbar, an der der Mensch eingreift — hoher wahrgenommener Nutzen bei geringer neuer Logik.
