# Feature: Telegram-Menü & Interaktive Zeitsteuerung

## Problemstellung (Problem Statement)

1. **Eingeschränkte Menüführung**: Die Bedienung des Telegram-Bots ist derzeit auf das manuelle Tippen von Befehlen oder die Verwendung von statischen Reply-Keyboards angewiesen. Es gibt keine native Telegram-Befehlsübersicht im Eingabefeld (Menu Button), was die Entdeckbarkeit der verfügbaren Steuerungen erschwert.
2. **Klassische ID-basierte Verwaltung**: Befehle zum Verwalten von Zeitplänen wie `/add`, `/delete <ID>` und `/toggle <ID>` verlangen vom Benutzer, dass er die IDs der Zeitpläne auswendig lernt oder manuell eintippt. Dies führt zu Tippfehlern und einer umständlichen Benutzererfahrung.
3. **Inkonsistente Bestätigungen**: Bestätigungen (wie das Speichern eines neuen Zeitplans oder das Überschreiben einer Ventil-Kopplung) verwenden teilweise Inline-Keyboards, die sich von anderen Systembestätigungen unterscheiden und leicht versehentlich geklickt werden können.

## Lösung (Solution)

1. **Telegram Menu Button & Befehlsregistrierung**: Der Bot registriert seine Kernbefehle (`status`, `zeitplan`, `stop`, `setup`, `report`) beim Start automatisch bei den Telegram-Servern. Die Schaltfläche unten links neben dem Eingabefeld wird als „Menü“ konfiguriert, das diese Befehle direkt auflistet.
2. **Interaktive Zeitplan-Steuerung**: Der `/zeitplan`-Befehl listet alle Zeitpläne mit einem interaktiven Inline-Keyboard auf. Jeder Zeitplan verfügt direkt über einen Status-Toggle-Button (mit farbigen Punkten `🟢`/`🔴` für aktiv/inaktiv) und einen Lösch-Button (`🗑️`). Der Benutzer muss keine IDs mehr eingeben.
3. **Globale Bestätigung über Reply-Keyboards**: Alle Aktionen, die eine explizite Bestätigung erfordern (Zeitplan löschen, neuen Zeitplan im Wizard speichern, Ventil-Kopplung überschreiben), nutzen einheitliche Reply-Keyboards (`[ ✅ Ja ... ]` / `[ ❌ Abbrechen ]`) anstelle von Inline-Buttons. Dies verhindert Fehleingaben und vereinheitlicht den UX-Ablauf.

## User Stories

1. Als Benutzer des Telegram-Bots möchte ich einen Menü-Button neben dem Eingabefeld haben, damit ich die wichtigsten Steuerbefehle direkt sehen und anklicken kann, ohne sie tippen zu müssen.
2. Als Benutzer des Telegram-Bots möchte ich beim Starten des Daemons auch dann keine Abstürze erleben, wenn die Steuerzentrale offline ist und die Telegram-Menüregistrierung fehlschlägt.
3. Als Benutzer des Telegram-Bots möchte ich meine Zeitpläne unter `/zeitplan` übersichtlich aufgelistet sehen und den Aktivierungsstatus durch einen einfachen Klick auf ein Inline-Button umschalten können, damit die Verwaltung schneller geht.
4. Als Benutzer des Telegram-Bots möchte ich einen Lösch-Button (`🗑️`) neben jedem Zeitplan haben, um den Löschvorgang mit einem Klick zu starten.
5. Als Benutzer des Telegram-Bots möchte ich beim Löschen eines Zeitplans um Bestätigung gebeten werden, damit ich nicht versehentlich wichtige Bewässerungszeiten entferne.
6. Als Benutzer des Telegram-Bots möchte ich, dass Bestätigungsdialoge (Löschen, Wizard-Speichern, Re-Pairing) einheitlich als Reply-Tastatur am unteren Bildschirmrand erscheinen, damit die Auswahl klar abgegrenzt ist und versehentliche Klicks auf alte Nachrichten-Buttons verhindert werden.

## Implementierungs-Entscheidungen (Implementation Decisions)

- **Menü-Registrierung auf Startup**:
  - Der Bot ruft beim Starten die Telegram-Methoden `/setMyCommands` und `/setChatMenuButton` (Typ `commands`) auf.
  - Diese API-Aufrufe werden in einen Try-Catch-Block gekapselt. Wenn die Internetverbindung der Steuerzentrale offline ist, wird die Fehlermeldung als Warnung geloggt und der Daemon startet normal weiter (Option A).
  
- **Interaktives Zeitplan-Menü**:
  - Unter `/zeitplan` wird neben jedem Eintrag ein Zeilen-Tastenfeld generiert:
    - Button 1: Toggles Status (`🟢 Name (Startzeit)` / `🔴 Name (Startzeit)`) – Triggert Callback `sched_toggle_<id>`.
    - Button 2: Löschen (`🗑️`) – Triggert Callback `sched_delete_ask_<id>`.
  - Der Wizard-Button (`➕ Neuer Zeitplan`) bleibt als Header erhalten.

- **Statusbasierte Deletion-Confirmation**:
  - Wir führen einen Sitzungsspeicher `delete_states` für ausstehende Löschvorgänge im UI-Controller ein.
  - Wenn `sched_delete_ask_<id>` ausgelöst wird, wird die ID in `delete_states` abgelegt und ein Reply-Keyboard mit `[ ✅ Ja, löschen ]` und `[ ❌ Nein, abbrechen ]` gesendet.
  - In der Nachrichtenverarbeitung wird bei bestehendem Lösch-Status die Antwort ausgewertet, die Aktion in der Datenbank ausgeführt (oder abgebrochen) und der Zustand gelöscht. Danach wird das Hauptmenü-Keyboard wiederhergestellt.

- **Refactoring bestehender Bestätigungen**:
  - **Kopplungsbestätigung (`/setup`)**: Falls bereits ein Ventil gekoppelt ist, fordert der Bot die Bestätigung über ein Reply-Keyboard (`[ ✅ Ja, neu koppeln ]` und `[ ❌ Abbrechen ]`) anstatt über ein Inline-Keyboard an.
  - **Wizard-Speichern**: Am Ende des geführten Zeitplan-Assistenten wird die Bestätigungsfrage mit einem Reply-Keyboard (`[ ✅ Speichern ]` und `[ ❌ Abbrechen ]`) gesendet.

## Test-Entscheidungen (Testing Decisions)

- **Test-Nahtstellen (Seams)**:
  - Wir nutzen das Interface-Routing-Callback `telegram_ui.on_telegram_update(msg_obj, cb_obj)`. Da der `telegram_client` per Dependency Injection / Callbacks an das UI-Modul gekoppelt ist, können wir den Client mocken.
  - Wir erstellen eine dedizierte Testklasse `TestTelegramUI` in `tests/test_telegram_ui.py`.
  - Die Tests mocken `telegram_client.send_message`, `edit_message_text` und `answer_callback_query` und rufen direkt `on_telegram_update` auf, um die Reaktionen des UI-Controllers bei Button-Klicks und Bestätigungen zu verifizieren.
- **Testabdeckung**:
  - Test des Toggle-Inline-Buttons (ändert Status in DB, aktualisiert Nachricht).
  - Test der Lösch-Bestätigung (setzt Deletion-State, sendet Reply-Keyboard, führt Löschung bei "Ja" aus, bricht bei "Nein" ab).
  - Test der Re-Pairing-Bestätigung.
  - Test des Wizard-Abschlusses mit Reply-Keyboard-Bestätigung.

## Nicht im Leistungsumfang (Out of Scope)

- Anpassung der eigentlichen Bewässerungslogik oder des Schedulers.
- Unterstützung für Web-Apps oder andere Bot-Menüknöpfe außer dem Befehlsmenü (`commands`).
- Übersetzung der Benutzeroberfläche in andere Sprachen (bleibt rein Deutsch).

## Weitere Anmerkungen (Further Notes)

- Der klassische Befehlssatz (`/add`, `/delete`, `/toggle`) wird im Code als Fallback beibehalten, jedoch aus allen Hilfetexten und Beschreibungen entfernt, um den Benutzer vollständig auf die interaktive Benutzeroberfläche zu lenken.
