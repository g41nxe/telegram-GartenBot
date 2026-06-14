"""
Global test-session guard against outbound Telegram HTTP calls.

Python imports this file before any module in the tests/ package (including
subdirectories), so the patches below are active for every test regardless of
execution order or which test class a test inherits from.

Primary defense — architectural (telegram_ui.py):
    Event handlers are registered only via telegram_ui.subscribe_event_handlers(),
    which is called exclusively by main.py. Tests never call it, so the handlers
    are never wired to _global_bus and no Telegram messages can be triggered by
    domain events (WateringCycleStarted, WateringSkipped, InactivityAlert*, etc.).

Secondary defense — token guard (this file):
    config.TELEGRAM_BOT_TOKEN is blanked out so send_message() and send_photo()
    short-circuit before making any HTTP call. This catches any remaining path
    that might reach telegram_client functions directly (e.g. command handlers
    invoked by test_telegram_ui.py via _process_message).

    Tests that need a token (test_telegram_client.py) override this per-test
    with @patch.object(config, "TELEGRAM_BOT_TOKEN", "123:FAKE") — nested patches
    take precedence over this session-wide patch.

Individual test methods that need to assert what was sent should apply their own
@patch("daemon.ui.telegram_ui.telegram_client") to get an inspectable mock object.
"""

import sys
from pathlib import Path
from unittest.mock import patch

# src/ must be on sys.path before we can import daemon modules.
# Individual test files do this themselves, but __init__.py runs first.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Blank out the bot token — send_message() and send_photo() guard-return on
# empty token without making any HTTP call.
from daemon import config as _config
patch.object(_config, "TELEGRAM_BOT_TOKEN", "").start()

# Block the background long-poll thread from starting.
patch("daemon.ui.telegram_client.start_polling").start()
