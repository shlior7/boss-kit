# Domain boss (BOSS-template.md section 15)

How a domain boss works. `bosskit.py instructions` loads this file for every domain boss (a `Domain:` line in `CLAUDE.local.md`); the rules in section 15 of the template still hold, and where this file and the template differ, the template wins.

`bosskit.py instructions` then also loads `<project>/domains/<name>.md` (the charter: scope, powers, limits) and `<name>-state.md` (your own running notes: what is open, decided, risky).
- You share the project's ledger and lessons with the main boss. Prefix your ledger lines with the domain name, and read the ledger at the start of a session for work that touches your domain.
- You own one sidebar folder: the `Folder: <tag>` line next to `Domain:` in `CLAUDE.local.md` (spaces allowed, matched case-insensitively), else the domain name. Put every workspace you create in it (`boss-host create --folder`). The main boss (no `Domain:`) sees every folder.
- Keep `<name>-state.md` current: it is the memory that makes you the one who knows the domain. Update it after every dispatch, merge and decision.
- A domain boss is allowed, and expected, to push back, raise concerns and propose opportunities; see the charter's duties.
- **Every workspace you create branches from that main branch** (the host commands say how), then check it in the new worktree before any work (`git merge-base --is-ancestor origin/<main> HEAD`, and `git log origin/<main>..HEAD` empty for a fresh branch); reset an untouched new branch to `origin/<main>` when the check fails. PRs from those workspaces target `<main>`.
