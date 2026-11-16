# Host commands: coderplex (`coderplex-ctl`)

Your host is coderplex. A worker is a **session**: its own git worktree, terminal and agent on one daemon. This session's id is `$CODERPLEX_SESSION_ID` (8 hex characters, what the ledger's Workspace column holds). Use `bin/boss-host` for everything it covers; it runs the commands below for you.

## What boss-host does here
- `boss-host create` runs `coderplex-ctl sessions create --target local --repo <name> --branch <b> --agent claude --prompt ... [--model] [--effort] [--name] --json`, then `sessions move --section <folder>`. Without `--access` a new session inherits this session's access mode.
- `boss-host send` runs `coderplex-ctl sessions send <id> --text ...`: it queues until the agent is idle and wakes a stopped one, so nothing is dropped mid-turn and there is no input line to clear.
- `boss-host watch <session> <branch>` checks the messages that session sends you, and fires on an envelope, PR READY, a blocked agent (any phase other than working or review), 9 idle polls (3 min) without an envelope, or a gone session. The envelope message usually reaches you first; the watcher is the safety net and the stage log.
- `boss-host archive <id>` runs `coderplex-ctl sessions archive <id>`. Never pass `--ttl` without the user's OK: it DELETES the session (worktree, branch, uncommitted work) when it runs out.
- `boss-host close` has nothing to close here: archive a finished session once the layover says so. Folders are sidebar sections (`boss-host move <id> <section>`).

## coderplex commands boss-host does not cover
- `coderplex-ctl sessions ls --json`; `coderplex-ctl sessions show <id> --json` (`agentPhase`: `working`, `review` once its turn ended); `coderplex-ctl repos ls`.
- A session that changes no files (research, ops, reviews, checks) runs as a new tab in your own session: `coderplex-ctl sessions create --target local --in-session --agent claude --name "<what it does>" --model <m> --prompt "..."`.
- Pass `--target local` to every `sessions create` (it refuses to guess when a remote workspace is reachable); messages reach sessions on the same daemon only.
- Replies come to you: a message sent to this session arrives as a new prompt once your turn ends. End your turn instead of waiting. `coderplex-ctl sessions messages --json` lists what landed (after a restart, check it before re-arming).
- Pages: none. Proof and review pages are claude.ai artifacts.
- No screen read: what a worker is doing comes from its `.boss-worker/status.json` and its messages.

## Completion: the worker sends its envelope to you
Every dispatched prompt ends with: "When done, send exactly this envelope to the boss with `coderplex-ctl sessions send <boss id> --file -` (the envelope on stdin), each field on its own line starting at column 0. On the PR, post one short plain-English status comment (what changed, checks, proof) ending with the line `<!-- BOSS_WORKER_DONE task: <id> -->`; never the envelope." Fill in this boss's id.
