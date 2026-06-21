# 31. Graduierte Gieß-Steuerung statt binärem Regen-Skip

Datum: 2026-06-21

## Status

Akzeptiert

## Kontext

Die bisherige Bewässerungsentscheidung war rein **binär** (`core/watering_advice.evaluate_rain_window`): Übersteigt die Summe aus gefallenem und vorhergesagtem Regen den Schwellenwert `RAIN_THRESHOLD_MM`, fällt der geplante Guss komplett aus — sonst läuft er unverändert. Diese Logik hat vier dokumentierte Schwächen:

1. **Nur Angebotsseite:** Der Wasserbedarf der Pflanze (Tagestemperatur, mehrtägige Hitze) fließt nicht ein — 3 mm bei 12 °C und 3 mm bei 35 °C führen zur identischen Entscheidung.
2. **Gemessen = vorhergesagt:** Unsicherer Forecast wird wie bereits gefallener Regen gewichtet; die abgerufene Regenwahrscheinlichkeit (`rain_prob`) wird verworfen.
3. **Alles-oder-nichts:** Bei teilweisem Regen gibt es nur „voller Guss" oder „Komplettausfall".
4. **Keine nutzbare Empfehlung** für den Benutzer.

Recherche zu gängigen Bewässerungssteuerungen (UF/IFAS, LSU AgCenter, OpenSprinkler Zimmerman, Rachio, ET-Wasserbilanz nach EPA WaterSense) ordnet die Varianten von simpel zu Goldstandard: reaktiver Regen-Skip → Forecast-Delay → kombiniertes Fenster (Status quo) → graduierte Wetter-Skalierung → ET-/Boden-Wasserbilanz.

## Entscheidung

Wir ersetzen die binäre Entscheidung durch einen **stufenlosen Skalierungsfaktor (0–100 %)** nach **Modell A** (linearer Regen-Quotient mit hitze-angepasster Schwelle):

```
R_eff        = rain_last + rain_next_eff            # rain_next_eff = Σ precip[h]·prob[h]/100
hitze_faktor = 1 + (heiß_heute ? B_today : 0) + min(streak, Cap)·B_streak
T_eff        = RAIN_THRESHOLD_MM · hitze_faktor
faktor       = clamp(1 − R_eff / T_eff, 0, 1)       # + Totzonen 0.9/0.1, 5%-Rundung
```

- Der Faktor skaliert im Scheduler **Zeit- und Volumenlimit** des geplanten Gusses. Der bisherige **binäre Skip bleibt als Sonderfall** `faktor == 0` erhalten (inkl. `should_skip_watering()`-Wrapper für Feature 0020 — ein Gehirn, zwei Sichten).
- Die Bedarfsseite (Temperatur heute + Hitzestrecke) hebt die effektive Schwelle, ohne je über 100 % zu gehen (kein Boost, konsistent mit dem Überflutungsschutz).
- Der Forecast wird als **erwarteter Niederschlag** stundenweise mit der Wahrscheinlichkeit gewichtet (fail-safe; fehlt die Wahrscheinlichkeit → Forecast trägt nicht bei).
- Die Logik lebt als **pure Funktion** `evaluate_watering()` in `core/` (ADR 0021) und wird von Scheduler, `/giesscheck` und Chart-Caption gemeinsam genutzt.

**Verworfene Alternativen:**

- **Modell B (diskrete Verdict-Stufen → feste Faktoren):** nutzt die 4-Stufen-Matrix 1:1, aber grob, ohne stufenlose Nutzung der Regenmenge und ohne natürliche Einbindung der Wahrscheinlichkeit.
- **Modell C (Boden-Wasserbilanz / ET-„Eimer"):** physikalischer Goldstandard mit Gedächtnis über Tage, aber deutlich größer (persistenter Zustand, ET-Modell, Kalibrierung) und sinnvoll erst auf Basis des lokalen Regensensors (Feature 0016). Bleibt als **Nordstern** dokumentiert; Modell A ist die inkrementelle Vorstufe und hält die Tür dafür offen.

## Konsequenzen

- **Wasserersparnis ohne Unterbewässerung:** Teilregen reduziert dosiert statt komplett zu überspringen; Hitze verhindert voreiliges Reduzieren.
- **Bedarfs- und konfidenzbewusst:** Temperatur/Hitzestrecke und Forecast-Wahrscheinlichkeit fließen erstmals in die Entscheidung ein.
- **Rückwärtskompatibel:** Mit `GIESSCHECK_HEAT_SENSITIVITY=0` und voller Wahrscheinlichkeit verhält sich der Faktor wie der alte binäre Skip.
- **Vorbereitet auf Feature 0016:** `rain_last` bleibt quellen-agnostisch; der lokale Regensensor wird später ohne Änderung am Rechenkern zur primären Quelle.
- **Mehr Bewegliches:** zusätzliche Konfiguration (`GIESSCHECK_*`), eine neue gecachte Spalte (`rain_next_eff_mm`) und ein neues Ereignis (`WateringScaled`). Der Faktor ist eine begründete Heuristik, kein physikalisches Bodenmodell — das bleibt Modell C vorbehalten.
- Vereinheitlicht `RAIN_THRESHOLD_MM` auf `3.0` (zuvor Drift zwischen Code `2.0` und Doku `3.0`).
- Referenziert: ADR 0003/0024/0028 (Wetterquellen), ADR 0020 (Cache-first), ADR 0021/0022 (pure Funktion, Hitzestrecke), ADR 0008 (Ereignis-Kanal), ADR 0029 (Design-System). Detailspezifikation: Feature 0009.
```
