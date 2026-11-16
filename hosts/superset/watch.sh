#!/bin/bash
# watch.sh <workspaceId> <terminalId> [<branch>]   the superset host plugin's watcher, started by `boss-host watch`
# (run with run_in_background; never edit while one runs)
# The boss ALWAYS watches for done with this script, never `superset terminals wait --match`. Three facts about the screen:
#  1. Claude Code draws the whole reply box at once, so the envelope's first line can land 48 rows above the bottom,
#     outside a `--max-lines 30` window (a one-line regex timed out at 30 and matched at once at 60).
#  2. Workers wrap the envelope: `BOSS_WORKER_DONE` on one line, `task: x` on the next, so a one-line regex never matches.
#     (The older token SUPERSET_WORKER_DONE / _BLOCKED counts the same, everywhere below.)
#  3. `terminals read` returns only the visible screen (64 rows) even with `--max-lines 600`; an envelope taller than the
#     screen loses its first line before a 20 s poll sees it.
# So: (a) `sig` strips the box and side pane, joins the token with the next non-empty line, and counts an envelope only when
# the token is directly followed by `task: <id>` (prose like "the BOSS_WORKER_DONE envelope for task x" never fires;
# templates whose field value is <placeholder> or literally "..." are skipped); (b) the optional <branch> adds a check that does not depend on the screen:
# about every 3rd poll, `gh pr list --head <branch> --state all` fires "PR READY #n" when a PR gets a comment holding a DONE
# envelope, becomes non-draft or merges, and was not so at start (run from the repo, or set GH_REPO). Workers keep their PR
# draft and post the envelope there; the boss marks it ready. `--ready < pr-list.json` prints the numbers (tests/test-watch.sh).
# Idle fallback (for a worker that asks in plain text): 9 idle polls (3 min) with an unchanged screen, 135 (45 min) while the bottom lines show a background shell or monitor ("1 shell": a worker waiting on its own yarn verify:pr, 10-30 min under load); envelopes fire at once, so a long fallback costs nothing.
# On a fire it logs the stage to the boss's events.jsonl through bin/boss-event (DONE, BLOCKED, PR READY or merged), for the boss-deck stages.
# Env: BOSS_HOST (default: first host), BOSS_HOST_CLI (default: superset); boss-host sets both to what the adapter resolved.
# Poll 20 s, timeout 3 h. Needs the superset CLI, jq (gh for <branch>).
# It reads the screen: this host's workers leave the envelope there.
# `sig` ignores any line whose box border starts past column 20 (the boss's own message box, which may quote a done-message with real values).
# `sig` is "DONE|<id>|<first 30 chars of summary>" (or BLOCKED), so a new envelope with an already-seen task id still differs from the
# baseline (a dispatch message that quotes the done-message once poisoned it). `watch.sh --sig < screen` prints it, nothing if none (tests/test-watch.sh).
sig(){ LC_ALL=C awk '/^ {21,}(│|╭|╰)/ { l[NR] = ""; next }   # the boss'\''s own message box is drawn past column 20: never an envelope
  { gsub(/││.*$/, ""); gsub(/│|─|╭|╮|╰|╯|⏺/, " "); l[NR]=$0 }
  END { for (n = NR; n > 0; n--) if (match(l[n], /(BOSS|SUPERSET)_WORKER_(DONE|BLOCKED)/)) {
    k = substr(l[n], RSTART, RLENGTH); sub(/^.*_WORKER_/, "", k); r = substr(l[n], RSTART + RLENGTH)
    for (m = n + 1; m <= NR && l[m] ~ /^[ \t]*$/; m++) ;
    if (m <= NR) r = r " " l[m]
    if (r !~ /^[ \t]*task:[ \t]*[A-Za-z0-9._-]/) continue
    b = ""; for (i = n; i <= n + 6 && i <= NR; i++) b = b " " l[i]
    if (b ~ /(task|summary|files|checks|proof|handoff|reason|needs):? *(<[a-z]|\.\.\.)/) continue
    sub(/^[ \t]*task:[ \t]*/, "", r); sub(/[^A-Za-z0-9._-].*$/, "", r)
    su = ""; if (match(b, /summary:? +/)) { su = substr(b, RSTART + RLENGTH, 30); gsub(/[ \t]+/, " ", su); sub(/ $/, "", su) }
    print k "|" r "|" su; exit } }'; }
# PR numbers that count as done: merged, open non-draft, or carrying a comment whose line starts a DONE envelope
pick(){ jq -r '.[] | select(.state == "MERGED" or (.state == "OPEN" and (.isDraft == false
    or any((.comments // [])[]; .body | test("(^|\n)[ \t>`]*(BOSS|SUPERSET)_WORKER_DONE\\s+task:[ \t]*[A-Za-z0-9._-]"))))) | .number'; }
[ "$1" = --sig ] && { sig; exit; }
[ "$1" = --ready ] && { pick; exit; }
W=$1; T=$2; B=$3
# log a stage for the boss-deck; a failure here never stops the watcher
ev(){ "${BOSS_BIN:-$(dirname "$0")/../../bin}/boss-event" "$W" "$@" >/dev/null 2>&1 || true; }
S=${BOSS_HOST_CLI:-superset}
H=${BOSS_HOST:-$("$S" hosts list --json | jq -r 'if type=="array" then .[0].id else .hosts[0].id end')}
scr(){ "$S" terminals read --workspace "$W" --host "$H" --terminal "$T" --max-lines 600 --json 2>/dev/null | jq -r '.text // empty'; }
# numbers of this branch's PRs that count as done (pick); fails when gh does
ready(){ local j; j=$(gh pr list --head "$B" --state all --json number,isDraft,state,comments 2>/dev/null) || return 1
  echo "$j" | pick; }
base=$(scr | sig); idle=0; lasth=""; prbase=""; prok=0
[ -n "$B" ] && prbase=$(ready) && prok=1
for i in $(seq 1 540); do
  sleep 20
  txt=$(scr); [ -z "$txt" ] && { echo "TERMINAL GONE (session ended or host restarted)"; exit 0; }
  cur=$(echo "$txt" | sig)
  if [ -n "$cur" ] && [ "$cur" != "$base" ]; then
    n=$(echo "$txt" | grep -nE "(BOSS|SUPERSET)_WORKER_" | tail -1 | cut -d: -f1)
    ev "${cur%%|*}" "$(echo "${cur#*|}" | sed 's/|/: /')"
    echo "ENVELOPE $cur"; echo "$txt" | tail -n +$n | sed 's/││.*$//' | head -60; exit 0
  fi
  if [ -n "$B" ] && [ $((i % 3)) -eq 0 ] && now=$(ready); then
    if [ "$prok" = 0 ]; then prbase=$now; prok=1   # first successful read becomes the baseline
    else new=$(comm -13 <(echo "$prbase" | sort) <(echo "$now" | sort) | grep . | head -1)
      [ -n "$new" ] && { [ "$(gh pr view "$new" --json state -q .state 2>/dev/null)" = MERGED ] && ev merged "PR #$new" || ev "PR READY" "PR #$new"
        echo "PR READY #$new"; echo "$txt" | tail -30 | sed 's/││.*$//'; exit 0; }
    fi
  fi
  st=$("$S" snapshot --host "$H" --json 2>/dev/null | jq -r --arg t "$T" '.. | objects | select(.terminalId? == $t or .id? == $t) | .agent.state // empty' | head -1)
  if [ "$st" = blocked ]; then ev BLOCKED "blocked on input"; echo "AGENT BLOCKED ON INPUT"; echo "$txt" | tail -30 | sed 's/││.*$//'; exit 0; fi
  h=$(echo "$txt" | tail -25 | cksum)
  if [ "$st" = idle ] && [ "$h" = "$lasth" ]; then idle=$((idle+1)); else idle=0; fi
  lasth=$h
  need=9; echo "$txt" | tail -12 | grep -qE "[0-9]+ (shells?|monitors?)|Monitor event" && need=135
  if [ "$idle" -ge "$need" ]; then echo "AGENT IDLE WITHOUT ENVELOPE"; echo "$txt" | tail -40 | sed 's/││.*$//'; exit 0; fi
done
echo TIMEOUT
