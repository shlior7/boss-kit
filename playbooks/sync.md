# Conflict sync (BOSS-template.md section 7)

How-to detail for section 7. The rules stay in the template; where this file and the template differ, the template wins. Read it before you run the sync script, and before you brief a worker on a real conflict.

- The template's sync bullet says what `bin/boss-sync.py` does for each open PR.
- `--if-moved` = one `git ls-remote` against saved state; no `--push` = dry run.
- Run on demand: after every merge, before merge prep, or when asked. No recurring cron.
- Real conflicts go to the owning session with a short brief (merge base, keep both sides, regenerate indexes, run tests, push, reply new head sha).
