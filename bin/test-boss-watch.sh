#!/bin/bash
# Feeds `boss-watch-done.sh --sig` fixture screens: fire, fire, no fire, no fire, no fire (quoted done-message), then same-task-new-summary must differ.
S="$(cd "$(dirname "$0")" && pwd)/boss-watch-done.sh"; fail=0
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
 {"number":6,"state":"MERGED","isDraft":false}]'
got=$(echo "$prs" | "$S" --ready | tr '\n' ' ' | sed 's/ $//')
if [ "$got" = "1 5 6" ]; then echo "ok   PR READY -> $got"; else echo "FAIL PR READY: want '1 5 6', got '$got'"; fail=1; fi
exit $fail
