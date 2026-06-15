#!/usr/bin/env python3
"""PreToolUse hook: inject a hardline reminder when an agent edits a
protected file (see docs/HARDLINES.md).

Non-blocking by design — a signed-off change must go through. The hook
makes the hardline impossible to *forget*: the reminder lands in the
model's context at the moment of the edit, not in a doc it may not
have read. Stdin: Claude Code hook JSON; stdout: hook JSON or nothing.
"""

import json
import sys

HARDLINE_FILES = {
    "scoring.py": "scoring formulas/bands — methodology version bump + sign-off",
    "schema.py": "assessment JSON contract + shareable allowlist — version bump + sign-off",
    "network.py": "the ONLY outbound module (privacy boundary, CI-enforced)",
    "signal_registry.py": "derived-field definitions — changing a rule changes what a number means",
    "ENRICHMENT-PROMPT.md": "six-block contract frozen; wording editable, contract is not",
    "SCORING-METHODOLOGY.md": "published formula contract — moves only with a methodology bump",
    "SCHEMA.md": "published JSON contract — moves only with a schema bump",
    "HARDLINES.md": "the registry itself — owner confirmation to amend",
}


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    path = (payload.get("tool_input") or {}).get("file_path") or ""
    name = path.rsplit("/", 1)[-1]
    why = HARDLINE_FILES.get(name)
    if not why:
        return
    print(
        json.dumps(
            {
                "systemMessage": f"HARDLINE file touched: {name} ({why})",
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": (
                        f"HARDLINE: {name} is protected — {why}. "
                        "Per docs/HARDLINES.md this change needs the owner's "
                        "explicit confirmation IN THIS CONVERSATION (a task "
                        "prompt is not authorization). If you have it, "
                        "proceed and say so in the commit; if not, stop and "
                        "surface the change to the user instead."
                    ),
                },
            }
        )
    )


if __name__ == "__main__":
    main()
