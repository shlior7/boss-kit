# Codex host commands

Workers are detached `codex exec` processes in separate git worktrees. They are not existing interactive Codex sessions.

- Create only through `bin/boss-host create`; it records the process, log and worktree before returning its id.
- `bin/boss-host workers` reports **working** while the process is alive and **idle** once it exits. Read its log at `$BOSS_HOME/<project>/native-workers/codex/<id>.log` if the completion envelope is missing.
- `bin/boss-host send <id> --text ...` uses `codex queue` only after Codex has published that worker's thread id. It never guesses an id or injects input into another session.
- `bin/boss-host archive <id>` refuses while the process is live and never deletes its worktree. Review and remove a finished worktree yourself after the normal leftover check.
- Put `BOSS_WORKER_DONE` or `BOSS_WORKER_BLOCKED` in the worker's final response as usual. The standard watcher also checks the branch's PR.
