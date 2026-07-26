# 46. Einheitliche Wizard-Engine (reine Zustandsmaschine + Spec-Registry)

Alle mehrstufigen Bot-Dialoge (Zeitplan anlegen, Nebel-Intervall, Sofort-Guss, Sofort-Nebel,
Kamera-Kopplung, Kamera-Einstellungen, Ventil-Kopplung, Löschen, Bearbeiten) laufen über **eine**
gemeinsame Engine: eine reine `Assistent`-Zustandsmaschine je Dialog plus ein deklarativer
`WizardSpec`-Eintrag. Kein wizard-spezifisches Dispatch-/Treiber-/Normalisier-Glue mehr.

## Kontext

Nach ADR 0039 lief jeder Wizard zwar über `show_step`, aber die Verdrahtung war je Wizard
handgeschrieben: `_X_prompt_text`, `_X_keyboard`, `_normalize_X_callback`, `_drive_X`, plus
Typ-Verzweigungen in `_wizard_driver`/`_manual_driver`. Acht Wizards ⇒ vielfach dupliziertes
Muster; ein neuer Wizard oder eine neue Speiche bedeutete Änderungen an mehreren Stellen.

Zwei Dialoge passten scheinbar nicht ins Muster:
- **Löschen** war eine Reply-Keyboard-Bestätigung mit Text-Treffer (kein Inline-Flow).
- **Bearbeiten** ist ein *Nabe-Speiche*-Feldeditor, kein linearer Fluss — und der Alt-Editor
  schrieb **nach jedem Feld sofort** in die DB (I/O mitten im Fluss), was die reine Maschine
  (`advance() -> Prompt | Reject | Done`, ohne I/O) nicht abbilden kann.

## Entscheidung

- **Ein Assistent = reine Zustandsmaschine** (`ui/assistent.py`): `advance(value)` liefert eine
  reine Absicht (`Prompt` / `Reject` / `Done`) — keine Präsentation, kein I/O. Nabe-Speiche ist
  kein Sonderfall: ein `menu`-Schritt, zu dem mehrere Übergänge zurückführen, ist ein normaler
  Zustandsgraph.
- **Ein `WizardSpec` je Assistent** (`ui/telegram_ui.py`) bündelt die Präsentation + Verdrahtung:
  `store`, `text(view, data)`, `keyboard(tag, assistent)`, `callbacks` (deklarative Regel-Liste
  prefix→cast bzw. exakt→Wert), `on_done(chat_id, state, message_id)`, `cancel`. Eine Registry
  `WIZARDS: {AssistentTyp -> WizardSpec}`.
- **Je genau eine generische Funktion**: `_apply_rules` (Callback→Wert), `_render_wizard`,
  `_drive_wizard`, `_start_wizard` (Einstieg), `_drive_typed` und `_dispatch_wizard_callback`.
  Dispatch und getippte Eingabe schlagen die Spec über `type(assistent)` nach.
- **Bearbeiten passt komplett ins Schema** durch **Batch-Speichern**: Feldänderungen sammeln sich
  im vorbefüllten `data`; erst „✅ Fertig" löst **ein** `Done` aus → der Adapter schreibt alles in
  einem `update_schedule`. Damit gibt es kein I/O mitten in der Maschine — und Bearbeiten wird
  transaktional (Abbrechen lässt den Zeitplan unberührt statt Teiländerungen stehenzulassen).
- **Löschen wird ein Inline-Dialog** (`DeleteConfirmAssistent`), womit die letzte
  Reply-Keyboard-Sonderrolle verschwindet.
- **`wants_text()`-Wache am Assistenten**: getippte Eingabe geht nur an Schritte, die Text erwarten
  (`_text_steps`); auf einem Button-Schritt wird Text ignoriert statt `int("Unsinn")` abzustürzen.

## Konsequenzen

- **Einen Wizard anlegen/warten** kostet: 1 `Assistent`-Klasse (die Logik) + 1 `WizardSpec`-Eintrag.
  Kein Dispatch-Code, keine Treiber-Wrapper, keine Typ-Verzweigung mehr — weniger individueller
  Wartungsaufwand, weniger Divergenz.
- **Schicht-Trennung bleibt (ADR 0045):** reine Maschinen + Validierung in `assistent.py`;
  deutsche Texte, Keyboards, DB-/Aktions-Aufrufe in `telegram_ui.py`.
- **Der alte, wizard-spezifische Router entfällt**: die durch den Retrofit tot gewordenen
  `_drive_*`/`_normalize_*`/`_render_*_prompt`-Funktionen und die Alt-Callback-Zweige/-Message-
  Handler werden entfernt; die einheitliche Engine ist die einzige Mechanik.
- Baut auf ADR 0039 (eine lebende Prompt-Nachricht, `show_step`) auf — die Invariante bleibt, nur
  hinter *einem* generischen Renderer statt je Wizard.
- Abgesichert durch je einen Ende-zu-Ende-Paritäts-/Verhaltens-Test pro Wizard (Treiber über die
  echten Dispatcher), die vor **und** nach der Migration grün bleiben.
