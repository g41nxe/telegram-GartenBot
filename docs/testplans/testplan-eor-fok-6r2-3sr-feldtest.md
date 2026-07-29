# Testplan — Feldtest der unveröffentlichten master-Änderungen

**Umfang:** drei verhaltenserhaltende Refactors (**6r2** Watchdog-Flanken, **3sr**
Benachrichtigungs-Registry, **cs9** typisierte Datenbankzugriffe) + zwei Fixes (**fok**
DST-korrekte Kamera-Schlafdauer, **eor** OTA-Auto-Rollback). Alle 840 Unit-Tests grün,
jeder Cluster code-reviewed (6r2, 3sr, cs9 adversarial auf Verhaltens-Parität geprüft).
Diese Session prüft, was die Tests **nicht** abdecken: echte Telegram-Zustellung,
MQTT/Hardware-Timing, OTA am echten Pi, Zeitzone am realen Kalendertag, Zustand über
einen echten Daemon-Neustart hinweg.

> Dieser Plan bündelt die aktuelle master-Vorlage; er wird beim nächsten Release
> (Version dann via `release`-Skill) zur Release-Abnahme. **Noch nicht durchgeführt** —
> Häkchen erst beim Durchlauf setzen.

**Vorbereitung**
- [ ] Neueste master-Version ist auf der Steuerzentrale (Auto-Update oder `/update`).
- [ ] **0044-Selbsttest:** Beim Start meldet der Bot **„🚀 Update aktiv — jetzt auf `vX.Y.Z`"**.
- [ ] `sudo systemctl status garden-irrigation` → active, keine Traceback-Zeilen.
- [ ] `journalctl -u garden-irrigation -n 50` → sauberer Start, „Laufende Version: …".

---

## 1 · 3sr — Benachrichtigungs-Registry (verhaltenserhaltend)
> Alle Push-Meldungen laufen jetzt über die `NOTIFICATIONS`-Registry statt 26 einzeln
> verdrahteter Handler. Der Nachrichtentext ist byte-identisch — der Feldtest prüft, dass
> **jede** Meldung real ankommt und keine ausbleibt/doppelt kommt.
- [ ] Manuellen Guss starten → **„🚿 Wasser marsch!"** kommt. Stoppen → **„🛑 Guss gestoppt"**.
- [ ] Guss regulär auslaufen lassen → **„🏁 …"** (Volumen- bzw. Zeitlimit-Variante).
- [ ] **Button-Slot (der einzige Bestands-Button):** Zeitplan so legen, dass ihn der Regen anpasst → ~5 Min vorher **„🌧 Regen voraus …"** **mit Inline-Button „🚿 Regen ignorieren"**. Button drücken → Übersteuerung greift (`rain_override` gesetzt), Guss läuft trotzdem, Meldung wird quittiert.
- [ ] Nebel-Intervall starten → **„🌫️ Nebel-Intervall gestartet"**; endet → **„🌫️ … beendet"**.
- [ ] Regen-Skip eines Zeitplans → **„🌧 Heute übernimmt der Regen …"**; reduzierter Guss → **„💧 Guss reduziert (X %)"**.
- [ ] `/tagesbericht` → **Chart + Berichtstext** kommen (bespoke-Handler, unverändert).
- [ ] Getimte Foto-Aufnahme → **Bild wird zugestellt** (bespoke-Handler, unverändert).
- [ ] (falls Regen) **„🌧 Regen erkannt"** / **„🌤 Regen vorbei — … mm"**.
- [ ] Über die Session: **keine doppelte** Meldung, **keine ausgebliebene** Meldung.

## 2 · 6r2 — Watchdog-Flanken als Modul (verhaltenserhaltend)
> Die 11-fach duplizierte Flanken-/Flag-Logik läuft jetzt über `edge_alarm.evaluate` +
> `_check_edge`. Jeder Alarm feuert genau **einmal** je Episode und entwarnt eigens.
- [ ] **Ventil-Inaktivität** (falls provozierbar, z. B. Ventil vom Netz): nach dem Timeout **„⚠️ Verbindung verloren"** — **genau eine** Meldung; wieder aktiv → **„🟢 wiederhergestellt"**.
- [ ] **Kamera-Inaktivität** analog (Kamera länger als das dynamische Limit stumm).
- [ ] **Regensensor-Inaktivität** analog (falls provozierbar).
- [ ] **Kamera-Verzug (Entprellung):** ein **einzelner** verspäteter Aufnahme-Zeitpunkt meldet **nicht**; erst der **zweite in Folge** → **„⚠️ Kamera kommt zu spät"** bzw. „… kein Bild"; wieder pünktlich → **„🟢 wieder pünktlich"**.
- [ ] `journalctl` zeigt die Watchdog-Alerts/Entwarnungen sauber, ohne Traceback.

## 3 · fok — DST-korrekte Kamera-Schlafdauer
> Die Schlafdauer wird über echte verstrichene Sekunden (`.timestamp()`) statt naiver
> Wanduhr-Differenz berechnet — korrekt auch an den Umstellungstagen.
- [ ] Kamera trifft ihre **Foto-Zeitpunkte** (lokale `HH:MM`) — Aufnahmen kommen zu den konfigurierten Uhrzeiten, `sleep_duration_seconds` plausibel.
- [ ] `journalctl` / Kamera-Telemetrie: berechnete Schlafdauer passt zur Zielzeit, **kein 1-h-Versatz**.
- [ ] **Voll prüfbar nur an einem DST-Umstellungstag** (letzter/nächster Sonntag der Umstellung) — sonst als „steht aus" markieren und beim nächsten Umstellungstag nachziehen.

## 4 · eor — OTA-Auto-Rollback bei Update-Fehler
> `update.sh` rollt bei **jedem** Fehler nach Update-Beginn automatisch zurück (ERR-Trap),
> statt nur zu melden.
- [ ] Normales Update läuft durch → **„🚀 Update aktiv — jetzt auf `vX.Y.Z`"**, Dienst active.
- [ ] (Kontrolliert provozierbar) fehlerhaftes Update → **Auto-Rollback**: Dienst läuft auf der **Vorgängerversion** weiter; Bot meldet **„❌ Update fehlgeschlagen"** (Rollback vollzogen) bzw. bei Abbruch **vor** dem Rollback **„⚠️ Update unterbrochen … Bitte `/status` prüfen"**.
- [ ] Nach Rollback: `/status` zeigt die laufende (alte) Version; `systemctl status` active, keine Traceback-Zeilen.
- [ ] Attempt-/Rollback-Marker in `/tmp` werden gesetzt und wieder geräumt (kein Dauer-Rückstand).

## 5 · cs9 — Typisierte Datenbankzugriffe (verhaltenserhaltend)
> Regenereignis-Zustand, Kamera-Koppelfenster und der Aufnahme-Verzug-Schlüssel laufen jetzt
> über benannte Zugriffe in `database.py` statt roher, in zwei Adaptern duplizierter Literale
> (ADR 0045 abgeschlossen). Reine Umlagerung — kein Verhalten geändert.
- [ ] **Regenereignis übersteht einen Neustart:** Regen laufen lassen (`RainEventStarted`), Daemon währenddessen neu starten (`sudo systemctl restart garden-irrigation`) → **kein zweites** „🌧 Regen erkannt", Gesamtmenge läuft nach dem Neustart korrekt weiter, `/tagesbericht` zeigt die volle Menge.
- [ ] **Kamera-Kopplung funktioniert wie zuvor:** ⚙️ Einstellungen ▸ 📷 Kamera koppeln starten, Kamera meldet sich → **„✅ Kamera-Kopplung erfolgreich!"**; Timeout ohne Meldung → **„❌ Kamera-Kopplung fehlgeschlagen"**. Koppelfenster schließt sich in beiden Fällen zuverlässig (zweiter Kopplungsversuch startet sauber).
- [ ] **Getimte Fotos weiterhin dedupliziert:** über mehrere Aufnahme-Zeitpunkte hinweg kein doppelt zugestelltes Foto (dieselbe `last_delivered_target`-Logik wie zuvor, nur zentralisiert).
- [ ] `journalctl` zeigt keine neuen Fehler/Tracebacks rund um Regenereignis, Kopplung oder Foto-Zustellung.

---

## Abbruch-/Rollback-Kriterien
- **Traceback** beim Start oder bei `/tagesbericht` / `/gießcheck` → **Rollback** (der Health-Check von `update.sh` sollte das automatisch tun — zugleich ein eor/0044-Feldtest).
- **Ausgebliebene oder doppelte Push-Meldung** → 3sr-Regression (Registry-Verdrahtung), nicht releasen.
- **Watchdog feuert wiederholt** statt einmal je Episode, oder entwarnt fälschlich → 6r2-Regression.
- **Kamera trifft ihre Zeitpunkte um ~1 h daneben** (an einem Umstellungstag) → fok-Regression.
- **Update-Fehler ohne Auto-Rollback** (Dienst bleibt kaputt/tot) → eor-Regression.
- **Doppeltes „Regen erkannt" nach Neustart**, hängendes Koppelfenster oder doppelt zugestelltes Foto → cs9-Regression.

## Nach erfolgreicher Session
- [ ] Kurzes Go/No-Go notieren; bei Go geht das Bündel ins nächste Release (`release`-Skill).
- [ ] Offen für später: `mtb`/Feature 0018 (Aktions-Buttons — 3sr ist der Enabler), `top` (wartet auf Kamera-Telemetrie), `55t` (Kopplungs-Folgeaktionen).
