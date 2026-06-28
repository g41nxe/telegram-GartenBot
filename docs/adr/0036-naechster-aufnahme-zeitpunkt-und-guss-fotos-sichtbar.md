# 36. Nächsten Aufnahme-Zeitpunkt im Status und Guss-Fotos in den Fotozeiten sichtbar machen

Wir machen die geplanten Aufnahme-Zeitpunkte der Garten-Kamera für den Nutzer sichtbar:
Der `/status` zeigt den **nächsten Aufnahme-Zeitpunkt**, und die Fotozeiten-Ansicht listet
neben den festen Fotozeiten auch die abgeleiteten **Guss-Fotos**. Zugleich nennt die
Telegram-Bildunterschrift eines Guss-Fotos jetzt den auslösenden Zeitplan statt einer
irreführenden Uhrzeit.

## Kontext

Aufnahme-Zeitpunkte (CONTEXT.md) existieren bereits: Die Kamera wird gezielt nach jedem Guss
(Startzeit + Dauer + Nach-Offset) und zu festen Uhrzeiten geweckt; nur diese Fotos werden per
Telegram zugestellt, reguläre Intervall-Bilder nicht. Das Modell war bisher aber **unsichtbar**:

- Der `/status` zeigte den nächsten Guss, aber nicht, wann das nächste Foto kommt.
- Die Fotozeiten-Ansicht listete nur die festen Fotozeiten — die guss-basierten Aufnahme-
  Zeitpunkte fehlten, obwohl sie genauso Fotos erzeugen.
- Die Bildunterschrift eines Guss-Fotos lautete „Nach dem Guss um 06:00" — sie zeigte die
  **Guss-Startzeit**, obwohl das Bild erst Dauer + Offset später entsteht, und nannte bei
  mehreren Zeitplänen **keinen Namen**.

## Entscheidung

- **„Nächstes Foto" = nächster Aufnahme-Zeitpunkt**, nicht der unsichtbare Intervall-Tick. Da
  die Steuerzentrale die Kamera ohnehin auf den nächsten Aufnahme-Zeitpunkt taktet
  (`compute_next_sleep_seconds`), ist dieser Wert präzise bekannt und wird über eine reine
  Schwester-Funktion (`next_photo_target`) ermittelt.
- **`/status`-Zeile direkt unter „Nächster Guss"**: `📷 Nächstes Foto: heute 06:12 Uhr · nach
  Guss „Rasen"` bzw. `· feste Fotozeit`. Angezeigt wird der **tatsächliche Aufnahme-Zeitpunkt**
  (Start + Dauer + Nach-Offset), nicht die Guss-Startzeit. Die Zeile entfällt, wenn keine Kamera
  registriert ist oder keine Aufnahme-Zeitpunkte existieren; eine offline-Kamera unterdrückt sie
  nicht (es ist der Plan).
- **Fotozeiten-Ansicht in zwei Abschnitten**: „⏰ Feste Zeiten" (löschbar) und „🌿 Nach Güssen"
  (read-only, abgeleitet aus den **aktiven** Zeitplänen, mit berechneter Aufnahmezeit und
  Zeitplan-Name). Leere Abschnitte werden weggelassen; sind beide leer, bleibt die bisherige
  Leer-Meldung. Guss-Fotos sind bewusst nicht einzeln löschbar — sie folgen dem Zeitplan.
- **Bildunterschrift nennt den Anlass statt einer Uhrzeit**: Guss-Foto → „📷 Nach dem Guss
  „Rasen"" (Name, ohne Zeit); feste Fotozeit → „📷 Foto um 18:00" (unverändert). Dafür führt die
  interne Ziel-Berechnung den Zeitplan-Namen mit. `docs/design/telegram-nachrichten.html` wird
  angepasst.

## Konsequenzen

- Der Nutzer sieht, wann das nächste zugestellte Foto kommt und welche Aufnahme-Zeitpunkte sein
  Tag enthält — die bereits vorhandene Logik wird nur sichtbar gemacht, keine neue Entscheidungs-
  logik.
- Die Kernfunktionen in `core/camera_schedule.py` werden um strukturierte Label-Informationen
  (Typ + Zeitplan-Name) erweitert; `next_photo_target` kommt hinzu. Rein und testbar.
- Eine bestehende Nutzer-Nachricht (Guss-Foto-Caption) ändert sich — bewusst, da die alte Form
  (Startzeit, kein Name) irreführend war.
- **Bekannte Wechselwirkung (out of scope):** Wird ein Guss regenbedingt übersprungen
  (Feature 0034 / ADR 0035), entsteht das Guss-Foto trotzdem — die Kamera taktet auf den
  Zeitplan, nicht auf den tatsächlichen Lauf. Der `/status` kündigt es entsprechend auch dann an.
  Diese Entkopplung bleibt vorerst bestehen.
