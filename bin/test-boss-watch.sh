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
# PR READY: a draft counts only with BOSS_DRAFT_DONE=1 and every check green; pending or failing never does.
prs='[{"number":1,"state":"OPEN","isDraft":true,"statusCheckRollup":[{"conclusion":"SUCCESS"},{"state":"SUCCESS"}]},
 {"number":2,"state":"OPEN","isDraft":true,"statusCheckRollup":[{"conclusion":"SUCCESS"},{"conclusion":"","status":"IN_PROGRESS"}]},
 {"number":3,"state":"OPEN","isDraft":true,"statusCheckRollup":[{"conclusion":"FAILURE"}]},
 {"number":4,"state":"OPEN","isDraft":true,"statusCheckRollup":[]},
 {"number":5,"state":"OPEN","isDraft":false,"statusCheckRollup":[]},
 {"number":6,"state":"MERGED","isDraft":false}]'
for d in "" 1; do want=$([ "$d" = 1 ] && echo "1 5 6" || echo "5 6")
  got=$(echo "$prs" | BOSS_DRAFT_DONE=$d "$S" --ready | tr '\n' ' ' | sed 's/ $//')
  if [ "$got" = "$want" ]; then echo "ok   PR READY with BOSS_DRAFT_DONE='$d' -> $got"; else echo "FAIL PR READY with BOSS_DRAFT_DONE='$d': want '$want', got '$got'"; fail=1; fi
done
exit $fail
