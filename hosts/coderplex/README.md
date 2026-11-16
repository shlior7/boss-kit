# Host plugin: coderplex

`coderplex-ctl`. A worker is a **session**: its own git worktree, terminal and agent on one daemon. Signed in: `coderplex-ctl status` lists a target that is `ok`.

| | |
|---|---|
| This session's id | `$CODERPLEX_SESSION_ID` (8 hex characters, what the ledger holds) |
| Create | `sessions create --target local --repo --branch --prompt` (`--target` is required when a remote workspace is also reachable) |
| Messages | `sessions send`: queues until the agent is idle and wakes a stopped one; replies arrive as a new prompt in the boss's pane |
| Envelope | the worker sends it to the boss as a message (`coderplex-ctl sessions send <boss> --file -`), which wakes the boss; the generic `boss-host watch` checks that session's messages as the safety net and logs the stage |
| State | `agentPhase`: `working`; `review` (its turn ended) and none read as idle; any other phase as blocked |
| Folders | sidebar sections (`sessions move --section`) |
| Pages | none: proof and review pages are claude.ai artifacts |
| Closing | nothing to close: archive a finished session (`sessions archive`, never `--ttl` without the user's OK: it deletes) |

Config, under `hosts.coderplex`: `target` (`local`, where new sessions go; messages reach the same daemon only), `agent` (`claude`).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| A worker finished but the boss heard nothing | Its prompt must end with sending the envelope to the boss. Check `coderplex-ctl sessions messages <boss id>` |
| The watcher fires "AGENT BLOCKED" | The agent waits on someone: a permission prompt or a question. `boss-host open <id>`, answer, re-arm |
| An envelope landed before the watcher was armed | It still fires: messages count as new from the dispatch as coderplex records it (the boss's last message, else the session's creation) |
