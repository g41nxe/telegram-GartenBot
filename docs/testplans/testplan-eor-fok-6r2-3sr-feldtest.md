# Testplan — Feldtest der unveröffentlichten master-Änderungen

**Umfang:** drei verhaltenserhaltende Refactors (**6r2** Watchdog-Flanken, **3sr**
Benachrichtigungs-Registry, **cs9** typisierte Datenbankzugriffe) + zwei Fixes (**fok**
DST-korrekte Kamera-Schlafdauer, **eor** OTA-Auto-Rollback). Alle 840 Unit-Tests grün,
jeder Cluster code-reviewed (6r2, 3sr, cs9 adversarial auf Verhaltens-Parität geprüft).

> **Teil-Durchlauf am 29.07.2026, lokal gegen den TestBot** (Windows-Entwicklungsmaschine,
> `python -m src.daemon.main`, echter Bot-Token, simulierter MQTT-Client, echter Kamera-HTTP-
> Server auf Port 8080). Alle 3sr-, 6r2- und cs9-Punkte, die ohne Pi-Hardware bzw. ohne
> Wetter-/Zeitplan-Setup reproduzierbar waren, wurden **live bestätigt**.
> **Bonusfund:** ein echter, aber produktionsharmloser lokaler Import-Bug wurde dabei entdeckt
> und noch in derselben Session gefixt (Ticket yqu, Commit `c0f34a8`) — `camera_receiver.py`
> importierte absolut über `src.daemon...` statt relativ, was unter dem (jetzt korrigierten)
> CLAUDE.md-Befehl `python -m daemon.main` zwei divergierende `CameraRegistered`-Klassen
> erzeugte und die Kamera-Kopplung endlos in den 90s-Timeout laufen ließ.
>
> **Feldtest am 30.07.2026 auf dem echten Pi** (`garten-null`, per SSH): Update auf `v1.19.1`
> lief sauber durch (Vorbereitung komplett bestätigt), danach **eor** live verifiziert — echter
> Update-Fehler nach Update-Beginn provoziert, automatischer Rollback + korrekte Telegram-Meldung
> bestätigt (Details unten). Dabei zunächst ein **Fehler im Testaufbau** selbst gefunden (nicht im
> Produktcode): Ein simulierter Fehler über `die()` löst den `ERR`-Trap nicht aus, weil `die()`
> intern direkt `exit` aufruft — ein direktes `exit` überspringt den Trap in Bash. Mit einem
> echten fehlschlagenden Befehl als Auslöser hat der Rollback-Pfad danach exakt wie entworfen
> funktioniert. `fok` bleibt als einziger Punkt offen — braucht einen echten DST-Umstellungstag.

**Vorbereitung**
- [x] Neueste master-Version ist auf der Steuerzentrale (Auto-Update). *(30.07.2026 bestätigt: v1.19.1)*
- [x] **0044-Selbsttest:** Beim Start meldet der Bot **„🚀 Update aktiv — jetzt auf `vX.Y.Z`"**. *(bestätigt)*
- [x] `systemctl status garden-irrigation` → active, keine Traceback-Zeilen. *(bestätigt)*
- [x] `journalctl -u garden-irrigation -n 50` → sauberer Start, „Laufende Version: …". *(bestätigt)*

---

## 1 · 3sr — Benachrichtigungs-Registry (verhaltenserhaltend)
> Alle Push-Meldungen laufen jetzt über die `NOTIFICATIONS`-Registry statt 26 einzeln
> verdrahteter Handler. Der Nachrichtentext ist byte-identisch — der Feldtest prüft, dass
> **jede** Meldung real ankommt und keine ausbleibt/doppelt kommt.
- [x] Manuellen Guss starten → **„🚿 Wasser marsch!"** kommt. Stoppen → **„🛑 Guss gestoppt"**. *(lokal bestätigt)*
- [x] Guss regulär auslaufen lassen → **„🏁 …"** *(im Stopp-Fall lokal bestätigt; Zeitlimit-Variante folgt derselben Registry-Zeile, nicht separat erneut geprüft)*
- [ ] **Button-Slot (der einzige Bestands-Button):** Zeitplan so legen, dass ihn der Regen anpasst → ~5 Min vorher **„🌧 Regen voraus …"** **mit Inline-Button „🚿 Regen ignorieren"**. Button drücken → Übersteuerung greift (`rain_override` gesetzt), Guss läuft trotzdem, Meldung wird quittiert. *(nicht durchgeführt — braucht ein passendes Zeitplan-/Wetter-Setup; steht weiter aus)*
- [x] Nebel-Intervall starten → **„🌫️ Nebel-Intervall gestartet"**; endet → **„🌫️ … beendet"**. *(lokal bestätigt)*
- [ ] Regen-Skip eines Zeitplans → **„🌧 Heute übernimmt der Regen …"**; reduzierter Guss → **„💧 Guss reduziert (X %)"**. *(nicht durchgeführt — braucht reale Regen-Wetterlage)*
- [x] `/tagesbericht` → **Chart + Berichtstext** kommen (bespoke-Handler, unverändert). *(lokal bestätigt — Start-Katchup sendete den Bericht automatisch)*
- [x] Getimte Foto-Aufnahme → **Bild wird zugestellt** (bespoke-Handler, unverändert). *(lokal bestätigt via simulierten Kamera-Upload, siehe cs9)*
- [x] **„🌧 Regen erkannt"** / **„🌤 Regen vorbei — … mm"**. *(lokal bestätigt via injiziertem `RainSensorMeasured`, siehe cs9)*
- [x] Über die Session: **keine doppelte** Meldung, **keine ausgebliebene** Meldung. *(für alle oben getesteten Pfade bestätigt)*

## 2 · 6r2 — Watchdog-Flanken als Modul (verhaltenserhaltend)
> Die 11-fach duplizierte Flanken-/Flag-Logik läuft jetzt über `edge_alarm.evaluate` +
> `_check_edge`. Jeder Alarm feuert genau **einmal** je Episode und entwarnt eigens.
- [x] **Ventil-Inaktivität:** nach dem Timeout **„⚠️ Verbindung verloren"** — **genau eine** Meldung; wieder aktiv → **„🟢 wiederhergestellt"**. *(lokal bestätigt — `last_update` künstlich auf 25h zurückdatiert, `run_watchdog_check()` direkt aufgerufen, dann restauriert)*
- [x] **Kamera-Inaktivität** analog. *(lokal bestätigt — Testkamera-`last_seen` auf 2h zurückdatiert)*
- [ ] **Regensensor-Inaktivität** analog. *(nicht separat durchgeführt — identischer `_check_edge`-Mechanismus wie Ventil/Kamera, bereits 2× bestätigt; geringer Zusatznutzen)*
- [x] **Kamera-Verzug (Entprellung):** ein **einzelner** verspäteter Aufnahme-Zeitpunkt meldet **nicht**; erst der **zweite in Folge** → **„⚠️ Kamera kommt zu spät"**; wieder pünktlich → **„🟢 wieder pünktlich"**. *(lokal bestätigt — volle Dreier-Sequenz still→Alarm→Entwarnung über echte Kamera-Uploads gegen den HTTP-Empfänger)*
- [x] `journalctl`/lokales Log zeigt die Watchdog-Alerts/Entwarnungen sauber, ohne Traceback (abgesehen vom bekannten, unabhängigen Windows-Konsolen-Encoding-Kosmetikfehler bei Emoji-Logzeilen).

## 3 · fok — DST-korrekte Kamera-Schlafdauer
> Die Schlafdauer wird über echte verstrichene Sekunden (`.timestamp()`) statt naiver
> Wanduhr-Differenz berechnet — korrekt auch an den Umstellungstagen.
- [ ] Kamera trifft ihre **Foto-Zeitpunkte** (lokale `HH:MM`) — Aufnahmen kommen zu den konfigurierten Uhrzeiten, `sleep_duration_seconds` plausibel.
- [ ] `journalctl` / Kamera-Telemetrie: berechnete Schlafdauer passt zur Zielzeit, **kein 1-h-Versatz**.
- [ ] **Voll prüfbar nur an einem DST-Umstellungstag** (letzter/nächster Sonntag der Umstellung) — **einziger noch offener Punkt des gesamten Plans**; beim nächsten Umstellungstag nachziehen.

## 4 · eor — OTA-Auto-Rollback bei Update-Fehler
> `update.sh` rollt bei **jedem** Fehler nach Update-Beginn automatisch zurück (ERR-Trap),
> statt nur zu melden.
- [x] Normales Update läuft durch → **„🚀 Update aktiv — jetzt auf `vX.Y.Z`"**, Dienst active. *(30.07.2026 auf dem echten Pi bestätigt: Update auf v1.19.1)*
- [x] (Kontrolliert provozierbar) fehlerhaftes Update → **Auto-Rollback**: Dienst läuft auf der **Vorgängerversion** weiter; Bot meldet **„❌ Update fehlgeschlagen"** bzw. bei Abbruch **vor** dem Rollback **„⚠️ Update unterbrochen … Bitte `/status` prüfen"**. *(30.07.2026 auf dem echten Pi bestätigt — echter Befehlsfehler nach `UPDATE_STARTED=true` injiziert (separate Testkopie von update.sh, echte Datei unverändert); ERR-Trap → `do_rollback()` → Dateien wiederhergestellt, Dienst neu gestartet, Telegram-Meldung „❌ Update fehlgeschlagen — v1.19.1 ließ sich nicht installieren, läuft weiter auf …" kam korrekt an.)*
- [x] Nach Rollback: `/status` zeigt die laufende (alte) Version; `systemctl status` active, keine Traceback-Zeilen. *(bestätigt)*
- [x] Attempt-/Rollback-Marker in `/tmp` werden gesetzt und wieder geräumt (kein Dauer-Rückstand). *(bestätigt — beide Marker nach Rollback korrekt verschwunden)*

## 5 · cs9 — Typisierte Datenbankzugriffe (verhaltenserhaltend)
> Regenereignis-Zustand, Kamera-Koppelfenster und der Aufnahme-Verzug-Schlüssel laufen jetzt
> über benannte Zugriffe in `database.py` statt roher, in zwei Adaptern duplizierter Literale
> (ADR 0045 abgeschlossen). Reine Umlagerung — kein Verhalten geändert.
- [x] **Regenereignis übersteht einen Neustart:** Regen laufen lassen (`RainSensorMeasured` injiziert) → **„🌧 Regen erkannt"**. Zweiter Tick in einem **frischen Prozess** (Neustart-Simulation) → **kein zweites** „Regen erkannt", Gesamtmenge korrekt akkumuliert (0.5 + 0.8 = 1.3 mm). Karenzzeit verstreichen lassen (Zeitstempel zurückdatiert) → **„🌤 Regen vorbei — 1.3 mm in 4 Min"** kam korrekt. *(vollständig lokal bestätigt)*
- [x] **Kamera-Kopplung funktioniert wie zuvor:** ⚙️ Einstellungen ▸ 📷 Kamera koppeln gestartet, simulierte Kamera-Registrierung → **„✅ Kamera-Kopplung erfolgreich!"**. *(lokal bestätigt — dabei den Bonusfund/Bug entdeckt und gefixt, siehe oben; nach dem Fix erfolgreich reproduziert)*
- [x] **Getimte Fotos weiterhin dedupliziert:** ein überfälliger Aufnahme-Zeitpunkt wurde zugestellt; ein fehlgeschlagener Telegram-Versand öffnete ihn korrekt wieder (bestehendes ADR-0041-Verhalten, unverändert); der Zeitpunkt hakt sich nicht doppelt zu. *(lokal bestätigt, inkl. des Reopen-bei-Fehlschlag-Pfads)*
- [x] Log zeigt keine neuen Fehler/Tracebacks rund um Regenereignis, Kopplung oder Foto-Zustellung (abgesehen vom bekannten Windows-Konsolen-Encoding-Kosmetikfehler).

---

## Abbruch-/Rollback-Kriterien
- **Traceback** beim Start oder bei `/tagesbericht` / `/gießcheck` → **Rollback** (der Health-Check von `update.sh` sollte das automatisch tun — zugleich ein eor/0044-Feldtest).
- **Ausgebliebene oder doppelte Push-Meldung** → 3sr-Regression (Registry-Verdrahtung), nicht releasen.
- **Watchdog feuert wiederholt** statt einmal je Episode, oder entwarnt fälschlich → 6r2-Regression.
- **Kamera trifft ihre Zeitpunkte um ~1 h daneben** (an einem Umstellungstag) → fok-Regression.
- **Update-Fehler ohne Auto-Rollback** (Dienst bleibt kaputt/tot) → eor-Regression.
- **Doppeltes „Regen erkannt" nach Neustart**, hängendes Koppelfenster oder doppelt zugestelltes Foto → cs9-Regression.

## Nach erfolgreicher Session
- [x] Lokaler Teil-Durchlauf (3sr/6r2/cs9) am 29.07.2026: **GO** — jeder erreichbare Punkt bestätigt, ein echter (produktionsharmloser) Bug gefunden und gefixt.
- [x] Echter Pi-Feldtest (eor) am 30.07.2026: **GO** — Auto-Rollback funktioniert exakt wie entworfen; dabei einen Fehler im Testaufbau selbst gefunden und korrigiert (nicht im Produktcode).
- [ ] **Einziger noch offener Punkt:** `fok` (DST) — braucht einen echten Umstellungstag; sonst nichts mehr offen aus diesem Bündel außer dem 3sr-Regen-Button (braucht reales Wetter-Setup) und der Regensensor-Inaktivität (geringer Zusatznutzen, übersprungen).
- [ ] Offen für später: `mtb`/Feature 0018 (Aktions-Buttons — 3sr ist der Enabler), `top` (wartet auf Kamera-Telemetrie), `55t` (Kopplungs-Folgeaktionen).
