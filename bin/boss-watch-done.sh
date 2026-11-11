#!/bin/bash
# boss-watch-done.sh <workspaceId> <terminalId>   (run with run_in_background; never edit while one runs)
# Skips envelope templates whose fields are still <placeholders>, so the dispatch prompt never fires it.
# Env: BOSS_HOST = Superset host id (default: first host from `superset hosts list --json`).
# Fires on: a NEW line-anchored SUPERSET_WORKER_DONE/BLOCKED envelope (compared by its task: line),
#           agent state `blocked`, or 3 idle polls with an unchanged screen (agent asked in plain text).
# Needs: superset CLI, jq. Poll 30 s, timeout 2 h.
W=$1; T=$2
H=${BOSS_HOST:-$(superset hosts list --json | jq -r 'if type=="array" then .[0].id else .hosts[0].id end')}
RE='^[[:space:]⏺]*SUPERSET_WORKER_(DONE|BLOCKED)[[:space:]]*$'
scr(){ superset terminals read --workspace "$W" --host "$H" --terminal "$T" --max-lines 3000 --json | jq -r .text; }
sig(){ awk -v re="$RE" '{l[NR]=$0} END{ for(n=NR;n>0;n--) if(l[n] ~ re){ ph=0; s=l[n]; t=""; for(i=n+1;i<=n+5 && i<=NR;i++){ if(l[i] ~ /: *</) ph=1; if(t=="" && l[i] ~ /task/) t=l[i] } if(!ph){ print s t; exit } } }'; }
base=$(scr | sig); idle=0; lasth=""
for i in $(seq 1 240); do
  sleep 30
  txt=$(scr); cur=$(echo "$txt" | sig)
  if [ -n "$cur" ] && [ "$cur" != "$base" ]; then
    n=$(echo "$txt" | grep -nE "$RE" | tail -1 | cut -d: -f1)
    echo "ENVELOPE"; echo "$txt" | tail -n +$n | head -70; exit 0
  fi
  st=$(superset snapshot --host "$H" --json | jq -r --arg t "$T" '.. | objects | select(.terminalId? == $t or .id? == $t) | .agent.state // empty' | head -1)
  if [ "$st" = blocked ]; then echo "AGENT BLOCKED ON INPUT"; echo "$txt" | tail -30; exit 0; fi
  h=$(echo "$txt" | tail -25 | cksum)
  if [ "$st" = idle ] && [ "$h" = "$lasth" ]; then idle=$((idle+1)); else idle=0; fi
  lasth=$h
  if [ "$idle" -ge 3 ]; then echo "AGENT IDLE WITHOUT ENVELOPE (probably waiting for the user)"; echo "$txt" | tail -40; exit 0; fi
done
echo TIMEOUT
