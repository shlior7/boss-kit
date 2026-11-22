---
name: status
description: The boss's status: what needs you, the stack and the workers, in plain words. Use in a boss session when the user says /boss:status or asks for status without the pane open.
---

# Status

1. Run `python3 "${BOSS_KIT_HOME:-<this skill's base directory>/../..}/bin/bosskit.py" buttons get "Status"` from this session's working directory. It prints the prompt the boss pane's **Status** button sends, with this boss's overrides (`deck_prompts`) applied.
2. If it exits non-zero, reply with its message exactly (outside a boss session: "Not a boss here: run /boss to set one up.") and stop.
3. Otherwise do what the printed prompt says, as if the user had typed it. Every gate in the boss prompt still holds.
