# boss-deck

A quiet, read-only Claude Code pane for a boss session. It shows:

- **review ↗ <date>**: the latest review page, from `state/<project>/review.txt`
- **now**: the boss's one next action, from `state/<project>/next.txt`
- **what needs you**: blocked workers, idle workers whose dispatch has no watcher, stale watchers, red CI, and PRs that are approved and green
- **workers**: each dispatched Paradev workspace with its current task (from the ledger) and live state. Press the name to open the workspace; press the task for a summary (state, branch, what it is doing, its last envelope, context use, watcher) and its proof links (`proof ↗ page`) from the ledger
- **pull requests**: as a stack tree, colored by status (green approved, blue waiting on a reviewer, yellow conflict, red CI, grey draft). Press the number for CI, mergeability, reviews and size, plus "open on GitHub" and its proof (`demo ↗`, `page ↗`, `artifact ↗`, found in the PR body and comments). An approved, green PR without proof reads **no proof** in yellow. PRs idle for 10+ days fold into one line
- **tracker** summary, when one is configured

It loads only in a session whose working directory has a `CLAUDE.local.md` containing `# Boss workspace`. Data comes from `bin/boss-deck-data.py` under `$BOSS_KIT_HOME` (default `~/.claude/boss-kit`). It refreshes every 60 s and right after the boss dispatches, merges or comments. `/boss-deck` opens and refreshes it.
