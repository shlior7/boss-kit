#!/bin/bash
# Feeds `watch.sh --sig` fixture screens: fire, fire, no fire, no fire, no fire (quoted done-message), then same-task-new-summary must differ.
S="$(cd "$(dirname "$0")/.." && pwd)/watch.sh"; fail=0
check(){ local name=$1 want=$2 got; got=$("$S" --sig)
  if [ "$got" = "$want" ]; then echo "ok   $name -> ${got:-no fire}"; else echo "FAIL $name: want '${want:-no fire}', got '${got:-no fire}'"; fail=1; fi; }
check "one-line envelope in a box with a side pane" "DONE|demo-task|did it files: a.sh checks" <<'X'
  some earlier output
╭──────────────────────────────────────────╮ ││ side pane: workers
│ ⏺ SUPERSET_WORKER_DONE task: demo-task summary: did it files: a.sh ││ demo-worker  idle
│   checks: ok handoff: none                ││ 
╰──────────────────────────────────────────╯ ││
X
check "two-line envelope" "DONE|demo-task|did it" <<'X'
│   SUPERSET_WORKER_DONE
│   task: demo-task
│   summary: did it
X
check "prose false positive" "" <<'X'
│ When finished, post the SUPERSET_WORKER_DONE
│ envelope for task demo-task.
X
check "template line" "" <<'X'
│ SUPERSET_WORKER_DONE task: <id> summary: <one line> files: <paths>
X
check "dispatch message quoting the done-message, wrapped, with '...' fields" "" <<'X'
│ post a one-line envelope: SUPERSET_WORKER_DONE
│ task: demo-task summary: ... checks: ...
X
check "boss message box (indented past column 20) quoting a done-message with real values" "" <<'X'
╭──────────────────────────────────────────────────╮
│ ⏺ working on it                                  │
╰──────────────────────────────────────────────────╯
You ⬤
                              ╭─────────────────────────────────────────╮
                              │ reply with: post SUPERSET_WORKER_BLOCKED │
                              │ task: e2e-exclusive reason: proof runs   │
                              │ needs: boss go                           │
                              ╰─────────────────────────────────────────╯
X
check "worker envelope above a boss message box still fires" "DONE|demo-task|did it" <<'X'
╭──────────────────────────────────────────╮
│ ⏺ SUPERSET_WORKER_DONE task: demo-task summary: did it │
╰──────────────────────────────────────────╯
                              ╭─────────────────────────────╮
                              │ SUPERSET_WORKER_BLOCKED task: other reason: x │
                              ╰─────────────────────────────╯
X
check "new token, two-line envelope" "DONE|demo-task|did it" <<'X'
│   BOSS_WORKER_DONE
│   task: demo-task
│   summary: did it
X
check "new token, blocked" "BLOCKED|demo-task|" <<'X'
│ ⏺ BOSS_WORKER_BLOCKED task: demo-task reason: needs a token ││ side
X
check "new token, prose false positive" "" <<'X'
│ When finished, post the BOSS_WORKER_DONE
│ envelope for task demo-task.
X
a=$("$S" --sig <<'X'
│ SUPERSET_WORKER_DONE task: demo-task summary: first run checks: ok
X
); b=$("$S" --sig <<'X'
│ SUPERSET_WORKER_DONE task: demo-task summary: second run checks: ok
X
)
if [ -n "$a" ] && [ "$a" != "$b" ]; then echo "ok   same task, new summary -> differs ($a vs $b)"; else echo "FAIL same task, new summary: '$a' vs '$b'"; fail=1; fi
# PR READY: a draft counts only once a comment starts a DONE envelope; a comment that quotes it, or a template, never does.
prs='[{"number":1,"state":"OPEN","isDraft":true,"comments":[{"body":"Proof: https://example.com/p\n\nSUPERSET_WORKER_DONE task: fix-1\nsummary: done"}]},
 {"number":2,"state":"OPEN","isDraft":true,"comments":[{"body":"Will post the SUPERSET_WORKER_DONE envelope for task fix-2 when done"}]},
 {"number":3,"state":"OPEN","isDraft":true,"comments":[{"body":"SUPERSET_WORKER_DONE task: <id>"}]},
 {"number":4,"state":"OPEN","isDraft":true,"comments":[]},
 {"number":5,"state":"OPEN","isDraft":false,"comments":[]},
 {"number":6,"state":"MERGED","isDraft":false},
 {"number":7,"state":"OPEN","isDraft":true,"comments":[{"body":"BOSS_WORKER_DONE task: fix-7\nsummary: done"}]},
 {"number":8,"state":"OPEN","isDraft":true,"comments":[{"body":"BOSS_WORKER_DONE\ntask: fix-8\nsummary: done"}]}]'
got=$(echo "$prs" | "$S" --ready | tr '\n' ' ' | sed 's/ $//')
if [ "$got" = "1 5 6 7 8" ]; then echo "ok   PR READY -> $got"; else echo "FAIL PR READY: want '1 5 6 7 8', got '$got'"; fail=1; fi
# The watcher runs the CLI and machine boss-host hands it (the adapter's), never a bare `superset` from PATH.
t=$(mktemp -d); mkdir "$t/bin" "$t/cli"; ln -s "$(command -v jq)" "$t/bin/jq"
printf '#!/bin/sh\necho "$*" >> "%s/calls"\necho "{\\"text\\": \\"hi\\"}"\n' "$t" > "$t/cli/the-cli"; chmod +x "$t/cli/the-cli"
PATH="$t/bin:/usr/bin:/bin" BOSS_HOST=m-7 BOSS_HOST_CLI="$t/cli/the-cli" "$S" w1 t1 >/dev/null 2>&1 & pid=$!
for _ in 1 2 3 4 5 6 7 8 9 10; do [ -s "$t/calls" ] && break; sleep 0.2; done; kill $pid 2>/dev/null; wait $pid 2>/dev/null
got=$(head -1 "$t/calls" 2>/dev/null)
if [ "$got" = "terminals read --workspace w1 --host m-7 --terminal t1 --max-lines 600 --json" ]; then echo "ok   resolved CLI and machine -> $got"
else echo "FAIL resolved CLI and machine: got '${got:-no call}'"; fail=1; fi
rm -rf "$t"
exit $fail
