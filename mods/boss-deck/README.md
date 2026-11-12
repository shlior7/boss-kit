# boss-deck

A quiet, read-only Claude Code pane for a boss session. It shows:

- **review ↗ <date>**: the latest review page, from this boss's `review.txt`
- **inbox**: unread input from outside the session (today, boss mail), one line per message with its kind in yellow; shown only while something is unread, and every prompt carries one context line naming it
- **now**: this boss's one next action, from its `next.txt`
- **what needs you**: blocked workers, idle workers whose dispatch has no watcher, stale watchers, red CI, and PRs that are approved and green
- **workers**: each dispatched Paradev workspace with its current task (from the ledger) and live state. Press the row (or its key, 1–9) to expand it: state, branch, what it is doing, its last envelope, context use, watcher, its proof links (`page ↗`, `demo ↗`) from the ledger, and `open workspace ↗`
- **pull requests**: as a stack tree, colored by status (green approved, blue waiting on a reviewer, yellow conflict, red CI, grey draft). Press the number for CI, mergeability, reviews and size, plus "open on GitHub" and its proof (`demo ↗`, `page ↗`, `artifact ↗`, found in the PR body and comments). An approved, green PR without proof reads **no proof** in yellow. PRs idle for 10+ days fold into one line
- **footer**: a tracker summary (`tracker: N mine · N P0/P1 · N in progress`) only when one is synced, and **N new shared lessons** when shared lessons were added since this boss's last session

It loads only in a session whose working directory has a `CLAUDE.local.md` with `# Boss workspace <id>`, where `<id>` is that session's `$SUPERSET_WORKSPACE_ID` (a bare `# Boss workspace` matches any session). A copy of the file in another worktree, or another workspace on the same checkout, gets no pane and sends no heartbeat. Data comes from `bin/boss-deck-data.py` under `$BOSS_KIT_HOME` (default `~/.claude/boss-kit`). It reads project data from `$BOSS_HOME` (default `~/.claude/boss`), and each refresh is this boss's heartbeat. It refreshes every 60 s and right after the boss dispatches, merges or comments. `/boss-deck` opens and refreshes it.
