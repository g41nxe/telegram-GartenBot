#!/usr/bin/env python3
"""Claude-Code-Hook (PreToolUse): warnt vor ASCII-transliterierten deutschen Umlauten
(ae/oe/ue statt ä/ö/ü, vereinzelt ss statt ß) in Bash-Befehlen, Edit- und Write-Inhalten.

Liest das Hook-JSON von stdin (siehe https://docs.claude.com/en/docs/claude-code/hooks).
Grund: Doku allein (docs/agents/encoding.md) hat das wiederkehrende Problem nicht
verhindert -- siehe [[feedback-german-umlaut-encoding]] im Agent-Gedächtnis.

Kein Treffer: kein Output, Exit 0, Tool-Aufruf läuft normal weiter.
Treffer: JSON mit hookSpecificOutput.permissionDecision="deny" auf stdout, Exit 0 -- das
aktuelle PreToolUse-Blockierschema (das ältere reine decision:"block" gilt dafür als veraltet).
"""
import json
import re
import sys
from pathlib import Path

WORDLIST_PATH = Path(__file__).parent / "umlaut_wordlist.txt"


def load_wordlist() -> list[str]:
    if not WORDLIST_PATH.exists():
        return []
    fragments = []
    for line in WORDLIST_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            fragments.append(line)
    return fragments


def extract_text(tool_name: str, tool_input: dict) -> str:
    if tool_name in ("Bash", "PowerShell"):
        return tool_input.get("command", "")
    if tool_name == "Edit":
        return tool_input.get("new_string", "")
    if tool_name == "Write":
        return tool_input.get("content", "")
    return ""


def find_hits(text: str, fragments: list[str]) -> list[str]:
    lowered = text.lower()
    return [f for f in fragments if re.search(re.escape(f), lowered)]


def main() -> int:
    # Windows' Konsolen-Codepage ist nicht UTF-8 -- ohne das hier crasht/mangelt print() mit
    # Umlauten im Output selbst (siehe docs/agents/encoding.md, "Python print()"-Fußnote).
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    text = extract_text(tool_name, tool_input)
    if not text:
        return 0

    hits = find_hits(text, load_wordlist())
    if not hits:
        return 0

    unique_hits = sorted(set(hits))
    reason = (
        "Mögliche ASCII-transliterierte deutsche Umlaute gefunden: "
        + ", ".join(f'"{h}"' for h in unique_hits)
        + ". Bitte prüfen und echte UTF-8-Umlaute verwenden (ä/ö/ü/ß) statt ae/oe/ue/ss. "
        + "Falscher Treffer (z. B. echtes englisches Wort)? scripts/umlaut_wordlist.txt anpassen."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
