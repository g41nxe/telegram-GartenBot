# Feature: In-Chat-Einstellungen

## Problemstellung (Problem Statement)

Der Bot ist eine komfortable Fernbedienung für *Aktionen*, aber blind für seine eigene *Konfiguration*. Gärtnerisch relevante Schwellen — die Regenschwelle (`RAIN_THRESHOLD_MM`), der Batterie-Warnwert (`BATTERY_WARNING_THRESHOLD`), das Sicherheits-Timeout (`SAFETY_TIMEOUT_MINUTES`) — leben ausschließlich in der `.env`-Datei und lassen sich nur per SSH und Datei-Edit mit anschließendem Service-Neustart ändern. Wer im Sommer die Regenschwelle anpassen will, muss die Bedienoberfläche verlassen. Das System wirkt dadurch an dieser Stelle unfertig.

> Hinweis: Für einen technisch versierten Nutzer ist `.env` kein hartes Hindernis. Dieses Feature ist daher bewusst als Komfort-/Abrundungs-Feature eingeordnet, nicht als kritische Lücke — und auf wenige, wirklich relevante Schwellen begrenzt.

## Lösung (Solution)

Ein „⚙️ Einstellungen"-Bereich im Telegram-Bot, über den ausgewählte, gärtnerisch sinnvolle Schwellen direkt geändert werden können. Geänderte Werte werden persistent gespeichert und überschreiben zur Laufzeit die `.env`-Vorgabe; unveränderte Werte fallen weiterhin auf die `.env`/Defaults zurück. Damit wirken Änderungen sofort, ohne SSH und ohne Service-Neustart. Sicherheitskritische Grenzen behalten harte Ober-/Untergrenzen.

## User Stories

1. Als Benutzer möchte ich die Regenschwelle direkt im Bot ändern können, um die Überspringlogik saisonal anzupassen.
2. Als Benutzer möchte ich den aktuellen Wert einer Einstellung sehen, bevor ich ihn ändere.
3. Als Benutzer möchte ich, dass eine Änderung sofort wirkt, ohne den Dienst neu zu starten.
4. Als Benutzer möchte ich vor unsinnigen oder gefährlichen Werten geschützt werden (z. B. ein zu hohes Sicherheits-Timeout).
5. Als Benutzer möchte ich eine Einstellung auf den Standard zurücksetzen können.
6. Als Benutzer möchte ich, dass nur die wenigen wirklich relevanten Schwellen einstellbar sind, damit der Bereich übersichtlich bleibt.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Eingrenzung der einstellbaren Werte (Erstausbau):** `RAIN_THRESHOLD_MM`, `BATTERY_WARNING_THRESHOLD`, `SAFETY_TIMEOUT_MINUTES`. Bewusst klein gehalten; weitere Werte nur bei echtem Bedarf.
- **Konfigurations-Auflösung (Override-Kette):** Laufzeitwert = DB-Override (falls gesetzt) → sonst `.env` → sonst Code-Default. Die Persistenz nutzt die bestehende `system_metadata`-Tabelle (analog zu anderen persistenten Flags).
- **Architektonische Implikation (wichtig):** `config.py` lädt heute Konstanten beim Import. Für laufzeit-überschreibbare Werte braucht es eine kleine Zugriffsschicht (z. B. `config.get_setting(name)`), die DB-Override und Default zusammenführt, statt das Modul-Level-Konstanten-Muster beizubehalten. Betroffene Lesestellen (Scheduler-Skip, Watchdog, Sicherheits-Timeout-Versand) werden auf diese Zugriffsschicht umgestellt. Dies ist als bewusste Designentscheidung in der Planung zu bestätigen.
- **Wirksamkeit ohne Neustart:** Da die Werte bei jedem Lesezugriff aufgelöst werden, wirken Änderungen sofort. Ausnahme `SAFETY_TIMEOUT_MINUTES`: Der Hardware-Fail-Safe wird beim Verbindungsaufbau ans Ventil gesendet — eine Änderung erfordert ein erneutes Senden (beim nächsten Connect oder via expliziter Re-Konfiguration); dies wird dem Benutzer transparent gemacht.
- **Validierung & Grenzen:** Jede Einstellung hat einen erlaubten Bereich (z. B. Sicherheits-Timeout fest gedeckelt). Ungültige Eingaben werden sachlich abgewiesen (ADR 0029).
- **Bedienung:** „⚙️ Einstellungen" zeigt die Werte mit aktuellem Stand; Auswahl führt zu Eingabe/Buttons; Bestätigung zeigt alten → neuen Wert. „Auf Standard zurücksetzen" entfernt den DB-Override.
- **Design-System-Konform:** Anrede „du", neutrales Register, Einheiten-/Zahlenformat nach ADR 0029.

## Test-Entscheidungen (Testing Decisions)

- **Test-Nahtstelle (Seam):** Die Konfigurations-Zugriffsschicht (`config.get_setting`) als Unit-Test (Override-Kette: DB → .env → Default), plus `tests/ui/test_telegram_ui.py` für den Einstellungs-Dialog.
- **Was geprüft wird:** Ein gesetzter DB-Override gewinnt über `.env`; nach „Zurücksetzen" greift wieder der Default; ungültige Werte werden abgewiesen; eine geänderte Regenschwelle wirkt sich auf die Skip-Bewertung aus (Integrationstest gegen die bestehende Skip-Logik).
- **Sicherheitsgrenzen:** Test, dass das Sicherheits-Timeout nicht über die harte Obergrenze gesetzt werden kann.
- **Referenz-Pflege:** Neue Einstellungs-Nachrichten in IST- und SOLL-Referenz nachziehen.
- **Coverage** darf nicht regredieren.

## Nicht im Leistungsumfang (Out of Scope)

- **Alle** `.env`-Werte editierbar machen (Tokens, IDs, Koordinaten, MQTT-Topics) — bewusst nicht; nur gärtnerische Schwellen.
- **Mehrbenutzer-spezifische Einstellungen** — Einstellungen gelten systemweit.
- **Import/Export** der Konfiguration über den Bot.

## Weitere Anmerkungen (Further Notes)

- Priorität bewusst niedriger als 0018–0021: Komfort-/Abrundungs-Feature, das v. a. für nicht-technische Nutzer Wert schafft.
- Die Konfigurations-Zugriffsschicht ist die eigentliche Substanz dieses Features; der Bot-Dialog ist nur die Oberfläche darauf. Diese Umstellung sollte in der Planung architektonisch sauber entworfen werden (ADR-würdig, falls sie das Konstanten-Muster in `config.py` grundsätzlich ablöst).
- Offene Detailfrage: Soll `SAFETY_TIMEOUT_MINUTES` überhaupt in-chat editierbar sein (sicherheitsrelevant) oder bewusst nur in `.env` bleiben?
