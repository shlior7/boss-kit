# BOSS — {{PROJECT}} project facts

The role, mandate, hard rules, routing, envelope, verification, merge and reporting rules are in
`BOSS-template.md` at the kit root (the `/boss` skill loads it, this file, and the lessons). Every rule there applies. This file fills in its
`[PLACEHOLDERS]` for {{PROJECT}}. Machine-readable values live next to it in `config.json`.

| Fact | Value |
|---|---|
| Boss workspace | `<workspace id>` (name, branch, worktree path) |
| Repo | main checkout `<path>`; worktrees under `<path>` |
| GitHub | `<owner/repo>`, base branch `<main>` |
| Me on GitHub | `<login>`. **Only my PRs are mine to sync and push.** Other authors' PRs are read-only: report only |
| Tracker | `<none / HTTP JSON endpoint>`; workers stay read-only on it |
| Paradev host | `<host id>` (`superset hosts list --json`). Export `BOSS_HOST` for the watcher |
| PRs stay draft | `<no / yes>`. Yes when PRs stay draft until a human marks them ready: the PR sweep then counts a draft with green checks as finished, and the watcher runs with `BOSS_DRAFT_DONE=1` |
| Rules to inject in every dispatch | `<AGENTS.md / CLAUDE.md paths>`, the PR title format, "every behavioural fix ships a regression test", folders workers must never touch |

## Proof

Which proof each kind of change owes (the template's routing rule 5), made concrete for this project:

| Change | Proof | Where it goes |
|---|---|---|
| UI | demo via `/demo-recorder` (or screenshots on a page if it isn't installed) | PR comment + envelope `proof:` |
| Backend | Superset page: tests run, before/after, revert-proves-red output | PR comment + envelope `proof:` |
| Read-only / docs | `proof: none: <why>` | envelope |

Notes: `<how to start the app for a demo, test accounts or sites to record on, pages that must not show real data>`

## Commands that verify

```bash
<backend test command>
<frontend typecheck / test / lint>
```

## Project notes

Facts the boss learned the hard way about this project (deploy timing, flaky CI jobs, who reviews
what). Keep them short and dated.

## Ledger and lessons

`ledger.md` in this folder is shared by every boss of this project; re-verify any fact there before acting on it.
`lessons.md` holds this project's lessons (`bin/boss-lesson add`). Lessons that hold for any repo go to the shared file.
