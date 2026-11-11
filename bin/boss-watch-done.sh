#!/bin/bash
# boss-watch-done.sh <workspaceId> <terminalId>   (run with run_in_background; never edit while one runs)
# 2026-11-11: the old envelope regex only matched the name alone on its own line, but Claude Code
# draws the reply in a box ("│ SUPERSET_WORKER_DONE task: x ...") with a side pane on the same line, so it never saw
# an envelope and only ever fired on its idle fallback. Now it strips the box and side pane, finds the name anywhere,
# reads its task, skips templates (a field whose value is a <placeholder>; a <token> inside a real URL is fine), and fires the moment the latest envelope differs from the start.
# Idle fallback (for a worker that asks in plain text): 9 idle polls (3 min) with an unchanged screen, 18 (6 min) if a background shell or monitor runs; envelopes fire at once, so a long fallback costs nothing.
# Env: BOSS_HOST (default: first host). Poll 20 s, timeout 3 h. Needs superset CLI, jq.
W=$1; T=$2
H=${BOSS_HOST:-$(superset hosts list --json | jq -r 'if type=="array" then .[0].id else .hosts[0].id end')}
scr(){ superset terminals read --workspace "$W" --host "$H" --terminal "$T" --max-lines 600 --json 2>/dev/null | jq -r '.text // empty'; }
sig(){ awk '{ gsub(/││.*$/, ""); gsub(/[│╭╮╰╯⏺]/, " "); l[NR]=$0 }
  END { for (n = NR; n > 0; n--) if (match(l[n], /SUPERSET_WORKER_(DONE|BLOCKED)/)) {
    k = substr(l[n], RSTART + 16, RLENGTH - 16); b = ""
    for (i = n; i <= n + 6 && i <= NR; i++) b = b " " l[i]
    if (b ~ /(task|summary|files|checks|proof|handoff|reason|needs):? *<[a-z]/) continue
    t = "?"; if (match(b, /task:? +[A-Za-z0-9._-]+/)) { t = substr(b, RSTART, RLENGTH); sub(/task:? +/, "", t) }
    print k "|" t; exit } }'; }
base=$(scr | sig); idle=0; lasth=""
for i in $(seq 1 540); do
  sleep 20
  txt=$(scr); [ -z "$txt" ] && { echo "TERMINAL GONE (session ended or host restarted)"; exit 0; }
  cur=$(echo "$txt" | sig)
  if [ -n "$cur" ] && [ "$cur" != "$base" ]; then
    n=$(echo "$txt" | grep -n "SUPERSET_WORKER_" | tail -1 | cut -d: -f1)
    echo "ENVELOPE $cur"; echo "$txt" | tail -n +$n | sed 's/││.*$//' | head -60; exit 0
  fi
  st=$(superset snapshot --host "$H" --json 2>/dev/null | jq -r --arg t "$T" '.. | objects | select(.terminalId? == $t or .id? == $t) | .agent.state // empty' | head -1)
  if [ "$st" = blocked ]; then echo "AGENT BLOCKED ON INPUT"; echo "$txt" | tail -30 | sed 's/││.*$//'; exit 0; fi
  h=$(echo "$txt" | tail -25 | cksum)
  if [ "$st" = idle ] && [ "$h" = "$lasth" ]; then idle=$((idle+1)); else idle=0; fi
  lasth=$h
  need=9; echo "$txt" | tail -12 | grep -qE "[0-9]+ (shells?|monitors?)|Monitor event" && need=18
  if [ "$idle" -ge "$need" ]; then echo "AGENT IDLE WITHOUT ENVELOPE"; echo "$txt" | tail -40 | sed 's/││.*$//'; exit 0; fi
done
echo TIMEOUT
