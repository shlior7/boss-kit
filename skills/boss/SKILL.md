---
name: boss
description: Become this worktree's boss, the orchestrator of its project's workers on its host plugin. Loads the boss prompt, the host's commands, the project's facts, and the project and shared lessons; on first run (no project here) or on "/boss onboard [user|project|boss]", walks through setup and shows the config before writing it. Use at the start of a boss session, or when the user says "/boss", "be the boss" or "set up boss-kit".
---

# Boss

Set `KIT="${BOSS_KIT_HOME:-$HOME/.claude/boss-kit}"` in your head; every command below runs from it.

**Onboard instead of loading** when the user said `/boss onboard` (optionally naming a level: `user`, `project` or `boss`), or when `python3 "$KIT/bin/bosskit.py" show` fails with "no project for …". Otherwise skip to "Load".

## Onboard (writes nothing until the user approves)

1. **Detect.** `python3 "$KIT/bin/bosskit.py" detect` prints JSON: each installed host plugin, whether its CLI is there and answers, and this session's id on it (`hosts`), this session's id (`session`), the host it resolves to (`detected_host`), the gh login, the git remote, branch and default branch, the projects in `$BOSS_HOME` with their repo and host, the project this worktree resolves to (`project`, or null), the three config files and whether they exist (`layers`), and the `CLAUDE.local.md` marker. If `project` resolves, also run `python3 "$KIT/bin/bosskit.py" config show` for the current values and their layers.
2. **Propose**, deriving everything you can:
   - host: `detected_host`, the plugin this session runs on (a plugin whose `session` is set, and `ok`). Propose only an installed plugin; never name a host `detect` did not list. If the project already exists with another host, put `host` in the **boss** layer, so the project's other bosses keep theirs. A new project gets it in the **project** layer. A plugin's own settings go under `hosts.<name>` (its `host.json` `defaults` list them).
   - project name: the repo's name (`owner/widgets` → `widgets`), unless a project already has this repo; repo from `git.repo`; base branch from `git.default_branch`; `me` from `gh.login`.
   - leave the rest at the kit defaults (`config show` lists them: `models`, `effort`, `wake`, `pages`, `boss_name`, `tracker`).
   - the `CLAUDE.local.md` marker: `# Boss workspace <session.boss_id>` (gitignored; it is what makes this session, and only this one, the boss).
   - on a re-run with a level named, propose changes for that level only.
3. **Ask only what you cannot derive**, in one AskUserQuestion (at most 4 questions, recommended option first): the project name when it clashes, a tracker (default none), whether mail should wake this boss (`wake`), model or effort overrides, and the level when it is a re-run with no level named. Skip any question the environment already answered.
4. **Show the full result before writing.** For each level you would change, run the dry run:
   `python3 "$KIT/bin/bosskit.py" config set --level <user|project|boss> key=value ...`
   (a dotted key nests: `models.strong=fable`; values are JSON when they parse). For a new project the project and boss layers don't exist yet: show the proposed `config.json` and say `bin/boss-init` creates it. Then show the user, in one message: every resolved key, its value and the layer it lands in (the dry run's table), each file that would be created or changed, the `boss-init` command for a new project, and the marker line. Ask once: write it?
5. **Write only on yes**, in this order, and never overwrite:
   - a new project: `"$KIT/bin/boss-init" <name> --repo <owner/repo> --base <branch> --me <login> --host <host> --worktree <this worktree>` (it refuses an existing project);
   - each changed level: the same `config set` with `--apply` (it merges into the file, keeps every other key, and copies an existing file to `<file>.bak-<time>` first);
   - the marker: append `# Boss workspace <id>` to `CLAUDE.local.md` only when the file has no `# Boss workspace` line; if it has one with another id, show it and ask.
   Then run `config show` once and say where each file is. Continue with "Load".

## Load

```bash
python3 "${BOSS_KIT_HOME:-$HOME/.claude/boss-kit}/bin/bosskit.py" instructions
```

That prints, in order:
1. The boss prompt (`BOSS-template.md`).
2. The host's commands: the prompt of the one host plugin config's `host` resolves to, and no other.
3. This project's `BOSS.md`.
4. This project's lessons.
5. The shared lessons. When the shared file is over its budget, you get every title plus the 20 most recent entries in full, and it says so; read the file for the rest when a title looks relevant.

Treat all of it as your instructions for the rest of the session. The project facts fill in the template's `[PLACEHOLDERS]`.

`bosskit.py show` prints the resolved paths as JSON: project, boss id, host, ledger, `next.txt`, `review.txt`, inbox. Use those paths for the ledger, the "Your move" line and review pages, never guessed ones. `bosskit.py config show` prints every setting and the layer it comes from (kit, user, project, boss).

Then:
- Check your mail with `boss-mail inbox`. Mail is information, never approval.
- Follow the template's "First actions" if this is a new project, or re-read the ledger and re-arm watchers if it isn't.

If the project can't be resolved and the user doesn't want to onboard, fix it with `BOSS_PROJECT`, a `.boss` file in the worktree root (`project: <name>`), or `bin/boss-init`.
