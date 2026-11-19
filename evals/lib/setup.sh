#!/bin/bash
# Scaffold shared by every boss eval case: run by `claude plugin eval --scaffold` in the case's empty cwd, under the
# eval's own temp HOME (never the real ~/.boss). It makes cwd a boss worktree of the project "evalproj" on the test
# host, renders what /boss loads into BOSS-INSTRUCTIONS.md, copies the case's state/ (captured tool output) in, and
# stubs the kit commands the boss acts with.
#   setup.sh <case dir>     the case's scaffold.sh passes its own folder
set -euo pipefail
CASE=$(cd "${1:?usage: setup.sh <case dir>}" && pwd)
KIT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
case "$HOME" in /tmp/*|/private/tmp/*|/var/folders/*) ;; *) echo "setup.sh: HOME=$HOME is not a temp home; refusing" >&2; exit 1;; esac
export BOSS_HOME="$HOME/.boss" BOSS_KIT_HOME="$KIT" BOSS_HOST_PATH="$KIT/tests/hosts"
git init -q -b main . && git -c user.email=e@x -c user.name=eval commit -q --allow-empty -m init
printf '# Boss workspace\n' > CLAUDE.local.md
"$KIT/bin/boss-init" evalproj --repo acme/widgets --base main --me ada --host fake --worktree "$PWD" >/dev/null
python3 "$KIT/bin/bosskit.py" instructions > BOSS-INSTRUCTIONS.md
[ -d "$CASE/state" ] && cp -R "$CASE/state" ./state
# The commands the boss acts with are stubs: they log their argv to calls.log and change nothing. evals/run grants Bash
# only for these, so every other command (gh, git push, ...) is refused, and still shows in the trace for the graders.
mkdir -p bin
for c in boss-host boss-merge boss-mail boss-event boss-status-ask boss-lesson boss-sync.py; do
  printf '#!/bin/sh\necho "%s $*" >> "%s/calls.log"\necho "replay: recorded, not run"\n' "$c" "$PWD" > "bin/$c"
  chmod +x "bin/$c"
done
echo "scaffold ok: $(wc -c < BOSS-INSTRUCTIONS.md) bytes of instructions"
