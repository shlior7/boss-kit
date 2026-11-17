# Watcher, PR sweep and stage log (BOSS-template.md section 6)

How-to detail for section 6. The rules stay in the template; where this file and the template differ, the template wins. Read it when you arm your first watcher in a session, and when one fires oddly or misfires.

## The envelope on screen
The whole envelope stays under 15 rows because a poll reads only the bottom of the screen. A long envelope pushes its first line off the screen before a poll sees it.

## What fires the watcher
`bin/boss-host watch <workspace> <branch>` runs in the background until something happens. It fires on a new envelope, when the branch's PR gets a DONE comment, leaves draft or merges (PR READY), when the agent waits on someone (blocked), after a few idle minutes without an envelope, or when the workspace is gone, and logs the stage. The host commands say how it reads the envelope.

## PR sweep
While workers run, each watcher does this sweep for its own `<branch>` in the background: it fires `PR READY` when that branch's PR gets a DONE comment, leaves draft, or merges. Your own sweep, at every turn and every report, covers every open PR, including those no watcher looks at.

## Stage log
The pane reads `events.jsonl` for each workspace's stage (your move, boss checking, working, blocked, in review, idle, done today), its time in stage and its expanded timeline. Each `boss-host send` is logged as that workspace's `msg` event; the worker's own pane shows them under FROM BOSS.
