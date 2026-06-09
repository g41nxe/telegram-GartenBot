# Implementation Plan: Telegram Menu Button & Interactive Schedule Management

This plan outlines the design and files to be modified to implement a Telegram Commands Menu Button on startup, interactive inline keyboards for schedules (with toggle/delete buttons), and globally unified Reply Keyboards for confirmations (schedule wizard, re-pairing, and schedule deletion).

## Design Rules & Decisions

- **Confirmations:** All confirmations (deleting schedules, saving a newly created schedule, and confirming re-pairing) must use **Reply Keyboards** (bottom of screen menu replacements) rather than Inline Keyboards (buttons directly under messages) to ensure a consistent, deliberate confirmation flow.
- **Error Handling:** Attempt to update the menu button and commands list when the bot starts up. If it fails due to network issues, catch the exception, log a warning, and continue running (the commands/menu will simply be updated next time the bot starts with a working connection).
- **Architecture Documentation:** A new ADR `0013-telegram-confirmation-keyboards.md` will be created to document the decision to use Reply Keyboards for confirmations.

---

## Proposed Changes

### Documentation (ADRs)

#### [NEW] [0013-telegram-confirmation-keyboards.md](file:///d:/Projects/Repositories/telegram-GartenBot/docs/adr/0013-telegram-confirmation-keyboards.md)
- Define the architectural decision to use Reply Keyboards for all user confirmations (deleting schedules, saving a newly created schedule, and confirming re-pairing).

### Telegram UI and Client

#### [MODIFY] [telegram_client.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/ui/telegram_client.py)
- Implement `set_bot_commands()` using Telegram's API `/setMyCommands` to register the following commands:
  - `status` - Zeigt aktuellen System-Status & Zyklen
  - `zeitplan` - Zeigt aktuelle Zeitpläne & Assistent
  - `stop` - Stoppt Bewässerung sofort
  - `setup` - Startet die Ventil-Kopplung
  - `report` - Generiert den täglichen Statusbericht
- Implement `set_bot_menu_button()` using Telegram's API `/setChatMenuButton` to configure the menu button to show commands (`commands`).
- Wrap startup API calls in `try...except` block, logging a warning on network failure, so the daemon starts up cleanly even if offline.

#### [MODIFY] [telegram_bot.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/ui/telegram_bot.py)
- Call `telegram_client.set_bot_commands()` and `telegram_client.set_bot_menu_button()` inside `start_bot()`.

#### [MODIFY] [telegram_ui.py](file:///d:/Projects/Repositories/telegram-GartenBot/src/daemon/ui/telegram_ui.py)
- Add a new dictionary `delete_states = {}` for keeping track of pending schedule deletions.
- Update `handle_schedules` to render the list of schedules. In addition to the `[ ➕ Neuer Zeitplan ]` button, generate an inline keyboard row for each configured schedule containing:
  - Toggle button: `[ 🟢 Name (Uhrzeit) ]` or `[ 🔴 Name (Uhrzeit) ]` that toggles the schedule immediately on click.
  - Delete button: `[ 🗑️ ]` that initiates the confirmation flow.
- Add handler in `_process_callback_query` for schedule toggling (`sched_toggle_<id>`) and schedule delete initiation (`sched_delete_ask_<id>`).
- Implement the confirmation keyboard flow for deletions using a Reply Keyboard:
  - When `sched_delete_ask_<id>` is clicked, store `{"schedule_id": id, "name": name}` in `delete_states` and send the message with a reply keyboard containing `[ ✅ Ja, löschen ]` and `[ ❌ Nein, abbrechen ]`.
- Update `_process_message` to handle:
  - Deletion confirmations ("✅ Ja, löschen" / "❌ Nein, abbrechen") when a session is active in `delete_states`.
- Refactor existing confirmations to use Reply Keyboards instead of Inline Keyboards:
  - **Re-pairing confirmation (`setup_confirm`):** Update the confirmation message in `handle_setup` to use a reply keyboard with `[ ✅ Ja, neu koppeln ]` and `[ ❌ Abbrechen ]` instead of inline buttons.
  - **Wizard saving confirmation (`wiz_confirm_save`):** Update step 7 of the wizard to ask for confirmation using a reply keyboard with `[ ✅ Speichern ]` and `[ ❌ Abbrechen ]`.

---

## Verification Plan

### Automated Tests
- Run `python -m unittest tests/test_irrigation.py` to ensure existing tests still pass.
- Write a new test file `tests/test_telegram_ui.py` to test the UI callback logic (`on_telegram_update`) with mocked messages/callbacks.

### Manual Verification
1. Run the daemon locally in simulation mode.
2. Verify that `setMyCommands` and `setChatMenuButton` API endpoints are called.
3. Open a Telegram client and verify:
   - The menu button is present and lists the registered commands.
   - Sending `/zeitplan` renders the list of schedules with toggle (`🟢`/`🔴`) and delete (`🗑️`) inline buttons.
   - Clicking toggle updates the schedule state immediately.
   - Clicking delete shows a confirmation request with the Reply Keyboard `[ ✅ Ja, löschen ]` / `[ ❌ Nein, abbrechen ]`. Confirming/cancelling restores the main menu.
   - Creating a new schedule (wizard) asks for saving confirmation using the Reply Keyboard `[ ✅ Speichern ]` / `[ ❌ Abbrechen ]`.
   - Running `/setup` when a valve is already paired asks for confirmation using `[ ✅ Ja, neu koppeln ]` / `[ ❌ Abbrechen ]` via Reply Keyboard.
