#!/bin/bash
# boss-watch-done.sh <workspaceId> <terminalId> [<branch>]   (run with run_in_background; never edit while one runs)
# The boss ALWAYS watches for done with this script, never `superset terminals wait --match`. Three facts about the screen:
#  1. Claude Code draws the whole reply box at once, so the envelope's first line can land 48 rows above the bottom,
#     outside a `--max-lines 30` window (a one-line regex timed out at 30 and matched at once at 60).
#  2. Workers wrap the envelope: `SUPERSET_WORKER_DONE` on one line, `task: x` on the next, so a one-line regex never matches.
#  3. `terminals read` returns only the visible screen (64 rows) even with `--max-lines 600`; an envelope taller than the
#     screen loses its first line before a 20 s poll sees it.
# So: (a) `sig` strips the box and side pane, joins the token with the next non-empty line, and counts an envelope only when
# the token is directly followed by `task: <id>` (prose like "the SUPERSET_WORKER_DONE envelope for task x" never fires;
# templates whose field value is <placeholder> or literally "..." are skipped); (b) the optional <branch> adds a check that does not depend on the screen:
# about every 3rd poll, `gh pr list --head <branch> --state all` fires "PR READY #n" when a PR becomes non-draft or merged
# and was not so at start (run from the repo, or set GH_REPO). In a project whose PRs stay draft, BOSS_DRAFT_DONE=1 also
# counts a draft whose checks are all green (`--ready < pr-list.json` prints the numbers, bin/test-boss-watch.sh).
# Idle fallback (for a worker that asks in plain text): 9 idle polls (3 min) with an unchanged screen, 135 (45 min) while the bottom lines show a background shell or monitor ("1 shell": a worker waiting on its own yarn verify:pr, 10-30 min under load); envelopes fire at once, so a long fallback costs nothing.
# Env: BOSS_HOST (default: first host), BOSS_DRAFT_DONE. Poll 20 s, timeout 3 h. Needs superset CLI, jq (gh for <branch>).
# `sig` is "DONE|<id>|<first 30 chars of summary>" (or BLOCKED), so a new envelope with an already-seen task id still differs from the
# baseline (a dispatch message that quotes the done-message once poisoned it). `boss-watch-done.sh --sig < screen` prints it, nothing if none (bin/test-boss-watch.sh).
sig(){ awk '{ gsub(/││.*$/, ""); gsub(/[│╭╮╰╯⏺]/, " "); l[NR]=$0 }
  END { for (n = NR; n > 0; n--) if (match(l[n], /SUPERSET_WORKER_(DONE|BLOCKED)/)) {
    k = substr(l[n], RSTART + 16, RLENGTH - 16); r = substr(l[n], RSTART + RLENGTH)
    for (m = n + 1; m <= NR && l[m] ~ /^[ \t]*$/; m++) ;
    if (m <= NR) r = r " " l[m]
    if (r !~ /^[ \t]*task:[ \t]*[A-Za-z0-9._-]/) continue
    b = ""; for (i = n; i <= n + 6 && i <= NR; i++) b = b " " l[i]
    if (b ~ /(task|summary|files|checks|proof|handoff|reason|needs):? *(<[a-z]|\.\.\.)/) continue
    sub(/^[ \t]*task:[ \t]*/, "", r); sub(/[^A-Za-z0-9._-].*$/, "", r)
    su = ""; if (match(b, /summary:? +/)) { su = substr(b, RSTART + RLENGTH, 30); gsub(/[ \t]+/, " ", su) }
    print k "|" r "|" su; exit } }'; }
# PR numbers that count as done: merged, open non-draft, or (BOSS_DRAFT_DONE=1) a draft with every check green
pick(){ jq -r --arg drafts "${BOSS_DRAFT_DONE:-}" 'def green: (.statusCheckRollup // []) as $c | ($c | length) > 0
    and all($c[]; ((.conclusion // .state // "") | ascii_upcase) as $s | $s == "SUCCESS" or $s == "SKIPPED" or $s == "NEUTRAL");
  .[] | select(.state == "MERGED" or (.state == "OPEN" and (.isDraft == false or ($drafts == "1" and green)))) | .number'; }
[ "$1" = --sig ] && { sig; exit; }
[ "$1" = --ready ] && { pick; exit; }
W=$1; T=$2; B=$3
H=${BOSS_HOST:-$(superset hosts list --json | jq -r 'if type=="array" then .[0].id else .hosts[0].id end')}
scr(){ superset terminals read --workspace "$W" --host "$H" --terminal "$T" --max-lines 600 --json 2>/dev/null | jq -r '.text // empty'; }
# numbers of this branch's PRs that count as done (pick); fails when gh does
ready(){ local j; j=$(gh pr list --head "$B" --state all --json number,isDraft,state,statusCheckRollup 2>/dev/null) || return 1
  echo "$j" | pick; }
base=$(scr | sig); idle=0; lasth=""; prbase=""; prok=0
[ -n "$B" ] && prbase=$(ready) && prok=1
for i in $(seq 1 540); do
  sleep 20
  txt=$(scr); [ -z "$txt" ] && { echo "TERMINAL GONE (session ended or host restarted)"; exit 0; }
  cur=$(echo "$txt" | sig)
  if [ -n "$cur" ] && [ "$cur" != "$base" ]; then
    n=$(echo "$txt" | grep -n "SUPERSET_WORKER_" | tail -1 | cut -d: -f1)
    echo "ENVELOPE $cur"; echo "$txt" | tail -n +$n | sed 's/││.*$//' | head -60; exit 0
  fi
  if [ -n "$B" ] && [ $((i % 3)) -eq 0 ] && now=$(ready); then
    if [ "$prok" = 0 ]; then prbase=$now; prok=1   # first successful read becomes the baseline
    else new=$(comm -13 <(echo "$prbase" | sort) <(echo "$now" | sort) | grep . | head -1)
      [ -n "$new" ] && { echo "PR READY #$new"; echo "$txt" | tail -30 | sed 's/││.*$//'; exit 0; }
    fi
  fi
  st=$(superset snapshot --host "$H" --json 2>/dev/null | jq -r --arg t "$T" '.. | objects | select(.terminalId? == $t or .id? == $t) | .agent.state // empty' | head -1)
  if [ "$st" = blocked ]; then echo "AGENT BLOCKED ON INPUT"; echo "$txt" | tail -30 | sed 's/││.*$//'; exit 0; fi
  h=$(echo "$txt" | tail -25 | cksum)
  if [ "$st" = idle ] && [ "$h" = "$lasth" ]; then idle=$((idle+1)); else idle=0; fi
  lasth=$h
  need=9; echo "$txt" | tail -12 | grep -qE "[0-9]+ (shells?|monitors?)|Monitor event" && need=135
  if [ "$idle" -ge "$need" ]; then echo "AGENT IDLE WITHOUT ENVELOPE"; echo "$txt" | tail -40 | sed 's/││.*$//'; exit 0; fi
done
echo TIMEOUT
