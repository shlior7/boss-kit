# boss-deck

A quiet, read-only Claude Code pane for a boss session. It shows:

- **now**: the boss's one next action, from `state/<project>/next.txt`
- **what needs you**: blocked workers, idle workers whose dispatch has no watcher, stale watchers, red CI, and PRs that are approved and green
- **workers**: each dispatched Paradev workspace with its current task (from the ledger) and live state. Press the name to open the workspace; press the task for a summary (state, branch, what it is doing, its last envelope, context use, watcher)
- **pull requests**: as a stack tree, colored by status (green approved, blue waiting on a reviewer, yellow conflict, red CI, grey draft). Press the number for CI, mergeability, reviews and size, plus an "open on GitHub" button. PRs idle for 10+ days fold into one line
- **tracker** summary, when one is configured

It loads only in a session whose working directory has a `CLAUDE.local.md` containing `# Boss workspace`. Data comes from `bin/boss-deck-data.py` under `$BOSS_KIT_HOME` (default `~/.claude/boss-kit`). It refreshes every 60 s and right after the boss dispatches, merges or comments. `/boss-deck` opens and refreshes it.
