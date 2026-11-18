# AGY host

This host runs each worker as a detached `agy --print` process in a new local git worktree. It never touches another AGY conversation or sends keystrokes to a live worker.

Requirements: `agy` on `PATH`, an authenticated AGY CLI, and a committed base branch.

Set the project host to `agy`, then create workers with `bin/boss-host create`. Records and logs are in `$BOSS_HOME/<project>/native-workers/agy/`; worktrees default to `$BOSS_HOME/<project>/worktrees/agy/`. Override the location with `hosts.agy.worktrees_dir`.

AGY has no queued-message command, so the adapter refuses `boss-host send` for a live worker. Wait for it to finish and create a follow-up worker when needed. `archive` also refuses while a process is running and never deletes a worktree.
