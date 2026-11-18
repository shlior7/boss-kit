# AGY host commands

Workers are detached `agy --print` processes in separate git worktrees. They are not existing AGY conversations.

- Create only with `bin/boss-host create`; it creates a branch/worktree, records the process and starts AGY without touching another session.
- `bin/boss-host workers` shows **working** while the process is alive, then **idle**. Its output is in `$BOSS_HOME/<project>/native-workers/agy/<id>.log`.
- AGY currently has no queued-message command, so never attempt to interrupt or type into a running worker. Wait for completion, then start a follow-up worker when needed.
- `bin/boss-host archive <id>` refuses while it is live and never deletes the worktree.
- Workers finish with the standard `BOSS_WORKER_DONE` or `BOSS_WORKER_BLOCKED` envelope. The normal watcher also verifies a PR on the branch.
