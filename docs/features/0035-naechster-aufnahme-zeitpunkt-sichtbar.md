# Feature: Nächsten Aufnahme-Zeitpunkt sichtbar machen

Referenz: ADR 0036 · CONTEXT.md (Aufnahme-Zeitpunkt, Guss-Foto, feste Fotozeit)

## Problemstellung (Problem Statement)

Die Garten-Kamera wird gezielt zu **Aufnahme-Zeitpunkten** geweckt — nach jedem Guss und zu
festen Uhrzeiten — und nur diese Fotos landen im Telegram-Bot (reguläre Intervall-Bilder nicht).
Dieses Modell ist für den Nutzer aber unsichtbar:

- Der `/status` zeigt den nächsten Guss, verrät aber nicht, **wann das nächste Foto** kommt.
- Die Fotozeiten-Ansicht listet nur die **festen** Fotozeiten — die guss-basierten Aufnahmen
  (Guss-Fotos) fehlen, obwohl sie genauso Fotos erzeugen. Der Nutzer hat keinen vollständigen
  Überblick, wann am Tag Fotos entstehen.
- Bekommt der Nutzer ein Guss-Foto, lautet die Bildunterschrift „Nach dem Guss um 06:00" — das
  ist die **Guss-Startzeit** (das Bild entsteht erst Dauer + Offset später) und nennt bei
  mehreren Zeitplänen **keinen Namen**. Er weiß nicht, zu welchem Guss das Bild gehört.

## Lösung (Solution)

Die vorhandene Aufnahme-Zeitpunkt-Logik wird sichtbar gemacht — ohne neue Entscheidungslogik:

- Im `/status` erscheint **direkt unter „Nächster Guss"** eine Zeile mit dem **nächsten
  Aufnahme-Zeitpunkt** (tatsächliche Aufnahmezeit + Anlass).
- Die Fotozeiten-Ansicht zeigt zwei Abschnitte: die **festen Fotozeiten** (wie bisher löschbar)
  und read-only die **Guss-Fotos** der aktiven Zeitpläne (berechnete Aufnahmezeit + Name).
- Die Bildunterschrift eines Guss-Fotos nennt künftig den **Zeitplan-Namen** statt der
  irreführenden Startzeit.

Im unkritischen Fall (keine Kamera, keine Aufnahme-Zeitpunkte) bleibt alles wie bisher — die
neuen Anzeigen erscheinen nur, wenn sie Inhalt haben.

## User Stories

1. Als Bot-Nutzer möchte ich im `/status` sehen, wann das nächste Foto aufgenommen wird, um zu
   wissen, wann ich das nächste Bild aus dem Garten erwarten kann.
2. Als Bot-Nutzer möchte ich, dass der nächste Aufnahme-Zeitpunkt die **tatsächliche**
   Aufnahmezeit zeigt (Guss-Start + Dauer + Nach-Offset), nicht die Guss-Startzeit, damit die
   Angabe stimmt.
3. Als Bot-Nutzer möchte ich beim nächsten Aufnahme-Zeitpunkt den **Anlass** sehen (nach welchem
   Guss bzw. ob es eine feste Fotozeit ist), um die Aufnahme einordnen zu können.
4. Als Bot-Nutzer möchte ich die „Nächstes Foto"-Zeile im Stil der „Nächster Guss"-Zeile
   (heute/morgen + Uhrzeit), damit der Status konsistent lesbar bleibt.
5. Als Bot-Nutzer möchte ich, dass die „Nächstes Foto"-Zeile entfällt, wenn keine Kamera
   registriert ist oder keine Aufnahme-Zeitpunkte existieren, damit der Status nicht mit leeren
   Angaben überladen wird.
6. Als Bot-Nutzer möchte ich die Zeile auch dann sehen, wenn meine Kamera gerade offline ist,
   weil es der **Plan** ist und der Online-Zustand bereits im Kamera-Block steht.
7. Als Bot-Nutzer möchte ich in der Fotozeiten-Ansicht neben den festen Zeiten auch die
   **Guss-Fotos** sehen, um einen vollständigen Überblick über alle Aufnahme-Zeitpunkte zu haben.
8. Als Bot-Nutzer möchte ich die Guss-Fotos in der Fotozeiten-Ansicht mit ihrer **berechneten
   Aufnahmezeit** und dem **Zeitplan-Namen** sehen, um sie eindeutig zuzuordnen.
9. Als Bot-Nutzer möchte ich, dass Guss-Fotos in der Fotozeiten-Ansicht **read-only** sind (kein
   Löschen-Button), weil sie an den Zeitplan gebunden sind — ändern heißt, den Zeitplan ändern.
10. Als Bot-Nutzer möchte ich, dass nur **aktive** Zeitpläne Guss-Fotos erzeugen und gelistet
    werden, da inaktive Zeitpläne keine Aufnahme auslösen.
11. Als Bot-Nutzer möchte ich, dass leere Abschnitte der Fotozeiten-Ansicht weggelassen werden
    und nur, wenn beide leer sind, die bisherige Leer-Meldung erscheint, damit die Ansicht
    aufgeräumt bleibt.
12. Als Bot-Nutzer möchte ich den „➕ Uhrzeit hinzufügen"-Button immer sehen, um jederzeit eine
    feste Fotozeit anlegen zu können.
13. Als Bot-Nutzer möchte ich, dass die Bildunterschrift eines Guss-Fotos den Zeitplan-Namen
    nennt („Nach dem Guss „Rasen""), damit ich bei mehreren Zeitplänen weiß, zu welchem Guss das
    Bild gehört.
14. Als Bot-Nutzer möchte ich, dass die Bildunterschrift einer festen Fotozeit unverändert die
    Uhrzeit nennt („Foto um 18:00"), weil dort kein Name existiert.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Wiederverwendung des Aufnahme-Zeitpunkt-Modells.** Es wird keine neue Planungslogik gebaut.
  Die bestehenden reinen Core-Funktionen für Aufnahme-Zeitpunkte werden um **strukturierte
  Label-Informationen** erweitert (Typ: Guss-Foto / feste Fotozeit, sowie der Zeitplan-Name beim
  Guss-Foto), damit alle drei Anzeige-Stellen konsistent formatieren können.
- **Neue reine Funktion `next_photo_target`** im Kamera-Schedule-Core: liefert aus `now`, den
  Zeitplänen, den festen Fotozeiten und dem Nach-Offset den **nächsten** Aufnahme-Zeitpunkt
  (Zeitpunkt + strukturiertes Label) oder nichts. Schwester zur bestehenden Schlafdauer-Berechnung
  und nutzt dieselben Ziel-Quellen.
- **`/status`-Zeile** wird in der bestehenden Status-Erzeugung gerendert, **direkt unter der
  „Nächster Guss"-Zeile**. Quelle: registrierte Kameras, aktive Zeitpläne und feste Fotozeiten aus
  der Datenbank. Format im Stil der bestehenden Zeile (heute/morgen + Uhrzeit + Anlass). Entfällt
  ohne registrierte Kamera oder ohne Aufnahme-Zeitpunkte; eine offline-Kamera unterdrückt sie nicht.
- **Fotozeiten-Ansicht** wird zweigeteilt: Abschnitt „Feste Zeiten" (löschbare feste Fotozeiten,
  unverändert) und Abschnitt „Nach Güssen" (read-only Guss-Fotos der **aktiven** Zeitpläne, mit
  berechneter Aufnahmezeit und Zeitplan-Name). Leere Abschnitte werden ausgelassen; sind beide
  leer, erscheint die bisherige Leer-Meldung. Der Hinzufügen-Button bleibt immer sichtbar.
- **Bildunterschrift (Caption).** Die Beschriftung eines Aufnahme-Zeitpunkts nennt beim Guss-Foto
  den Zeitplan-Namen statt der Startzeit; die feste Fotozeit behält die Uhrzeit. Dafür trägt die
  Ziel-Berechnung den Namen mit. Da die Beschriftung auch das per Telegram zugestellte Foto
  betrifft, wird `docs/design/telegram-nachrichten.html` mitgepflegt (Regel `telegram_messages.md`).
- **Markdown-Sicherheit.** Zeitplan-Namen werden in allen drei Anzeigen über das bestehende
  `_md_escape` entschärft (Legacy-Markdown, vermeidet HTTP 400).
- **Architektur.** Die Anzeige-Logik bleibt in der Telegram-UI; die Berechnung der
  Aufnahme-Zeitpunkte in `core/` (rein, ohne I/O). Kein Adapter ruft einen anderen direkt.

## Test-Entscheidungen (Testing Decisions)

- **Höchstgelegene Nahtstellen, bestehende bevorzugt.**
  - **Core (`tests/core`):** `next_photo_target` als reine Funktion — gestelltes `now`, Listen von
    Zeitplänen und festen Fotozeiten, fester Nach-Offset. Geprüft wird das **externe Verhalten**:
    Welcher Aufnahme-Zeitpunkt ist der nächste, welcher Typ/Name steckt im Label, korrekte
    Aufnahmezeit (Start + Dauer + Offset), Wahl des frühesten zukünftigen Ziels, leeres Ergebnis
    ohne Ziele. Vorbild: die bestehenden Tests der Kamera-Schedule-Core-Funktionen.
  - **UI (`tests/ui/test_telegram_ui.py`, gemockter `telegram_client`/`database`):** Die
    `/status`-Zeile erscheint mit korrektem Text bzw. entfällt (keine Kamera / keine Ziele);
    die Fotozeiten-Ansicht rendert die zwei Abschnitte mit den richtigen Einträgen, lässt leere
    Abschnitte weg, zeigt Guss-Fotos ohne Löschen-Button und die festen Zeiten mit. Vorbild: die
    bestehenden Status- und Fotozeiten-Tests.
  - **Caption:** Test, dass die Beschriftung eines Guss-Aufnahme-Zeitpunkts den Zeitplan-Namen
    enthält und die einer festen Fotozeit die Uhrzeit.
- **Kein Test von Implementierungsdetails** — geprüft wird das sichtbare Verhalten (Text,
  vorhandene/fehlende Buttons), nicht interne Strukturen.
- **Coverage** darf nicht regredieren.

## Nicht im Leistungsumfang (Out of Scope)

- **Anzeige des unsichtbaren Intervall-Bildes** („nächstes Bild überhaupt"). „Nächstes Foto" meint
  ausschließlich den nächsten Aufnahme-Zeitpunkt (das zugestellte Foto).
- **Editieren/Löschen von Guss-Fotos** in der Fotozeiten-Ansicht — sie folgen dem Zeitplan.
- **Pro-Kamera-Differenzierung** des nächsten Aufnahme-Zeitpunkts — Aufnahme-Zeitpunkte sind global
  (gelten für alle Kameras); es wird eine einzige Zeile gerendert.
- **Unterdrückung des Guss-Fotos bei regenbedingt übersprungenem Guss** (siehe Anmerkung).

## Weitere Anmerkungen (Further Notes)

- **Wechselwirkung mit Feature 0034 (Regen-Übersteuerung).** Wird ein Guss regenbedingt
  übersprungen oder reduziert, entsteht das Guss-Foto **trotzdem** — die Kamera taktet auf den
  Zeitplan, nicht auf den tatsächlichen Lauf. Der `/status` kündigt es entsprechend auch dann an.
  Diese Entkopplung bleibt vorerst bestehen (ADR 0036); eine spätere Kopplung (kein Foto bei
  Skip) wäre ein eigenes Feature.
- Die drei Anzeigen zeigen für Guss-Fotos die **Aufnahmezeit** (z. B. 06:12), die Caption nennt
  den **Namen ohne Zeit** — bewusst, damit keine widersprüchlichen Zahlen entstehen.
