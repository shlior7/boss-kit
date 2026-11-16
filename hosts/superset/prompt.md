# Host commands: Paradev (Superset) CLI

Your host is Paradev (formerly Superset), CLI 2.x. A worker is a **workspace**: a git worktree with terminals; its agent runs in one of them. This session's id is `$SUPERSET_WORKSPACE_ID`. Use `bin/boss-host` for everything it covers; it runs the commands below for you.

## What boss-host does here
- `boss-host create` runs `superset workspaces create --local --project <the project whose repo matches> --branch <b> --agent claude --prompt ... [--tag <folder>]`. A domain boss's new workspace also needs `--base-branch origin/<main>`: create it by hand (below), and since `workspaces create` has ignored `--base-branch` before, check the new worktree as section 15 says.
- `boss-host send` clears the input line first (`--keys ctrl+u`: an idle session often shows an auto-suggestion that is not yours), then submits. Text sent while the worker is mid-turn can be dropped when it goes idle: check its screen after it finishes and resend if needed.
- `boss-host watch <workspace> <branch>` runs this host's screen watcher: every 20 s it reads the agent terminal, strips the reply box and side pane, and fires on a new envelope, PR READY, agent state `blocked`, 9 idle polls (3 min) on an unchanged screen (135 while a background shell or monitor runs), or a gone terminal. Never replace it with `superset terminals wait --match`: that sees only the last `--max-lines` rows and misses an envelope split over two lines. `terminals read` returns only the visible screen (about 64 rows). On a fire without an envelope, read the screen and GitHub first. On resume after a restart, read each worker's screen for an envelope that landed meanwhile, then re-arm.
- `boss-host close <workspace> <terminal>...` closes the PANE (`superset panes close`), which ends its terminal and leaves no "Session ended" tab; never a bare `superset terminals close`. `boss-host close-dead <workspace>...` removes tabs whose session already ended.
- `boss-host archive <id>` runs `superset workspaces archive <id> --local`, which removes the worktree folder (the branch stays on GitHub).
- Folders are workspace tags (`boss-host move <id> <tag>`).

## Superset commands boss-host does not cover
- `superset workspaces list --local --json`; `superset terminals list --workspace <id>`; `superset terminals read --workspace <id> --terminal <t> --max-lines N`. Use the FULL terminal UUID, never the short id. `superset snapshot --host <id> --json` shows every worker's state in one call.
- A session in an existing workspace (research, ops, reviews, checks; in the boss's own workspace when it changes no files): `superset agents create --workspace <id> --agent claude --model <m> --prompt "..." --json` (keep `sessionId`). Presets: claude (default), codex, gemini, antigravity/agy, amp, copilot, opencode (`superset agents list --local --json`). Drive codex as a terminal agent.
- New agents start in the user's default permission mode; a permission prompt reads as agent state `blocked`. Answer a read-only command prompt with the option that stops asking in the mode the user runs (auto, or bypass when that is their default); anything that writes, ask me.
- Pages: `superset pages publish scratch/pages/<f>.html --title ... --description ...` (self-contained HTML, no remote scripts/fetch/eval).

## Completion: the envelope on the worker's screen
Every dispatched prompt ends with: "End your final message with exactly this envelope, each field on its own line starting at column 0. On the PR, post one short plain-English status comment (what changed, checks, proof) ending with the line `<!-- BOSS_WORKER_DONE task: <id> -->`; never the envelope." The watcher reads it from the screen.
