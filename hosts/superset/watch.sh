#!/bin/bash
# watch.sh <workspaceId> <terminalId> [<branch>]   the superset host plugin's watcher, started by `boss-host watch`
# (run with run_in_background; never edit while one runs)
# The boss ALWAYS watches for done with this script, never `superset terminals wait --match`. Three facts about the screen:
#  1. Claude Code draws the whole reply box at once, so the envelope's first line can land 48 rows above the bottom,
#     outside a `--max-lines 30` window (a one-line regex timed out at 30 and matched at once at 60).
#  2. Workers wrap the envelope: `BOSS_WORKER_DONE` on one line, `task: x` on the next, so a one-line regex never matches.
#     (The older token SUPERSET_WORKER_DONE / _BLOCKED counts the same, everywhere below.)
#  3. `terminals read` returns only the visible screen, which is as tall as the worker's pane (often 32 rows) even with
#     `--max-lines 600`; an envelope taller than the pane never shows its first line (a 46-row reply box in a 32-row pane
#     fired 17.7 h late, once the pane had grown taller).
# So: (a) `sig` strips the box and side pane, joins the token with the next non-empty line, and counts an envelope only when
# the token is directly followed by `task: <id>` (prose like "the BOSS_WORKER_DONE envelope for task x" never fires;
# templates whose field value is <placeholder> or literally "..." are skipped, and so is the PR comment's hidden marker
# <!-- BOSS_WORKER_DONE task: x -->, which a dispatch prompt quotes with the real id); (b) the optional <branch> adds a check that does not depend on the screen:
# about every 3rd poll, `gh pr list --head <branch> --state all` fires "PR READY #n" when a PR gets a comment holding a DONE
# envelope or its hidden marker, becomes non-draft or merges, and was not so at start (run from the repo, or set GH_REPO).
# (c) When the screen shows no new envelope, `said` reads the worker's last replies from its Claude Code transcript
# ($CLAUDE_CONFIG_DIR or ~/.claude, projects/<worktree path with every non-alphanumeric as ->/<newest>.jsonl) through the same `sig`,
# against its own baseline, so an envelope taller than the pane still fires.
# Workers keep their PR draft and post a status comment ending with the marker there; the boss marks it ready. `--ready < pr-list.json` prints the numbers (tests/test-watch.sh).
# Idle fallback (for a worker that asks in plain text): WATCH_IDLE_S of idle polls with an unchanged screen (digits ignored: a status-line clock ticks every minute; 3 min), WATCH_IDLE_SHELL_S (45 min) while the bottom lines show a background shell or monitor ("1 shell": a worker waiting on its own yarn verify:pr, 10-30 min under load); envelopes fire at once, so a long fallback costs nothing.
# All timings (poll, timeout, both idle fallbacks, re-arms) come from bin/watch-timings.json, which the boss-deck reads too.
# Liveness: every poll touches a beat beside the watcher's file ($BOSS_WATCHER_FILE, set by `boss-host watch`: <pid>.json -> <pid>.beat); the deck calls a watcher stale only when its pid is dead or the beat is older than WATCH_BEAT_POLLS polls.
# Self-heal: when WATCH_TIMEOUT_S passes it re-arms itself in place (same worker, terminal, branch and baselines, so nothing that landed meanwhile is missed) up to WATCH_REARM_MAX times, counting them in its file ("rearms"), then exits with TIMEOUT as before.
# On a fire it logs the stage to the boss's events.jsonl through bin/boss-event (DONE, BLOCKED, PR READY or merged), for the boss-deck stages.
# Env: BOSS_HOST (default: first host), BOSS_HOST_CLI (default: superset); boss-host sets both to what the adapter resolved.
# Tests override the sleep and the polls per run: BOSS_WATCH_POLL_S, BOSS_WATCH_POLLS. Needs the superset CLI, jq (gh for <branch>).
# It reads the screen: this host's workers leave the envelope there.
# `sig` ignores any line whose box border starts past column 20 (the boss's own message box, which may quote a done-message with real values).
# `sig` is "DONE|<id>|<first 30 chars of summary>" (or BLOCKED), so a new envelope with an already-seen task id still differs from the
# baseline (a dispatch message that quotes the done-message once poisoned it). `watch.sh --sig < screen` prints it, nothing if none (tests/test-watch.sh).
sig(){ LC_ALL=C awk '/^ {21,}(│|╭|╰)/ { l[NR] = ""; next }   # the boss'\''s own message box is drawn past column 20: never an envelope
  { gsub(/││.*$/, ""); gsub(/│|─|╭|╮|╰|╯|⏺/, " "); l[NR]=$0 }
  END { for (n = NR; n > 0; n--) if (match(l[n], /(BOSS|SUPERSET)_WORKER_(DONE|BLOCKED)/)) {
    if (substr(l[n], 1, RSTART - 1) ~ /<!--[ \t]*$/) continue   # the hidden marker of a PR comment (a prompt quotes it): never the envelope
    k = substr(l[n], RSTART, RLENGTH); sub(/^.*_WORKER_/, "", k); r = substr(l[n], RSTART + RLENGTH)
    for (m = n + 1; m <= NR && l[m] ~ /^[ \t]*$/; m++) ;
    if (m <= NR) r = r " " l[m]
    if (r !~ /^[ \t]*task:[ \t]*[A-Za-z0-9._-]/) continue
    b = ""; for (i = n; i <= n + 6 && i <= NR; i++) b = b " " l[i]
    if (b ~ /(task|summary|files|checks|proof|handoff|reason|needs):? *(<[a-z]|\.\.\.)/) continue
    sub(/^[ \t]*task:[ \t]*/, "", r); sub(/[^A-Za-z0-9._-].*$/, "", r)
    su = ""; if (match(b, /summary:? +/)) { su = substr(b, RSTART + RLENGTH, 30); gsub(/[ \t]+/, " ", su); sub(/ $/, "", su) }
    print k "|" r "|" su; exit } }'; }
# PR numbers that count as done: merged, open non-draft (unless BOSS_PR_DRAFT=0: workers open ready PRs, config github.draft),
# or carrying a comment whose line starts a DONE envelope or holds its hidden marker (<!-- BOSS_WORKER_DONE task: x -->, the
# human-readable status comment's last line)
pick(){ jq -r '.[] | select(.state == "MERGED" or (.state == "OPEN" and ((.isDraft == false and $ENV.BOSS_PR_DRAFT != "0")
    or any((.comments // [])[]; .body | test("(^|\n)[ \t>`]*(<!--[ \t]*)?(BOSS|SUPERSET)_WORKER_DONE\\s+task:[ \t]*[A-Za-z0-9._-]"))))) | .number'; }
[ "$1" = --sig ] && { sig; exit; }
[ "$1" = --ready ] && { pick; exit; }
W=$1; T=$2; B=$3
# log a stage for the boss-deck; a failure here never stops the watcher
ev(){ "${BOSS_BIN:-$(dirname "$0")/../../bin}/boss-event" "$W" "$@" >/dev/null 2>&1 || true; }
S=${BOSS_HOST_CLI:-superset}
H=${BOSS_HOST:-$("$S" hosts list --json | jq -r 'if type=="array" then .[0].id else .hosts[0].id end')}
WT=$("$S" workspaces list --host "$H" --json 2>/dev/null | jq -r --arg w "$W" '(if type == "array" then . else .workspaces end)[]? | select(.id == $w) | .worktreePath // empty')
TD=${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/$(printf %s "$WT" | sed 's/[^A-Za-z0-9]/-/g')
said(){ local f; [ -n "$WT" ] && f=$(ls -t "$TD"/*.jsonl 2>/dev/null | head -1) && [ -n "$f" ] || return 0
  tail -n 400 "$f" | jq -Rrn '[inputs | fromjson? | select(.type? == "assistant") | .message.content[]? | select(.type? == "text") | .text] | .[-5:][]' 2>/dev/null | tr -d '*`'; }
scr(){ "$S" terminals read --workspace "$W" --host "$H" --terminal "$T" --max-lines 600 --json 2>/dev/null | jq -r '.text // empty'; }
# numbers of this branch's PRs that count as done (pick); fails when gh does
ready(){ local j; j=$(gh pr list --head "$B" --state all --json number,isDraft,state,comments 2>/dev/null) || return 1
  echo "$j" | pick; }
read -r POLL TIMEOUT IDLE IDLE_SHELL REARM_MAX < <(jq -r '[.WATCH_POLL_S, .WATCH_TIMEOUT_S, .WATCH_IDLE_S, .WATCH_IDLE_SHELL_S, .WATCH_REARM_MAX] | @tsv' "$(dirname "$0")/../../bin/watch-timings.json") \
  || { echo "watch.sh: cannot read bin/watch-timings.json" >&2; exit 1; }
polls=${BOSS_WATCH_POLLS:-$((TIMEOUT / POLL))}
# the liveness beat, beside the watcher's file (unset when run by hand); a failure here never stops the watcher
beat(){ [ -n "$BOSS_WATCHER_FILE" ] && touch "${BOSS_WATCHER_FILE%.json}.beat" 2>/dev/null; return 0; }
# count a re-arm in the watcher's file (atomic: the deck reads it at any time)
rearmed(){ [ -n "$BOSS_WATCHER_FILE" ] && jq --argjson n "$1" '.rearms = $n' "$BOSS_WATCHER_FILE" > "$BOSS_WATCHER_FILE.tmp" 2>/dev/null && mv "$BOSS_WATCHER_FILE.tmp" "$BOSS_WATCHER_FILE"; return 0; }
base=$(scr | sig); tbase=$(said | sig); idle=0; lasth=""; prbase=""; prok=0
[ -n "$B" ] && prbase=$(ready) && prok=1
beat
# one pass is polls polls (WATCH_TIMEOUT_S); at its end the watcher re-arms itself, keeping its baselines, up to WATCH_REARM_MAX times
for i in $(seq 1 $((polls * (REARM_MAX + 1)))); do
  sleep "${BOSS_WATCH_POLL_S:-$POLL}"
  beat
  [ "$i" -gt 1 ] && [ $(((i - 1) % polls)) -eq 0 ] && rearmed $(((i - 1) / polls))
  txt=$(scr); [ -z "$txt" ] && { echo "TERMINAL GONE (session ended or host restarted)"; exit 0; }
  cur=$(echo "$txt" | sig)
  if [ -z "$cur" ] || [ "$cur" = "$base" ]; then   # not on the screen: the transcript (an envelope taller than the pane)
    t=$(said); cur=$(echo "$t" | sig)
    if [ -n "$cur" ] && [ "$cur" != "$tbase" ]; then txt=$t; else cur=; fi
  fi
  if [ -n "$cur" ]; then
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
  h=$(echo "$txt" | tail -25 | tr -d 0-9 | cksum)
  if [ "$st" = idle ] && [ "$h" = "$lasth" ]; then idle=$((idle+1)); else idle=0; fi
  lasth=$h
  need=$((IDLE / POLL)); echo "$txt" | tail -12 | grep -qE "[0-9]+ (shells?|monitors?)|Monitor event" && need=$((IDLE_SHELL / POLL))
  if [ "$idle" -ge "$need" ]; then echo "AGENT IDLE WITHOUT ENVELOPE"; echo "$txt" | tail -40 | sed 's/││.*$//'; exit 0; fi
done
echo TIMEOUT
