# Host plugin: superset

Paradev (formerly Superset) CLI 2.x. A worker is a **workspace**: a git worktree with terminals; its agent runs in one of them. Signed in: `superset hosts list --json` answers.

| | |
|---|---|
| This session's id | `$SUPERSET_WORKSPACE_ID` (its terminal: `$SUPERSET_TERMINAL_ID`) |
| CLI | `superset` on PATH, or `~/.superset/bin/superset` |
| Messages | `terminals send`; the plugin clears the input line (`--keys ctrl+u`) first. Text sent mid-turn can be dropped, so mail wakes only an idle terminal |
| Envelope | on the worker's screen; `watch.sh` reads it. `SUPERSET_WORKER_DONE` / `_BLOCKED`, the older token, still counts for this host |
| Folders | workspace tags |
| Pages | Superset pages (`superset pages publish`); proof links `https://app.superset.sh/page/…` |
| Closing | `boss-host close` closes the pane, so no "Session ended" tab stays; `close-dead` sweeps tabs whose session ended |

Config, under `hosts.superset`: `host_id` (the host's machine id; empty = `$BOSS_HOST`, else your first host; the older top-level `superset_host` still counts), `project` (the Paradev project new workspaces go in; empty = the one whose repo matches).

## The watcher (`watch.sh`)

`boss-host watch <workspace> <branch> [--task <id>]` runs it (`--task`: another task's envelope never fires; the transcript read is the agent's own session, else the worktree's newest with a stderr line). Every 20 s, for up to 3 h, it reads the terminal, strips Claude Code's reply box and the side pane, and exits (waking the boss) when:
- a **new** envelope appears, on one line or split over two, counted only when the token is directly followed by `task: <id>`, compared by `task:` and summary, skipping `<placeholder>` templates and the boss's own message box. When the screen shows none, it reads the worker's last replies from its Claude Code transcript (`~/.claude/projects/<worktree path>/`), since a pane is often 32 rows and a tall envelope's first line never reaches it;
- with a branch, a PR on it gets a DONE comment, leaves draft or merges (`PR READY #n`), whatever the screen shows;
- the agent's state becomes `blocked`;
- the agent sits idle on an unchanged screen (digits ignored: a status-line clock ticks every minute) for 9 polls (3 min), or 135 (45 min) while a background shell or monitor shows;
- the terminal is gone.

Never swap it for `superset terminals wait --match`: a one-line regex misses an envelope drawn above a short read window or split over two lines, `terminals read` returns only the visible screen, and it has no idle fallback. `tests/test-watch.sh` feeds it captured screens (`watch.sh --sig < screen`).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| The watcher fires at once with "AGENT BLOCKED", but the worker isn't stuck | It is at a **permission prompt**, which reads as `blocked`. Answer read-only prompts with "Yes, and switch to auto mode", then re-arm |
| A follow-up sent to a busy worker never ran | Text sent mid-turn can be dropped when it goes idle. Check its screen after it finishes; resend |
| Your text landed glued to other text | An idle session shows an auto-suggestion in its input; `boss-host send` clears it first, a raw `terminals send --text` does not |
