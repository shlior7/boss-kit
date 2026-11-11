# BOSS — {{PROJECT}} project facts

The role, mandate, hard rules, routing, envelope, verification, merge and reporting rules are in
`BOSS-template.md` at the kit root. Every rule there applies. This file fills in its
`[PLACEHOLDERS]` for {{PROJECT}}. Machine-readable values live next to it in `config.json`.

| Fact | Value |
|---|---|
| Boss workspace | `<workspace id>` (name, branch, worktree path) |
| Repo | main checkout `<path>`; worktrees under `<path>` |
| GitHub | `<owner/repo>`, base branch `<main>` |
| Me on GitHub | `<login>`. **Only my PRs are mine to sync and push.** Other authors' PRs are read-only: report only |
| Tracker | `<none / HTTP JSON endpoint>`; workers stay read-only on it |
| Paradev host | `<host id>` (`superset hosts list --json`). Export `BOSS_HOST` for the watcher |
| Rules to inject in every dispatch | `<AGENTS.md / CLAUDE.md paths>`, the PR title format, "every behavioural fix ships a regression test", folders workers must never touch |

## Commands that verify

```bash
<backend test command>
<frontend typecheck / test / lint>
```

## Project notes

Facts the boss learned the hard way about this project (deploy timing, flaky CI jobs, who reviews
what). Keep them short and dated.

## Ledger

`ledger.md` in this folder. Re-verify any fact there before acting on it.
