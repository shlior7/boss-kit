# boss-deck

A quiet, read-only Claude Code pane for a boss session. It shows:

- **review ↗ <date>**: the latest review page, from this boss's `review.txt`
- **inbox**: unread input from outside the session (today, boss mail), one line per message with its kind in yellow; shown only while something is unread, and every prompt carries one context line naming it
- **now**: this boss's one next action, from its `next.txt`
- **what needs you**: blocked workers, idle workers whose dispatch has no watcher, stale watchers, red CI, and PRs that are approved and green
- **lanes**: each dispatched Paradev workspace by whose move it is, its PR joined by branch: YOUR MOVE (PR approved + green), BOSS CHECKING (a DONE not yet verified, or a ready PR gone red), WORKING (working, blocked, or idle without a DONE), IN REVIEW (PR ready), DONE TODAY (merged or retired today, at most 5). Empty lanes are hidden; time in stage comes from the boss's `events.jsonl` (`bin/boss-event`). Press the row (or its key, 1–9) to expand it: its timed stage history, the next step, what it is doing, context use, its proof links (`page ↗`, `demo ↗`) from the ledger, and `open workspace ↗`
- **pull requests**: the ones no workspace owns, as a stack tree, colored by status (green approved, blue waiting on a reviewer, yellow conflict, red CI, grey draft). Press the number for CI, mergeability, reviews and size, plus "open on GitHub" and its proof (`demo ↗`, `page ↗`, `artifact ↗`, found in the PR body and comments). An approved, green PR without proof reads **no proof** in yellow. PRs idle for 10+ days fold into one line
- **footer**: a tracker summary (`tracker: N mine · N P0/P1 · N in progress`) only when one is synced, and **N new shared lessons** when shared lessons were added since this boss's last session

It loads only in a session whose working directory has a `CLAUDE.local.md` with `# Boss workspace <id>`, where `<id>` is that session's `$SUPERSET_WORKSPACE_ID` (a bare `# Boss workspace` matches any session). A copy of the file in another worktree, or another workspace on the same checkout, gets no pane and sends no heartbeat. Data comes from `bin/boss-deck-data.py` under `$BOSS_KIT_HOME` (default `~/.claude/boss-kit`). It reads project data from `$BOSS_HOME` (default `~/.claude/boss`), and each refresh is this boss's heartbeat. It refreshes every 60 s and right after the boss dispatches, merges or comments. `/boss-deck` opens and refreshes it.
