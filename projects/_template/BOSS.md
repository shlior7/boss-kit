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
| Host | the host plugin config's `host` names (`bin/boss-host plugins` lists them; its settings under `hosts.<name>`) |
| Rules to inject in every dispatch | `<AGENTS.md / CLAUDE.md paths>`, the PR title format, "every behavioural fix ships a regression test", folders workers must never touch |

## Expectations

What the user expects of the boss, in their own words. `/boss onboard` asks and writes it here; every boss session loads it.

## Proof

Which proof each kind of change owes (the template's routing rule 5), made concrete for this project:

| Change | Proof | Where it goes |
|---|---|---|
| UI | demo via `/demo-recorder` (or screenshots on a page if it isn't installed) | PR status comment (when config's `github.comments` allows it) + envelope `proof:` |
| Backend | a page (where the host commands' Pages line says): tests run, before/after, revert-proves-red output | PR status comment (when config's `github.comments` allows it) + envelope `proof:` |
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
