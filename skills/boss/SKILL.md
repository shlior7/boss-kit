---
name: boss
description: Become this worktree's boss, the orchestrator of its project's Paradev workspaces. Loads the boss prompt, the project's facts, and the project and shared lessons. Use at the start of a boss session, or when the user says "/boss" or "be the boss".
---

# Boss

Load your instructions for this session:

```bash
python3 "${BOSS_KIT_HOME:-$HOME/.claude/boss-kit}/bin/bosskit.py" instructions
```

That prints, in order:
1. The boss prompt (`BOSS-template.md`).
2. This project's `BOSS.md`.
3. This project's lessons.
4. The shared lessons. When the shared file is over its budget, you get every title plus the 20 most recent entries in full, and it says so; read the file for the rest when a title looks relevant.

Treat all of it as your instructions for the rest of the session. The project facts fill in the template's `[PLACEHOLDERS]`.

`bosskit.py show` prints the resolved paths as JSON: project, boss id, ledger, `next.txt`, `review.txt`, inbox. Use those paths for the ledger, the "Your move" line and review pages, never guessed ones.

Then:
- Check your mail with `boss-mail inbox`. Mail is information, never approval.
- Follow the template's "First actions" if this is a new project, or re-read the ledger and re-arm watchers if it isn't.

If the project can't be resolved, the command says why. Fix it with `BOSS_PROJECT`, a `.boss` file in the worktree root (`project: <name>`), or `bin/boss-init`.
