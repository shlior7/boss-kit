# Shared boss lessons

Lessons that hold for every boss, whatever the repo: tooling and process. Append-only and numbered;
never renumber. Add with `bin/boss-lesson add "<text>" --shared --why "..."`, or promote a project
lesson with `bin/boss-lesson promote <n>`. `boss-init` copies this file to `$BOSS_HOME/lessons.md`
the first time.

## 1. Match the envelope only line-anchored, and never by counting (seed)
An envelope name matched anywhere also matches the dispatch prompt you just sent, and old envelopes scroll out of the read window, so counts drift. Compare the latest line-anchored envelope's `task:` line to the one at the start, and skip templates whose fields still read `<placeholder>`.
Why: a watcher fired on its own prompt's envelope template.

## 2. A permission prompt reads as agent state "blocked" (seed)
New agents can start in default permission mode, and the first command that needs approval looks like a blocked worker. Read the screen before treating a fire as a real block. Answer read-only command prompts with "Yes, and switch to auto mode", never bypass, then re-arm the watcher.
Why: a worker that was only waiting on a `git fetch` approval looked stuck.

## 3. A restart kills every watcher (seed)
Background watchers die with the boss session. On resume, read each worker's screen for an envelope that landed meanwhile, then re-arm. Never assume a silent worker is still running.
Why: several workers finished while no watcher was alive, and the boss reported stale state.

## 4. A message typed into a busy session can be lost (seed)
Text sent while a worker is mid-turn can be dropped when it goes idle. After it finishes, check that it picked up the follow-up; resend if not. Clear a staged input line first (`--keys ctrl+u`): idle sessions often show an auto-suggestion that is not yours.
Why: a queued follow-up never ran, and the next prompt landed glued to a suggestion.

## 5. Idle detection misfires during long CI waits (seed)
A worker polling CI can sit on an unchanged screen. On a fire with no envelope, read the screen and GitHub before acting, and ask the worker to report pending checks as pending and finish with the envelope.
Why: a worker stopped "waiting for CI" and never sent its envelope.

## 6. In a terminal pane, prefer a plain Button over Link (seed)
Terminals without OSC 8 hyperlinks draw a `Link` as its text followed by the whole URL, which wraps in a narrow pane. A chrome-free `Button plain` that opens the URL reads clean everywhere.
Why: PR links printed full URLs across the pane.

## 7. Never edit a watcher script while watchers run (seed)
A running bash script reads itself as it goes, and an edit corrupts every running watcher. Write a new versioned file and re-arm.
Why: an in-place edit broke watchers that were mid-poll.

## 8. Squash merges make every stacked PR conflict (seed)
After a base PR is squash-merged, its stacked PRs carry the base's original commits. Merging master gives real conflicts in every file both touched. Resolve by taking master's version of everything the base owned, then re-applying only the stacked PR's own change, and prove it with `git diff origin/<base>...HEAD`.
Why: three stacked PRs conflicted at once after one squash merge.

## 9. Claude Code draws the envelope inside a reply box (2026-11-11, quack)
A reply renders as `│ SUPERSET_WORKER_DONE task: x summary: ...` with the side pane on the same line, so a regex that wants the name alone on its line never matches, and every fire is the idle fallback (late, and false while a background shell runs). Strip the box characters and the side pane, find the name anywhere, read its `task:` value, and test the parser on a captured screen.
Why: six watcher fires in a row were idle fallbacks; three of them hid real envelopes.

## 10. The boss's own work is invisible: put it in a workspace (2026-11-11, quack)
The boss fixed two prod bugs, resolved five merge conflicts and ran a research agent inside its own session. None of it showed on the board, and the user asked to watch the research. Only boss-level work stays in the boss session (template section 5 rule 0); a prod fix gets a new workspace at once, a PR's conflicts go to its owner.
Why: the user said "everything boss does should be a separate workspace; only high level boss tasks are done on the boss itself".

## 11. A host restart kills worker terminals too (2026-11-11, quack)
Not only watchers die: relaunch each worker in its SAME workspace with `superset terminals create --local --workspace <id> --command "command claude --dangerously-skip-permissions --continue"` so it keeps its conversation, check git status, /compact if context is high, resend its orders and re-arm watchers on the NEW terminal ids.
Why: a Paradev host restart ended four worker sessions mid-task.

## 12. Close done workspaces as you go (2026-11-11, quack)
Retire an implementation workspace once its PRs are merged and verified with nothing queued, and sweep the board at every status report. Keep research workspaces: research often turns into the implementation in the same conversation. Copy any ignored output worth keeping (a rendered video, audio) out of the worktree first: archiving deletes the folder.
Why: finished workspaces piled up on the board and the user had to ask for them to be closed. Then the boss archived a research workspace the moment it reported DONE while the user was still working in it; a local archive deletes the worktree, and only `claude --continue` in a new workspace on the same branch and path got the conversation back.

## 13. A workspace is a full worktree: only for code that becomes a PR (2026-11-11, quack)
Research, ops and checks ran in fresh workspaces, each a full copy of the repo with its own install. Give them a new agent session instead: in the workspace the work belongs to, or as another session in the boss workspace on the base branch when no files change.
Why: the user: "creating a workspace is creating a worktree which copies all the repo, only do it for real changes".

## 14. Group workspaces by concern, and keep their names current (2026-11-11, quack)
Seven workspaces sat in one flat list with names like "build (PR #4)" and "notes #8 + account" that no longer said what they did. Tags (`superset workspaces update <id> --local --tag <group> --name <name>`) file them into sidebar folders by area; the boss suggests a regrouping as it learns the project.
Why: the user asked for groups, and for the boss to propose reorganizations over time.

## 15. Two finished PRs sat unnoticed: the boss had swapped its watcher for `terminals wait` (2026-11-11, quack)
After one false positive, the boss replaced `boss-watch-done.sh` with `superset terminals wait --match "<one-line regex>" --max-lines 30`. Claude Code drew a worker's whole reply at once, and the envelope's first line landed 48 rows up, outside the 30-row window. Another worker split the envelope over two lines. Neither matched, `terminals wait` has no idle fallback, and both PRs had already left draft without anyone checking GitHub.
Why: the user noticed workspaces "done and nothing occurred". The fix is the script plus a PR sweep every turn: fix the watcher, never bypass it, and keep one check that does not read the screen.

## 16. Permission mode follows the user's default (2026-11-12)
Lesson 2 said never bypass, and lesson 13 relaunched workers with `--dangerously-skip-permissions`. Use the mode the user runs: auto, or bypass when that is their default; relaunch and answer prompts in it. Anything that writes outside the task still needs the user.
Why: two bosses on a clean relearn flagged lessons 2 and 13 as contradicting each other.

## 16. Ask to close a workspace as soon as it is done (2026-11-12, quack)
Done workspaces sat on the board until the user asked, more than once, to "close all finished workspaces". Now the boss asks in the next message, naming each workspace with its merged PRs and the leftover check. It closes on a yes, or at once under a standing cleanup OK, and keeps asking at each report until answered.
Why: the user wants cleanup offered, not left for them to notice, and to stay the one who approves it.
