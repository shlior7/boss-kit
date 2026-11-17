# Status layover (BOSS-template.md section 8)

The steps of the sweep section 8 requires. The rules stay in the template; where this file and the template differ, the template wins. Read it before every sweep: at every status report, at every DONE, after every merge, and before the session ends.

1. **Inventory** every workspace and live session of the project (`boss-host workers`), mapped to branch, PR state, owner (the ledger dispatch row's Boss column), dirty files, commits ahead of origin, and any dev server, DB or container it runs.
2. **Ask** each one you own with `bin/boss-status-ask <workspace> [<terminal>] ...` (the six questions; the template has them) and read the six-line answers before deciding. A PR being merged, or a tree looking clean, does not replace the answer (the boss once kept a done workspace because it had no PR).
3. **Decide each row**: ARCHIVE, CLOSE TERMINAL ONLY, KEEP (say why and what ends it: task, PR, decision), or ASK the user (the template lists when each holds).
   Where the host has nothing to close it says so: archive instead.
4. **Show the table** (its columns are in the template). Idle sessions that are not needed are closed, not left to pile up. One line closes the report: `cleanup: archived N, closed M terminals, kept K (why)`.
5. **Consolidate before creating**: one workspace per PR or stack; minor changes join the workspace that owns the area as a new session, not a new worktree. A sweep that finds two workspaces for one concern merges them into the owner and retires the other.
6. The layover is part of the report, not an extra: if the user has to ask "what are all these workspaces", the sweep failed (section 0 incident).
