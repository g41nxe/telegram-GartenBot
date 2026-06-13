# Hitzestrecke: datums-aware Streak-Berechnung

Die Hitzestrecke wird nicht durch einfaches Iterieren über die Listeneinträge von `get_daily_max_temps()` berechnet, sondern durch einen datumsbewussten Vergleich zwischen aufeinanderfolgenden Einträgen.

## Kontext

`get_daily_max_temps()` gibt Paare `(date_str, temp_max)` zurück, neueste zuerst. Bei lückenloser Datenhistorie wäre ein einfacher List-Index-Durchlauf korrekt. In der Praxis kann die Steuerzentrale jedoch kurzzeitig offline sein — dann fehlt ein Kalendertag in der Rückgabe, ohne dass die Liste das sichtbar macht.

## Entscheidung

`evaluate()` prüft zwischen je zwei aufeinanderfolgenden Einträgen, ob die Datumsdifferenz genau einen Tag beträgt. Ist die Differenz größer als ein Tag, wird der Streak-Zähler abgebrochen — unabhängig davon, wie heiß die übrigen Tage waren. Eine Lücke gilt als Unterbrechung der Hitzestrecke.

## Konsequenzen

- Ein Pi-Ausfall von einem Tag kann den Streak auf null zurücksetzen, selbst wenn die Temperatur davor und danach über dem Schwellenwert lag. Das ist eine bewusste Vereinfachung: fehlende Daten werden nicht interpoliert.
- Der einfachere List-Index-Ansatz darf nicht als Refactoring eingeführt werden — er würde Lücken stillschweigend ignorieren und den Streak nach Ausfällen falsch verlängern.
