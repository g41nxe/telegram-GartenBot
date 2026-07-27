# Testplan — gemeinsame Test-Session v1.18.1

**Umfang:** vier verhaltenserhaltende Refactors + zwei bewusste Änderungen
(ccc Chart-Caption, 6l3 Skip-Journaling). Alle 759 Unit-Tests grün, Cluster
code-reviewed. Diese Session prüft das Verhalten auf echter Hardware (Pi + MQTT +
Wetter-Dienst), das die Tests nicht abdecken.

**Vorbereitung**
- [ ] Release v1.18.1 ist auf der Steuerzentrale angekommen (Auto-Update oder `/update`).
- [ ] **0044-Selbsttest:** Beim Start meldet der Bot **„🚀 Update aktiv — jetzt auf `v1.18.1`"**. (Erste echte Bestätigung der Update-Benachrichtigung im Feld.)
- [ ] `sudo systemctl status garden-irrigation` → active, keine Traceback-Zeilen.
- [ ] `journalctl -u garden-irrigation -n 50` → sauberer Start, „Laufende Version: v1.18.1".

---

## 1 · ccc — Chart-Caption spiegelt die reale Gieß-Entscheidung
- [ ] `/tagesbericht` senden → Wetterchart erscheint.
- [ ] **Caption zeigt das Verdikt**: `🚿 Voller Guss` **oder** `💧 Reduzierter Guss (X %)` **oder** `🌧 Kein Gießen nötig` — **nicht** mehr „🌱 Gießen empfohlen — trocken bis morgen".
- [ ] Caption stimmt mit `/gießcheck` überein (dieselbe Wahrheit). → Bei Regen: beide sagen „Kein Gießen"; bei Trockenheit: beide „Voller Guss".
- [ ] **Resilienz:** (falls provozierbar) fällt die Bewertung aus, kommt das Chart trotzdem — nur mit Kopfzeile „🌤 Wetterverlauf …", ohne Verdikt-Zeile.

## 2 · 6l3 — Skip/Skalierung: ein Eigner, Journaling via Ereignis
- [ ] Einen Zeitplan so legen, dass er bei aktueller Wetterlage **übersprungen** wird (oder Regen abwarten). Zur Startzeit:
  - [ ] Telegram: **„🌧 Heute übernimmt der Regen — Zeitplan '…' übersprungen — …"**.
  - [ ] `journalctl` zeigt **„Guss bewusst übersprungen — …"** (INFO, Ticket 06v-Spur).
  - [ ] **Genau EINE `skipped`-Zeile** im Verlauf — `/diagnose` ziehen, in der DB `watering_history` prüfen: kein Doppel-Eintrag (der alte Direktaufruf hätte zwei erzeugt), Dauer = Original-Dauer des Zeitplans.
- [ ] Einen Zeitplan so legen, dass er **reduziert** läuft (leichter Regen): 
  - [ ] Telegram-Meldung „💧 Reduzierter Guss".
  - [ ] `journalctl`: „Guss auf X % skaliert (A→B Min)".
  - [ ] Ventil öffnet tatsächlich mit **reduzierter** Dauer/Menge; Verlauf zeigt einen `completed`-Zyklus mit den reduzierten Werten (kein separater „scaled"-Eintrag — bewusst, gegen Doppelzählung).
- [ ] Voller Guss (trocken): läuft normal, keine Skip/Scale-Meldung.

## 3 · 2jq — Wetterquellen-Fallback (frisch/live/stale/fail-safe)
- [ ] `/gießcheck` liefert eine plausible Empfehlung (frischer Cache-Pfad, Normalfall).
- [ ] `journalctl` bei einem Poll: **„Gieß-Faktor aus frischem DB-Cache"** wenn Cache jung; **kein** unnötiger Live-Abruf bei frischem Cache (Optimierung erhalten).
- [ ] (optional, schwer erzwingbar) Bei Netzausfall/altem Cache: Log „Nutze veralteten Cache im Vorhersagefenster" bzw. Fail-safe „Bewässerung zur Sicherheit" — Entscheidung bleibt sinnvoll (voller Guss statt Absturz).

## 4 · 6xy — Wetterdaten-Aufbereitung (null-sicher)
- [ ] `/status` bzw. Tagesbericht zeigen **plausible Werte**: Temp Min/Max, Regenwahrscheinlichkeit %, Regen 24h, Vorhersage-mm.
- [ ] `journalctl` „Wetterdaten geladen - …" ohne `TypeError` (der 11b-Bug), auch über einen Tag mit wechselnden Modelldaten.
- [ ] Wetterchart-Balken (±24h) sehen korrekt aus (Vergangenheit vs. Zukunft, Wahrscheinlichkeits-Färbung).

---

## Abbruch-/Rollback-Kriterien
- Traceback im `journalctl` beim Start oder bei `/tagesbericht`/`/gießcheck` → **Rollback** (der Health-Check von `update.sh` sollte das automatisch tun; dann meldet der Bot **„❌ Update fehlgeschlagen"** — ebenfalls ein 0044-Feldtest).
- Doppelte `skipped`-Zeile oder fehlender skalierter Guss → 6l3-Regression, nicht releasen bzw. zurückrollen.

## Nach erfolgreicher Session
- [ ] Kurzes Go/No-Go notieren; bei Go bleibt v1.18.1 stehen.
- [ ] Offen für später: `l97` (Umfang zu entscheiden), `cy1` (Assistent-Modul, eigene Runde), `eor`/`fok` (P3), `top` (wartet auf Kamera-Telemetrie).
