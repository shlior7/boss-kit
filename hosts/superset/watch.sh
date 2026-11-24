#!/bin/bash
# watch.sh <workspaceId> <terminalId> [<branch>] [--task <id>]   the superset host plugin's watcher, started by `boss-host watch`
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
# (d) The transcript read is pinned to the watched agent's own session: its id is resolved once at start from Claude Code's
# session registry ($CLAUDE_CONFIG_DIR or ~/.claude, sessions/<pid>.json): the live session in the worktree that started closest
# after the terminal was created. Only when that fails does it read the newest transcript of the worktree (any session's, an old
# one's envelope can fire), and says so in one stderr line. (e) `--task <id>`: an envelope whose task: is another id never fires
# (screen or transcript); it is ignored and its baseline updated. `watch.sh --sig [--task <id>] < screen` applies the same filter.
# Workers keep their PR draft and post a status comment ending with the marker there; the boss marks it ready. `--ready < pr-list.json` prints the numbers (tests/test-watch.sh).
# Idle fallback (for a worker that asks in plain text): 9 idle polls (3 min) with an unchanged screen (digits ignored: a status-line clock ticks every minute), 135 (45 min) while the bottom lines show a background shell or monitor ("1 shell": a worker waiting on its own yarn verify:pr, 10-30 min under load); envelopes fire at once, so a long fallback costs nothing.
# Manual mode: when the user types in the worker's own session, its prompt hook logs a `manual` event. `boss-event --manual`
# says "new" the first time any watcher asks about that event (recorded in the boss's cache: one wake per burst, also for a
# burst that landed before this watcher started), which fires "WORKER MANUAL"; while it says "on" the idle fallback never
# fires (an envelope, blocked or a gone terminal still do).
# On a fire it logs the stage to the boss's events.jsonl through bin/boss-event (DONE, BLOCKED, PR READY or merged), for the boss-deck stages.
# Env: BOSS_HOST (default: first host), BOSS_HOST_CLI (default: superset); boss-host sets both to what the adapter resolved.
# Poll 20 s, timeout 3 h (BOSS_WATCH_POLL_S, BOSS_WATCH_POLLS: 540). Needs the superset CLI, jq (gh for <branch>).
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
[ "$1" = --ready ] && { pick; exit; }
# --task <id> may sit anywhere; the rest are the positional arguments
K=; a=(); while [ $# -gt 0 ]; do if [ "$1" = --task ]; then K=$2; shift 2; else a+=("$1"); shift; fi; done; set -- ${a[@]+"${a[@]}"}
# mine <sig>: true when no --task was given, there is no envelope, or its task is it
mine(){ [ -z "$K" ] || [ -z "$1" ] || [ "$(echo "$1" | cut -d'|' -f2)" = "$K" ]; }
[ "$1" = --sig ] && { s=$(sig); mine "$s" && echo "$s"; exit 0; }
W=$1; T=$2; B=$3
# log a stage for the boss-deck; a failure here never stops the watcher
EV=${BOSS_BIN:-$(dirname "$0")/../../bin}/boss-event
ev(){ "$EV" "$W" "$@" >/dev/null 2>&1 || true; }
S=${BOSS_HOST_CLI:-superset}
H=${BOSS_HOST:-$("$S" hosts list --json | jq -r 'if type=="array" then .[0].id else .hosts[0].id end')}
WT=$("$S" workspaces list --host "$H" --json 2>/dev/null | jq -r --arg w "$W" '(if type == "array" then . else .workspaces end)[]? | select(.id == $w) | .worktreePath // empty')
TD=${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/$(printf %s "$WT" | sed 's/[^A-Za-z0-9]/-/g')
# The agent's own session: among the live Claude sessions (registry sessions/<pid>.json) in this worktree with a transcript, the only
# one; of several, the one started closest after the terminal's createdAt (a host restart moves createdAt past startedAt: then
# none qualifies), else the most recently updated, said on stderr. Prints the transcript path, nothing when there is none.
own(){ local c f rows pick
  [ -n "$WT" ] || return 0
  c=$("$S" terminals list --workspace "$W" --host "$H" --json 2>/dev/null | jq -r --arg t "$T" '(.sessions // .)[]? | select(.terminalId == $t) | .createdAt // empty' | head -1)
  rows=$(for f in "${TD%/projects/*}"/sessions/*.json; do [ -f "$f" ] || continue
    jq -r --arg w "$WT" 'select(.cwd == $w) | "\(.pid) \(.sessionId) \(.startedAt // 0) \(.updatedAt // 0)"' "$f" 2>/dev/null; done |
    while read -r pid sid st up; do kill -0 "$pid" 2>/dev/null && [ -f "$TD/$sid.jsonl" ] && echo "$sid $st $up"; done)
  [ -n "$rows" ] || return 0
  if [ "$(echo "$rows" | wc -l)" -gt 1 ]; then
    pick=$(echo "$rows" | awk -v c="${c:-0}" '$2 >= c - 5000 && c > 0 { print $2 - c, $1 }' | sort -n | head -1 | cut -d' ' -f2)
    if [ -n "$pick" ]; then echo "watch.sh: several live sessions in $WT; took the one started closest after the terminal" >&2
    else pick=$(echo "$rows" | sort -k3,3nr | head -1 | cut -d' ' -f1); echo "watch.sh: several live sessions in $WT; took the most recently updated" >&2; fi
    echo "$TD/$pick.jsonl"
  else echo "$TD/${rows%% *}.jsonl"; fi; }
OWN=$(own)
[ -z "$OWN" ] && echo "watch.sh: could not resolve the agent's own session; reading the newest transcript in $TD (any session's)" >&2
said(){ local f=$OWN; [ -n "$f" ] || { [ -n "$WT" ] && f=$(ls -t "$TD"/*.jsonl 2>/dev/null | head -1) && [ -n "$f" ]; } || return 0
  tail -n 400 "$f" | jq -Rrn '[inputs | fromjson? | select(.type? == "assistant") | .message.content[]? | select(.type? == "text") | .text] | .[-5:][]' 2>/dev/null | tr -d '*`'; }
scr(){ "$S" terminals read --workspace "$W" --host "$H" --terminal "$T" --max-lines 600 --json 2>/dev/null | jq -r '.text // empty'; }
# numbers of this branch's PRs that count as done (pick); fails when gh does
ready(){ local j; j=$(gh pr list --head "$B" --state all --json number,isDraft,state,comments 2>/dev/null) || return 1
  echo "$j" | pick; }
base=$(scr | sig); tbase=$(said | sig); idle=0; lasth=""; prbase=""; prok=0
[ -n "$B" ] && prbase=$(ready) && prok=1
for i in $(seq 1 "${BOSS_WATCH_POLLS:-540}"); do
  sleep "${BOSS_WATCH_POLL_S:-20}"
  txt=$(scr); [ -z "$txt" ] && { echo "TERMINAL GONE (session ended or host restarted)"; exit 0; }
  cur=$(echo "$txt" | sig)
  mine "$cur" || { base=$cur; cur=; }   # another task's envelope: never fires, becomes the baseline
  if [ -z "$cur" ] || [ "$cur" = "$base" ]; then   # not on the screen: the transcript (an envelope taller than the pane)
    t=$(said); cur=$(echo "$t" | sig)
    mine "$cur" || { tbase=$cur; cur=; }
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
  m=$("$EV" --manual "$W" 2>/dev/null); man=0
  case "$m" in
    new*) echo "WORKER MANUAL (the user is working in it by hand: ${m#new }; read its .boss-worker/notes.md and screen, steer only with boss-host note, re-arm the watcher)"; exit 0;;
    on) man=1;;
  esac
  st=$("$S" snapshot --host "$H" --json 2>/dev/null | jq -r --arg t "$T" '.. | objects | select(.terminalId? == $t or .id? == $t) | .agent.state // empty' | head -1)
  if [ "$st" = blocked ]; then ev BLOCKED "blocked on input"; echo "AGENT BLOCKED ON INPUT"; echo "$txt" | tail -30 | sed 's/││.*$//'; exit 0; fi
  h=$(echo "$txt" | tail -25 | tr -d 0-9 | cksum)
  if [ "$st" = idle ] && [ "$h" = "$lasth" ] && [ "$man" = 0 ]; then idle=$((idle+1)); else idle=0; fi
  lasth=$h
  need=9; echo "$txt" | tail -12 | grep -qE "[0-9]+ (shells?|monitors?)|Monitor event" && need=135
  if [ "$idle" -ge "$need" ]; then echo "AGENT IDLE WITHOUT ENVELOPE"; echo "$txt" | tail -40 | sed 's/││.*$//'; exit 0; fi
done
echo TIMEOUT
