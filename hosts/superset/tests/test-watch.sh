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
check "a dispatch prompt quoting the PR comment's hidden marker with the real id" "" <<'X'
> On the PR, post one short status comment ending with the line
  <!-- BOSS_WORKER_DONE task: demo-task -->
X
check "an envelope below a quoted marker still fires" "DONE|demo-task|did it" <<'X'
  <!-- BOSS_WORKER_DONE task: demo-task -->
│ ⏺ BOSS_WORKER_DONE task: demo-task summary: did it
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
 {"number":8,"state":"OPEN","isDraft":true,"comments":[{"body":"BOSS_WORKER_DONE\ntask: fix-8\nsummary: done"}]},
 {"number":9,"state":"OPEN","isDraft":true,"comments":[{"body":"Retries failed webhooks; tests pass.\n\n<!-- BOSS_WORKER_DONE task: fix-9 -->"}]},
 {"number":10,"state":"OPEN","isDraft":true,"comments":[{"body":"Done.\n<!-- SUPERSET_WORKER_DONE task: fix-10 -->"}]},
 {"number":11,"state":"OPEN","isDraft":true,"comments":[{"body":"end with <!-- BOSS_WORKER_DONE task: <id> -->"}]}]'
got=$(echo "$prs" | "$S" --ready | tr '\n' ' ' | sed 's/ $//')
if [ "$got" = "1 5 6 7 8 9 10" ]; then echo "ok   PR READY -> $got"; else echo "FAIL PR READY: want '1 5 6 7 8 9 10', got '$got'"; fail=1; fi
# With drafts off (config github.draft: false) an open non-draft PR is no done signal; merged and marked ones still are.
got=$(echo "$prs" | BOSS_PR_DRAFT=0 "$S" --ready | tr '\n' ' ' | sed 's/ $//')
if [ "$got" = "1 6 7 8 9 10" ]; then echo "ok   PR READY, drafts off -> $got"; else echo "FAIL PR READY drafts off: want '1 6 7 8 9 10', got '$got'"; fail=1; fi
# The watcher runs the CLI and machine boss-host hands it (the adapter's), never a bare `superset` from PATH.
t=$(mktemp -d); mkdir "$t/bin" "$t/cli"; ln -s "$(command -v jq)" "$t/bin/jq"
printf '#!/bin/sh\necho "$*" >> "%s/calls"\necho "{\\"text\\": \\"hi\\"}"\n' "$t" > "$t/cli/the-cli"; chmod +x "$t/cli/the-cli"
PATH="$t/bin:/usr/bin:/bin" BOSS_HOST=m-7 BOSS_HOST_CLI="$t/cli/the-cli" "$S" w1 t1 >/dev/null 2>&1 & pid=$!
# wait for the watcher's first terminals read (not just any call: it lists workspaces first), up to 60 s on a loaded machine
for _ in $(seq 300); do grep -qs '^terminals read' "$t/calls" && break; sleep 0.2; done; kill $pid 2>/dev/null; wait $pid 2>/dev/null
got=$(grep -m1 '^terminals read' "$t/calls" 2>/dev/null)
if [ "$got" = "terminals read --workspace w1 --host m-7 --terminal t1 --max-lines 600 --json" ]; then echo "ok   resolved CLI and machine -> $got"
else echo "FAIL resolved CLI and machine: got '${got:-no call}'"; fail=1; fi
rm -rf "$t"
# The whole poll loop on a fake CLI (BOSS_WATCH_POLL_S=0). fixtures/boxed-envelope.screen is a real incident's screen, scrubbed:
# a 46-row reply box holding the envelope, the side pane, "2 shells" and a status-line clock, at 64 rows. The worker's pane
# was 32 rows, so the envelope's first line was never on the screen.
F="$(dirname "$S")/tests/fixtures"
check "boxed envelope, side pane, 2 shells, 64-row pane" "DONE|widgets-12|The bot's summary on 4c1e9a2 d" < "$F/boxed-envelope.screen"
check "the same screen in a 32-row pane: its first line is off the top" "" < <(tail -32 "$F/boxed-envelope.screen")
# loop <polls> <screen before> <screen from the 2nd poll> [<transcript before> <transcript from the 2nd poll>]: the watcher's
# output. Each read ticks the status-line clock a minute; the agent is idle; waited for up to 120 s (it normally exits in a few seconds; a loaded machine is slower, so the wait is only a ceiling).
loop(){ local t; t=$(mktemp -d); mkdir -p "$t/claude/projects/-work-acme-widgets"
  cp "$2" "$t/s1"; cp "$3" "$t/s2"; [ -n "$4" ] && cp "$4" "$t/claude/projects/-work-acme-widgets/s.jsonl" && cp "$5" "$t/t2"
  cat > "$t/cli" <<'C'
#!/bin/bash
d=$(dirname "$0")
case "$1 $2" in
  "workspaces list") echo '[{"id":"w1","worktreePath":"/work/acme/widgets"}]' ;;
  "terminals read") n=$(($(cat "$d/n" 2>/dev/null || echo 0) + 1)); echo $n > "$d/n"; f=$d/s1
    [ $n -ge 3 ] && { f=$d/s2; [ -f "$d/t2" ] && mv "$d/t2" "$d/claude/projects/-work-acme-widgets/s.jsonl"; }
    sed "s/⏱️ 16:48/⏱️ $((10 + n / 60)):$((10 + n % 60))/" "$f" | jq -Rs '{text: .}' ;;
  "snapshot --host") echo '{"workspaces":[{"terminals":[{"id":"t1","agent":{"state":"idle"}}]}]}' ;;
esac
C
  chmod +x "$t/cli"
  local evbin=$t/none; [ -n "$EVENTS" ] && { evbin=$t/evbin; mkdir "$t/evbin"; printf '#!/bin/bash\n# --manual: the first line until the 3rd terminals read, then the second\nd=%s; [ "$(cat "$d/n" 2>/dev/null || echo 0)" -ge 3 ] && sed -n 2p "$d/events" || sed -n 1p "$d/events"\n' "$t" > "$t/evbin/boss-event"
    chmod +x "$t/evbin/boss-event"; printf '%s\n' "$EVENTS" > "$t/events"; }
  CLAUDE_CONFIG_DIR=$t/claude BOSS_HOST=m-7 BOSS_HOST_CLI=$t/cli BOSS_BIN=$evbin BOSS_WATCH_POLL_S=0 BOSS_WATCH_POLLS=$1 "$S" w1 t1 > "$t/out" 2>"$t/err" & local pid=$!
  for _ in $(seq 600); do kill -0 $pid 2>/dev/null || break; sleep 0.2; done; kill $pid 2>/dev/null; wait $pid 2>/dev/null
  cat "$t/out"; rm -rf "$t"; }
fires(){ local name=$1 want=$2 got; shift 2; got=$(loop "$@" | head -1)
  if [ "$got" = "$want" ]; then echo "ok   $name -> $got"; else echo "FAIL $name: want '$want', got '${got:-nothing in 120 s}'"; fail=1; fi; }
w=$(mktemp -d); { head -14 "$F/boxed-envelope.screen"; tail -8 "$F/boxed-envelope.screen"; } > "$w/working"; tail -32 "$F/boxed-envelope.screen" > "$w/tall"
head -4 "$F/boxed-envelope.jsonl" > "$w/t1"   # the worker's earlier envelope, then the boss's follow-up: the baseline
fires "envelope taller than the pane: read from the worker's transcript" "ENVELOPE DONE|widgets-12|The bot's summary on 4c1e9a2 d" \
  20 "$w/working" "$w/tall" "$w/t1" "$F/boxed-envelope.jsonl"
fires "an old envelope in the transcript never fires" "TIMEOUT" 5 "$w/working" "$w/working" "$w/t1" "$w/t1"
sed 's/ · 2 shells//' "$w/tall" > "$w/noshell"
fires "idle on a screen whose only change is the status-line clock" "AGENT IDLE WITHOUT ENVELOPE" 20 "$w/noshell" "$w/noshell"
# Manual mode (EVENTS: what boss-event --manual says before, then from the 3rd read; bosskit.manual_wake decides it):
# "on" (a burst a watcher already woke the boss for) pauses the idle fallback; "new" fires once.
EVENTS="on
on" fires "the user's own session, idle: no idle fire while the newest event is manual" "TIMEOUT" 20 "$w/noshell" "$w/noshell"
EVENTS="
new dig in" fires "a new manual burst wakes the boss once" "WORKER MANUAL (the user is working in it by hand: dig in; read its .boss-worker/notes.md and screen, steer only with boss-host note, re-arm the watcher)" 20 "$w/noshell" "$w/noshell"
rm -rf "$w"
# The transcript read is pinned to the watched agent's own session, and --task drops another task's envelope.
# pin <polls> <what happens at poll 3> [<watch.sh args after the terminal>]: the watcher's output (first stdout line, then "stderr: ..." lines);
# NOREG=1 leaves the worker out of the session registry; CREATED=<ms> is the terminal's createdAt (default 1000000, before the worker's
# session started; later = the host restarted); OLDLIVE=1 keeps the older session alive too; OLDSTART=<ms> is its startedAt (default 100000);
# LATE=1: the worker's session registers only at the 3rd read (another pane was registered first); OWNOLD=1: the worker's transcript
# starts with an old envelope of its own task (foreign-back: another task's envelope follows it, then the old one stands alone again).
# Two transcripts in the worker's project dir: an older session's (holds a task-old envelope) and the worker's own (holds none).
# The session registry names both; the terminal was created at 1000000 s, the worker's session started two seconds later.
# what: touch-old (the older session's file becomes the newest), own-envelope (the worker posts its own), own-foreign (the worker's
# transcript gets another task's envelope), none.
env_line(){ jq -cn --arg t "$2" --arg s "$3" '{type: "assistant", message: {content: [{type: "text", text: ("BOSS_WORKER_DONE task: " + $t + "\nsummary: " + $s)}]}}'; }
pin(){ local t pd; t=$(mktemp -d); pd=$t/claude/projects/-work-acme-widgets; mkdir -p "$pd" "$t/claude/sessions"
  env_line x task-old "an older session" > "$pd/old-sess.jsonl"; echo '{"type":"user","message":{"content":"go"}}' > "$pd/own-sess.jsonl"
  touch -t 202001010000 "$pd/old-sess.jsonl"; touch -t 202601010000 "$pd/own-sess.jsonl"
  local dead; dead=$(sh -c 'echo $$')   # a pid that has exited: the older session ended
  echo '{"pid": '$([ -n "$OLDLIVE" ] && echo $$ || echo "$dead")', "sessionId": "old-sess", "cwd": "/work/acme/widgets", "startedAt": '"${OLDSTART:-100000}"', "updatedAt": 200000}' > "$t/claude/sessions/1.json"
  echo '{"pid": '$$', "sessionId": "own-sess", "cwd": "/work/acme/widgets", "startedAt": 1002000, "updatedAt": 1900000}' > "$t/claude/sessions/2.json"
  echo "${CREATED:-1000000}" > "$t/created"
  [ -n "$OWNOLD" ] && { env_line x widgets-12 "old run" > "$pd/own-sess.jsonl"; cp "$pd/own-sess.jsonl" "$t/own.old"; touch -t 202601010000 "$pd/own-sess.jsonl"; }
  [ -n "$LATE" ] && mv "$t/claude/sessions/2.json" "$t/late.json"
  [ -n "$NOREG" ] && rm "$t/claude/sessions/2.json"
  printf '%s' "$2" > "$t/what"
  cat > "$t/cli" <<'C'
#!/bin/bash
d=$(dirname "$0"); pd=$d/claude/projects/-work-acme-widgets
case "$1 $2" in
  "workspaces list") echo '[{"id":"w1","worktreePath":"/work/acme/widgets"}]' ;;
  "terminals list") echo '{"sessions":[{"terminalId":"t1","createdAt":'$(cat "$d/created")'},{"terminalId":"t9","createdAt":5}]}' ;;
  "terminals read") n=$(($(cat "$d/n" 2>/dev/null || echo 0) + 1)); echo $n > "$d/n"
    if [ $n -eq 3 ]; then case $(cat "$d/what") in
      touch-old) touch "$pd/old-sess.jsonl" ;;
      own-envelope) cat "$d/own.line" >> "$pd/own-sess.jsonl" ;;
      own-foreign|foreign-back) cat "$d/foreign.line" >> "$pd/own-sess.jsonl" ;;
      own-then-foreign) cat "$d/own.line" "$d/foreign.line" >> "$pd/own-sess.jsonl" ;;
      late-envelope) mv "$d/late.json" "$d/claude/sessions/2.json" ;; esac; fi
    if [ $n -eq 4 ]; then case $(cat "$d/what") in
      foreign-back) cp "$d/own.old" "$pd/own-sess.jsonl" ;;
      late-envelope) cat "$d/own.line" >> "$pd/own-sess.jsonl" ;; esac; fi
    echo '{"text": "⏺ running the tests\n"}' ;;
  "snapshot --host") echo '{"workspaces":[{"terminals":[{"id":"t1","agent":{"state":"working"}}]}]}' ;;
esac
C
  chmod +x "$t/cli"; env_line x widgets-12 "mine" > "$t/own.line"; env_line x other-9 "not mine" > "$t/foreign.line"
  CLAUDE_CONFIG_DIR=$t/claude BOSS_HOST=m-7 BOSS_HOST_CLI=$t/cli BOSS_BIN=$t/none BOSS_WATCH_POLL_S=0 BOSS_WATCH_POLLS=$1 "$S" w1 t1 ${@:3} > "$t/out" 2>"$t/err" & local pid=$!
  for _ in $(seq 600); do kill -0 $pid 2>/dev/null || break; sleep 0.2; done; kill $pid 2>/dev/null; wait $pid 2>/dev/null
  head -1 "$t/out"; sed 's/^/stderr: /' "$t/err"; rm -rf "$t"; }
pinned(){ local name=$1 want=$2 got; shift 2; got=$(pin "$@" | tr '\n' '|' | sed 's/|$//')
  if [ "$got" = "$want" ]; then echo "ok   $name -> $got"; else echo "FAIL $name: want '$want', got '${got:-nothing in 120 s}'"; fail=1; fi; }
pinned "another session's old envelope in the newest transcript never fires" "TIMEOUT" 6 touch-old
pinned "the worker's own envelope fires" "ENVELOPE DONE|widgets-12|mine" 6 own-envelope
pinned "--task: its own task's envelope fires" "ENVELOPE DONE|widgets-12|mine" 6 own-envelope --task widgets-12
pinned "--task: another task's envelope in the worker's own transcript never fires" "TIMEOUT" 6 own-foreign --task widgets-12
pinned "no --task: that envelope fires" "ENVELOPE DONE|other-9|not mine" 6 own-foreign
# the host restarted: the terminal's createdAt is later than the session's startedAt; the one live session is still the worker's
CREATED=2000000000 pinned "host restart (createdAt after startedAt): the one live session is pinned, no stderr line" "ENVELOPE DONE|widgets-12|mine" 6 own-envelope
CREATED=2000000000 pinned "host restart: the older session's envelope in the newest file never fires" "TIMEOUT" 6 touch-old
# two live sessions: the one started closest after createdAt, else the most recently updated (said on stderr)
OLDLIVE=1 pinned "two live sessions: the one started after the terminal" "ENVELOPE DONE|widgets-12|mine|stderr: watch.sh: several live sessions in /work/acme/widgets; took the one started closest after the terminal" 6 own-envelope
OLDLIVE=1 CREATED=2000000000 pinned "two live sessions, host restart: the transcript that changed last" "ENVELOPE DONE|widgets-12|mine|stderr: watch.sh: several live sessions in /work/acme/widgets; took the one whose transcript changed last" 6 own-envelope
# a session started 1 s before the terminal must not beat the one started 1 s after it
OLDLIVE=1 OLDSTART=999000 pinned "two live sessions: at or after createdAt beats 1 s before" "ENVELOPE DONE|widgets-12|mine|stderr: watch.sh: several live sessions in /work/acme/widgets; took the one started closest after the terminal" 6 own-envelope
# another pane was registered first; the worker's session registers later: re-resolved, its later envelope still fires
OLDLIVE=1 LATE=1 pinned "the worker's session registers after the watcher started" "ENVELOPE DONE|widgets-12|mine|stderr: watch.sh: several live sessions in /work/acme/widgets; took the one started closest after the terminal" 8 late-envelope
# --task: the watched task's envelope followed by another task's in the same read still fires
pinned "--task: mine then another task's envelope in one batch fires mine" "ENVELOPE DONE|widgets-12|mine" 6 own-then-foreign --task widgets-12
# --task: another task's envelope never touches the baseline, so the old matching envelope coming back is not new
OWNOLD=1 pinned "--task: a foreign envelope does not reset the baseline" "TIMEOUT" 7 foreign-back --task widgets-12
got=$(NOREG=1 pin 6 touch-old | tr '\n' '|')
case "$got" in "ENVELOPE DONE|task-old|an older session|stderr: watch.sh: could not resolve the agent's own session; reading the newest transcript in "*"/projects/-work-acme-widgets (any session's)|")
  echo "ok   unresolved session: falls back to the newest transcript and says so on one stderr line";;
  *) echo "FAIL unresolved session fallback: '$got'"; fail=1;; esac
t_out=$(mktemp)
# a trailing --task without an id is a usage error, not a spin or an unfiltered watch
"$S" w1 t1 --task > "$t_out" 2>&1 & tp=$!   # a watcher that spins (the old behaviour) is killed after 10 s and counts as a failure
for _ in $(seq 50); do kill -0 $tp 2>/dev/null || break; sleep 0.2; done
if kill -0 $tp 2>/dev/null; then kill $tp; rc=spin; else wait $tp; rc=$?; fi; out=$(cat "$t_out"); rm -f "$t_out"
if [ "$rc" = 2 ] && echo "$out" | grep -q -- "--task needs a task id"; then echo "ok   trailing --task: usage error (exit 2)"; else echo "FAIL trailing --task: rc=$rc '$out'"; fail=1; fi
# --sig with --task: another id gives nothing, the same id its signature
out=$("$S" --sig --task other-1 <<'X'
│ BOSS_WORKER_DONE task: demo-task summary: did it
X
); if [ -z "$out" ]; then echo "ok   --sig --task other-1 on demo-task's envelope -> no fire"; else echo "FAIL --sig --task other: '$out'"; fail=1; fi
out=$("$S" --sig --task demo-task <<'X'
│ BOSS_WORKER_DONE task: demo-task summary: did it
X
); if [ "$out" = "DONE|demo-task|did it" ]; then echo "ok   --sig --task demo-task -> $out"; else echo "FAIL --sig --task same: '$out'"; fail=1; fi
exit $fail
