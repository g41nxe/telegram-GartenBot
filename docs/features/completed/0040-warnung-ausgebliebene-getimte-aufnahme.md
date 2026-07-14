# Feature: Warnung bei Aufnahme-Verzug (inkl. ausgebliebener Aufnahme)

> **Überarbeitet nach der Fehleranalyse vom 14.07.2026.** Die ursprüngliche Fassung baute auf
> dem ±5-Minuten-Zustellfenster auf („Fenster geschlossen, kein Bild → Warnung"). Dieses Fenster
> entfällt mit ADR 0040 — ein Aufnahme-Zeitpunkt wird künftig vom ersten Bild *nach* ihm erfüllt.
> Damit ändert sich der Auslöser: Gewarnt wird nicht mehr bei „kein Bild im Fenster", sondern bei
> **zu großem Aufnahme-Verzug** — und das Ausbleiben ist dessen Grenzfall. Siehe ADR 0041.

## Problemstellung (Problem Statement)

Zwei Störungen der Garten-Kamera bleiben heute unsichtbar:

1. **Ausbleibende Aufnahme.** Wacht die Garten-Kamera zum Aufnahme-Zeitpunkt nicht auf, kommt sie
   nicht ins WLAN oder wird ihr Upload abgewiesen, kommt schlicht kein Bild — und niemand meldet
   das. Die Kamera-Überwachung schlägt erst nach `max(3 · Sende-Intervall, 3600 s)` an, bei einem
   4-Stunden-Intervall also erst nach zwölf Stunden.

2. **Verspätete Aufnahme.** Mit ADR 0040 wird auch ein 30 Minuten zu spätes Bild zugestellt — der
   Benutzer bekommt sein Foto. Genau dadurch verschwindet aber das bisher einzige Störungssignal:
   Dass die Fotos ausblieben, hat den Fehler vom Juli 2026 überhaupt erst sichtbar gemacht. Ohne
   Ersatz würde eine kranke Kamera künftig unbemerkt Zyklus um Zyklus verheizen, bis der Akku leer
   ist.

Der bestehende Watchdog kann beides nicht sehen: Er prüft `cameras.last_seen` — und der war
während der gesamten Störung durchgehend frisch. Die Kamera war ja lebendig. Sie war nur
unpünktlich.

## Lösung (Solution)

Die **Kamera-Überwachung** bekommt eine zweite Alarmklasse: den **Aufnahme-Verzug**.

- Überschreitet der Verzug die **Verzugs-Schwelle** (Default 15 min) **zweimal in Folge**, meldet
  der Telegram-Bot eine Störung.
- Ein Aufnahme-Zeitpunkt, der bis zu seiner Ablösung **gar kein** Bild erhalten hat, gilt als
  maximal verzögert und löst dieselbe Warnung aus — damit ist die ausgebliebene Aufnahme
  vollständig abgedeckt.
- **Entwarnung**, sobald ein Aufnahme-Zeitpunkt wieder innerhalb der Schwelle erfüllt wird.
- Der **Tagesbericht** weist den durchschnittlichen Aufnahme-Verzug des Tages aus. Er ist der
  Frühindikator: Er steigt, lange bevor Bilder ganz ausbleiben.

Siehe ADR 0041.

## User Stories

1. Als Benutzer möchte ich gewarnt werden, wenn ein erwartetes **Guss-Foto** oder das Foto zu
   einer **Festen Fotozeit** ausbleibt.
2. Als Benutzer möchte ich **auch dann** gewarnt werden, wenn die Fotos zwar kommen, aber
   regelmäßig **weit nach** ihrem Aufnahme-Zeitpunkt — das ist die Vorstufe des Ausfalls.
3. Als Benutzer möchte ich in der Warnung sehen, **welcher** Aufnahme-Zeitpunkt betroffen ist,
   **wie groß** der Verzug war und **wann die Garten-Kamera zuletzt gesehen** wurde, um
   einzuschätzen, ob sie schläft, offline ist oder ihr Akku schwächelt.
4. Als Benutzer möchte ich **keine Meldung wegen eines einzelnen Wacklers** — erst der zweite
   Verzug in Folge meldet.
5. Als Benutzer möchte ich **genau eine** Warnung je Störung, kein Nachhaken — und eine
   **Entwarnung**, wenn die Kamera ihre Zeitpunkte wieder trifft.
6. Als Benutzer möchte ich bei einem **längeren Ausfall keine Doppel-Meldungen**: Hat die
   Kamera-Überwachung die Garten-Kamera bereits als **inaktiv** gemeldet, schweigt die
   Verzugs-Warnung — die Inaktivität ist die umfassendere Aussage.
7. Als Benutzer möchte ich auch dann gewarnt werden, wenn der zugehörige Guss **regenbedingt
   übersprungen** wurde — ein fehlendes Foto signalisiert ein Kamera-/Netzwerk-Problem unabhängig
   davon, ob gegossen wurde.
8. Als Betreiber möchte ich nach einem **Daemon-Neustart keine Alarm-Flut** für längst vergangene
   Aufnahme-Zeitpunkte des Tages.
9. Als Betreiber möchte ich die **Verzugs-Schwelle konfigurieren** können.

> **Bewusste Abweichung von der ursprünglichen Fassung:** Dort war „keine Entwarnung" gefordert
> (Story 7 alt) — die ausgebliebene Aufnahme sei die Information. Mit der Alarmklasse ist das
> nicht mehr haltbar: Ein Alarm ist ein **Zustand**, und ein Zustand ohne Ende bleibt für immer
> im Tagesbericht stehen. Die Entwarnung folgt jetzt dem Muster der drei bestehenden Geräte
> (ADR 0018).

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Rein serverseitig**, kein Firmware-Eingriff. Setzt Feature 0042 (Zustellung nach
  Aufnahme-Verzug) voraus, weil erst dort der Verzug überhaupt ermittelt wird.

- **Tatsache und Bewertung getrennt (ADR 0018).** Der `camera_receiver` **ermittelt** den Verzug
  beim Upload (er braucht ihn ohnehin für die Bildunterschrift) und schreibt ihn in die
  `cameras`-Zeile — dort, wo er auch `last_seen` und `battery` fortschreibt. `adapters/watchdog.py`
  **bewertet** ihn. Keine Alarm-Logik im Transport-Adapter.

- **Zwei Zustände in `system_metadata`**, analog zu den bestehenden Watchdog-Flags:
  `watchdog_delay_alert_active_camera_<mac>` und ein Zähler der aufeinanderfolgenden Verzüge.

- **Nicht erfüllter Aufnahme-Zeitpunkt = maximaler Verzug.** Wird ein Aufnahme-Zeitpunkt von
  seinem Nachfolger abgelöst, ohne ein Bild erhalten zu haben, zählt das wie ein Verzug über der
  Schwelle. Erkannt wird das im stündlichen Watchdog-Lauf aus dem zuletzt zugestellten
  Aufnahme-Zeitpunkt (Feature 0042) gegen die Liste der fälligen Zeitpunkte.

- **Vorrang der Inaktivität.** Ist das Inaktivitäts-Flag der Kamera gesetzt, wird keine
  Verzugs-Warnung gesendet (Story 6).

- **Neue Ereignisse** in `core/camera_events.py`: `CameraDelayAlertTriggered`,
  `CameraDelayAlertResolved`. `telegram_ui` abonniert sie wie die bestehenden Alarme.

- **Konfiguration:** `AUFNAHME_VERZUG_SCHWELLE_MINUTEN` (Default 15) in `config/garden.conf`.

- **`docs/design/telegram-nachrichten.html`** wird um Warnung und Entwarnung ergänzt.

## Test-Entscheidungen (Testing Decisions)

- `tests/adapters/test_watchdog.py`:
  - Ein Verzug über der Schwelle → **keine** Warnung (Karenz).
  - Zwei Verzüge in Folge → genau **eine** Warnung.
  - Danach ein pünktlicher Treffer → **Entwarnung**, Zähler zurückgesetzt.
  - Aufnahme-Zeitpunkt abgelöst ohne Bild → zählt als Verzug über der Schwelle.
  - Inaktivitäts-Flag aktiv → Verzugs-Warnung schweigt.
  - Daemon-Neustart mit vergangenen Zeitpunkten → keine Alarm-Flut.
- `tests/ui/`: Wortlaut von Warnung und Entwarnung.

## Nicht im Leistungsumfang (Out of Scope)

- Die **Behebung** der Verzugs-Ursache in der Kamera — Feature 0005 im Kamera-Repository.
- Ein eigener Mechanismus für „ausgebliebene Aufnahme" — er geht in dieser Alarmklasse auf.

## Weitere Anmerkungen (Further Notes)

Der Aufnahme-Verzug ist die einzige Größe, an der die Steuerzentrale die Gesundheit der
Garten-Kamera ablesen kann: Gescheiterte Zyklen erreichen sie nie, sie sieht nur, *wann* ein Bild
ankommt. Genau daraus musste die Störung im Juli 2026 rekonstruiert werden. Diese Rekonstruktion
soll künftig das System leisten, nicht der Mensch.
