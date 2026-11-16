# Host commands: coderplex (`coderplex-ctl`)

Loaded after the boss prompt when this boss's host is `coderplex` (`bosskit.py show` prints `host`). A worker is a coderplex session: its own git worktree, terminal and agent on one daemon. This boss's id is `$CODERPLEX_SESSION_ID` (8 hex characters, what the ledger's Workspace column holds). Add `--json` to any command to parse it. Pass `--target local` to `sessions create` whenever a remote Coder workspace is also reachable (it refuses to guess), and keep workers on the boss's daemon: messages reach sessions on the same daemon only.

## Control surface
- List: `coderplex-ctl sessions ls --json` (`id, title, branch, repo, agent, live, status`); one in detail: `coderplex-ctl sessions show <id> --json` → `.sessions[0]` with `agentPhase` (`working` while it works, `review` once its turn ended), `liveStatus`, `branch`, `worktree`, `link`. `coderplex-ctl repos ls` lists the repos a worker can start from.
- New worker (a new worktree, only for real code changes that become a PR): `coderplex-ctl sessions create --target local --repo <repo> --branch <branch> --prompt "$(cat <prompt file>)" --model <m> [--effort low|medium|high|xhigh] [--access auto] --json` (keep `id`). Without `--access` it inherits this session's access mode; a permission prompt shows as a phase other than `working` and the watcher reports it as blocked.
- A session that changes no files (research, ops, reviews, checks) runs as a new tab in the boss's own session: `coderplex-ctl sessions create --target local --in-session --agent claude --name "<what it does>" --model <m> --prompt "..."`.
- Message a worker: `coderplex-ctl sessions send <id> --text "..."` or `--file <path>` (`--tab <tabId>` for one tab, `--re <messageId>` to reply in a thread). It queues until the agent is idle and wakes a stopped one: no input line to clear, nothing dropped mid-turn. The boss-deck pane logs each `sessions send --text` as that worker's `msg` event, for its FROM BOSS.
- Replies come to you: a message a worker sends this session arrives as a new prompt in your pane once your turn ends. End your turn instead of waiting; `coderplex-ctl sessions messages [<id>] --json` lists the history (use it after a restart to see what landed).
- Name and group: `coderplex-ctl sessions rename <id> --name "<what it does now>"`; folders are sidebar sections: `coderplex-ctl sessions move <id> --section "<group>"` (a new name creates the section). A domain boss's folder is a section.
- Archive a finished worker: `coderplex-ctl sessions archive <id>`. Never pass `--ttl` without the user's OK: it DELETES the session (worktree, branch, uncommitted work) when it runs out.
- Status layover inventory: `coderplex-ctl sessions ls --json`. The status check: `bin/boss-status-ask <session> - ...` (`-`: no terminal id on coderplex). There are no panes to close: a done session is archived (above) once the layover says so.
- Pages: coderplex has none. Proof and review pages are claude.ai artifacts (self-contained HTML).
- Open a session for the user: `open coderplex://session/local/<id>`.
- Limits: no screen read (what a worker is doing comes from its `.boss-worker/status.json` and its messages); messages reach sessions on the same daemon only.

## Completion: the worker sends its envelope to you
Every dispatched prompt ends with: "When done, send exactly this envelope to the boss with `coderplex-ctl sessions send <boss id> --file -` (the envelope on stdin), and post the same envelope as a PR comment." Fill in this boss's id. The message wakes you; verify as section 7 says.

## Watcher
In the SAME turn as the dispatch, arm `bin/boss-watch-msg <session> <branch>` in the background (`run_in_background`, never `&`, run from the repo; always pass the worker's branch). Every 20 s it checks the messages from that session to you, and fires when one holds an envelope (logging DONE or BLOCKED), when the branch's PR gets a DONE comment, leaves draft or merges (PR READY), when the agent waits on someone (blocked), after 9 idle polls (3 min) without an envelope, or when the session is gone. Timeout ~3 h. The envelope message usually reaches you first; the watcher is the safety net and the stage log. A session restart kills every watcher: on resume, run `coderplex-ctl sessions messages --json` for envelopes that landed meanwhile, then re-arm.
