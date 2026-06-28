## v1.12.2 — 2026-06-28

### Behoben
- Regensensor (Aqua Scope RANWIE01): Daten werden jetzt im echten Geräteformat eingelesen
  (Topic AQS/…, Regen in 0,5-mm-Schritten, Batterie aus Verbrauch berechnet)

---

## v1.12.1 — 2026-06-28

### Behoben
- „Stopp" schließt jetzt auch extern/manuell geöffnete Ventile, nicht nur laufende Güsse und Nebel

---

## v1.12.0 — 2026-06-28

### Neu
- Bot-Bedienung neu strukturiert: alle Befehle auf Deutsch, nach Domäne gruppiert
- „📷 Kamera"- und erweitertes „⚙️ Einstellungen"-Untermenü bündeln die Funktionen
- „Bewässern" als gemeinsamer Einstieg: Art (Guss/Nebel) → Ventil → Details
- Sofort-Nebel: Stoß-Dauer und Pause pro Lauf wählbar
- „Stopp" stoppt Güsse und Nebel gemeinsam (Auswahl bei mehreren aktiven Quellen)
- Aufgeräumtes Befehlsmenü; Foto-Anzeige zog ins Kamera-Untermenü

### Behoben
- Manuell gestopptes Nebel-Fenster läuft nicht mehr von selbst wieder an
- Nachrichten mit Sonderzeichen im Namen (z. B. „_") wurden von Telegram verworfen
- Lange Zeitplan-Listen werden automatisch aufgeteilt statt abzubrechen

---

## v1.11.2 — 2026-06-28

### Behoben
- Foto „nach dem Guss" wurde bei mehrfachem Kamera-Upload doppelt gesendet

---

## v1.11.1 — 2026-06-27

### Behoben
- Zweites Ventil (Nebel-Düse) zeigte dauerhaft 🔴 in /status trotz aktivem Zigbee-Link
- TestNebelScheduling schlug täglich nach 18 Uhr fehl (Datumsabhängigkeit behoben)

---

## v1.11.0 — 2026-06-27

### Neu
- Ventil-Auswahl im Bewässerungs-Wizard: bei mehreren Ventilen wählt man eines aus
- Bearbeiten-Menü zeigt das zugewiesene Ventil und erlaubt Änderung

### Behoben
- Nebel-Wizard-Bestätigung: Ventilname mit Sonderzeichen führte zu HTTP 400

---

## v1.10.1 — 2026-06-27

### Behoben
- /status wurde bei einem nicht-grünen (z.B. offline) Ventil von Telegram abgelehnt (Markdown-400)
- Ventil-, Kamera- und Zeitplan-Namen in /status gegen Markdown-Sonderzeichen abgesichert

---

## v1.10.0 — 2026-06-27

### Neu
- Nebel-Intervall: Terrassen-Kühlung über eine Nebeldüse in regelmäßigen Stößen
- Geplante Nebel-Fenster (Start–Ende) und manueller Sofort-Nebel per Telegram

### Intern
- CI: fetch-tags entfernt (kollidierte mit Tag-Trigger im Checkout)

---

## v1.9.1 — 2026-06-26

### Intern
- Bot UX Redesign (Feature 0031): Spec, Implementierungsplan und Beads-Issue angelegt
- CONTEXT.md: UI-Ausnahmen für Kamera-Untermenü-Labels dokumentiert

---

## v1.9.0 — 2026-06-26

### Neu
- Getimte Kamera-Aufnahmen: Kamera nimmt automatisch zu konfigurierten Uhrzeiten auf
- Neuer Befehl /aufnahmen zur Verwaltung der Foto-Zeitpunkte (inkl. Wizard)
- Kamera wacht nach dem Guss automatisch kurz auf und macht ein Foto

### Intern
- Feature-Abschluss-Rule: Beads-Ticket und Docs-Pflege immer im selben Commit
- Release-Trigger nur noch über Versions-Tag (nicht mehr bei jedem Branch-Push)

---

## v1.8.0 — 2026-06-26

### Neu
- Bild-Historie einer Kamera löschen: neuer Befehl /photo_clear (mit Rückfrage)

### Behoben
- OTA-Update: config/ wird ins Release-Archiv und Update-Skript aufgenommen

### Intern
- Scheduler-Loop-Test gegen prozessweiten time.sleep-Patch abgesichert (flaky behoben)
- Spezifikation für getimte Kamera-Aufnahmen (Feature 0030) ergänzt

---

## v1.7.0 — 2026-06-25

### Neu
- Benachrichtigung bei unerwarteter Ventilöffnung (Push, wenn ein Ventil ohne aktiven Guss öffnet)

### Behoben
- Wassermengenmessung: Guss-Volumen wieder korrekt erfasst (Volumenlimit greift, Historie stimmt)

---

## v1.6.1 — 2026-06-25

### Behoben
- Wassermengenmessung: Guss-Volumen wird korrekt gezählt (Volumenlimit & Historie)
- Gießcheck: Tageshöchsttemperaturen nutzen jetzt die lokale Zeitzone
- Reduzierter Guss erhält mindestens 1 Liter Volumenlimit

### Intern
- Regenschwelle aus Config statt hartkodiert (chart.py), Import aufgeräumt
- Folge-Ticket dokumentiert: Simulator-Treue für Volumen-Pfad (Feature 0028)

---

## v1.6.0 — 2026-06-22

### Neu
- Wetterchart: „Jetzt"-Markierung mit vertikaler Linie und Stunden-Raster

### Intern
- Guss-Steuerung: doppelten Volumenlimit-Abschluss in Helfer extrahiert
- Scheduler: reine, isoliert testbare Entscheidungsfunktion extrahiert
- Test-Isolation der Hitzestrecke (test_06) verbessert

---

## v1.5.0 — 2026-06-22

### Neu
- Regensensor-Integration: lokale Messungen ersetzen ERA5 als Regen-Quelle (Feature 0016)
- Guss-Unterbrechung: laufender Guss stoppt sofort, wenn Regen einsetzt
- Regen-Benachrichtigung beim Ein- und Aussetzen von Regen (Flankensteuerung)
- Graduierte Gieß-Steuerung: 0–100 % Skalierungsfaktor statt binärem Skip (Feature 0009)
- /giesscheck: Gieß-Empfehlung mit Verdict und Begründung
- Wetterchart zeigt jetzt ±24 h (gefallener + erwarteter Regen)

### Intern
- Sandcastle-Pipeline: Review-only-Modus, EOL-robuster Diff
- Zeilenenden im Repo auf LF normalisiert (.gitattributes)

---

## v1.4.0 — 2026-06-21

### Neu
- Morgen-Bericht: Tagesbericht als kompaktes Briefing (Kurzform/Problemfall)
- /status geschärft: nächste Bewässerung, Volumen in Historie, weniger Rauschen
- In-Chat-Einstellungen: Konfiguration direkt im Telegram-Chat ändern
- Zeitplan-Bearbeitung: bestehende Zeitpläne ändern statt neu anlegen
- Kamera-Akkustand wird in /status angezeigt
- Telegram-Responsivität & bessere Auffindbarkeit der Befehle
- Secrets (Token, Koordinaten) getrennt in .env (ADR 0030)

### Fixes
- Bugs in 4 Modulen behoben (Code-Review 0022/0024)

### Intern
- Dev-Infrastruktur: Beads-Tracker, Sandcastle-Pipeline, pytest-Runner

---

## v1.3.0 — 2026-06-19

- Telegram Design-System: Garten-Ampel (🟢/🟡/🔴) im /status-Befehl
- Progressive Disclosure: Technische Details nur bei Geräteproblemen sichtbar
- Hauptmenü-Buttons 🟢→🚿 und 🔴→🛑 (Ampelfarben freigehalten)
- Alle Nachrichten auf Legacy-Markdown migriert (* statt **), behebt stille HTTP-400-Fehler bei Telegram
- Regen-Skip-Emoji: 🌤️ → 🌧
- Nie-gekoppeltes Ventil korrekt als 🔴 markiert (statt fälschlich grün)

---

## v1.2.1 — 2026-06-15

- /update: Markdown-Sonderzeichen in Release-Notes werden jetzt escaped
- /update: Fallback-Dialog wenn die Telegram-API die Update-Nachricht ablehnt

---

## v1.2.0 — 2026-06-15

### Neu
- Garten-Kamera-Integration: M5Stack Timer Camera F per /camera_setup koppeln,
  Fotos via /photo abrufen, Kamera-Watchdog bei Ausfall
- Kamera-Setup Wizard (4 Schritte): Name, Intervall, Auflösung (VGA/XGA/UXGA),
  Bildqualität (Hoch/Mittel/Niedrig)
- Kamera-Status in /status: Online/Offline-Indikator, letztes Bild, Einstellungen
- /photo Caption zeigt Aufnahmezeitstempel
- Gemessene Regendaten (ERA5/Archiv): korrekte Skip-Entscheidungen nach echtem Regen
- Deterministischer Vorhersage-Tagessnapshot — manueller /report verschiebt
  Vergleichsbasis nicht mehr
- Hauptmenü reorganisiert: ⚙️ Setup-Untermenü für Kopplungsbefehle

### Fixes
- /report: gemeinsamer Abruf für Chart-Caption und Berichtstext
- Tagesbericht zeigt "keine Messung" statt falscher Zahl bei fehlendem ERA5-Wert

---

## v1.1.2 — 2026-06-14

- Architektur-Bereinigung: Scheduler-Fassade über Guss-Steuerung aufgelöst
- `telegram_bot.py` Pass-Through entfernt, Verdrahtung direkt in `main.py`
- `send_daily_report()` entkoppelt: kein sleep/MQTT-Prefetch mehr im Adapter
- README und CLAUDE.md auf aktuellen Modulstand gebracht

---

## v1.1.1 — 2026-06-14

- OTA-Bestätigung per Telegram nach erfolgreichem Update
- Release-Build zeigt jetzt die korrekte Versionsnummer

---

## v1.1.0 — 2026-06-14

- Wetterchart zeigt jetzt 2h Vergangenheit + 22h Vorhersage
- Regenschwelle auf 2.0mm gesenkt (konfigurierbar via RAIN_THRESHOLD_MM)
- Tagesbericht: Leerzeilen zwischen den Abschnitten

---

## v1.0.1 — 2026-06-14

- Wassermengenmessung korrigiert (SWV-ZFE meldet Liter, nicht L/min)

---

## 2026-06-14

- Release-Notes im /update-Dialog (aus CHANGELOG.md)
- Automatische Telegram-Benachrichtigung nach Update (Erfolg und Rollback)
- /release-Skill für geführten Release-Workflow
- Gieß-Empfehlung berücksichtigt jetzt auch Regen der letzten 24h
- Wetterchart-Verbesserungen (0°-Linie, sauberere Labels)

---
