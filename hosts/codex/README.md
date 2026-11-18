# Codex host

This host runs each worker as a detached `codex exec` process in a new local git worktree. It is deliberately process-based: it never adopts, types into, restarts, or closes an existing interactive Codex session.

Requirements: `codex` on `PATH`, an authenticated Codex CLI, and a committed base branch (Git needs a commit before it can create a worktree).

Set the project host to `codex`, then dispatch through `bin/boss-host create`. Worker records and logs live under `$BOSS_HOME/<project>/native-workers/codex/`; worktrees default to `$BOSS_HOME/<project>/worktrees/codex/`. Set `hosts.codex.worktrees_dir` when they belong elsewhere.

`boss-host send` queues a follow-up only after the worker's own JSON stream publishes its thread id. `archive` refuses while the process is running and never deletes a worktree. Review the normal leftover check before removing one yourself.
