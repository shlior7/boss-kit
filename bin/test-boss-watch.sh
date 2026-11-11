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
a=$("$S" --sig <<'X'
│ SUPERSET_WORKER_DONE task: demo-task summary: first run checks: ok
X
); b=$("$S" --sig <<'X'
│ SUPERSET_WORKER_DONE task: demo-task summary: second run checks: ok
X
)
if [ -n "$a" ] && [ "$a" != "$b" ]; then echo "ok   same task, new summary -> differs ($a vs $b)"; else echo "FAIL same task, new summary: '$a' vs '$b'"; fail=1; fi
exit $fail
