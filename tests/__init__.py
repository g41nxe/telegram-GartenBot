"""
Global test-session guard against outbound Telegram HTTP calls.

Python imports this file before any module in the tests/ package (including
subdirectories), so the patches below are active for every test regardless of
execution order or which test class a test inherits from.

Individual test methods that need to inspect what was sent (e.g. assert_called_with)
should still apply their own @patch("daemon.ui.telegram_ui.telegram_client") decorator
to get a fresh mock object they can introspect — that decorator just replaces the
module reference inside telegram_ui's namespace, and the global safety-net patches
here remain as a fallback for anything that bypasses that.
"""

import sys
from pathlib import Path
from unittest.mock import patch

# src/ must be on sys.path before we can import daemon.ui.telegram_client.
# Individual test files do this themselves, but __init__.py runs first.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Only patch the two functions that event handlers call directly:
#   - broadcast_notification: called by all telegram_ui event handlers
#     (inactivity watchdog, watering events, daily report, etc.)
#   - start_polling: prevents the background long-poll thread from starting
#
# send_message / send_photo / edit_message_text / answer_callback_query are
# NOT patched here because:
#   a) they are only reachable through broadcast_notification (already mocked)
#      or through command handlers in telegram_ui
#   b) test_telegram_ui.py patches daemon.ui.telegram_ui.telegram_client at the
#      module-reference level for every test that calls _process_message(), so
#      command-handler paths are also covered
#   c) test_telegram_client.py tests the real send_photo/send_message logic and
#      must not have those functions globally replaced by mocks
for _fn in ("broadcast_notification", "start_polling"):
    patch(f"daemon.ui.telegram_client.{_fn}").start()
