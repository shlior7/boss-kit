# Org layer: Acme

Copy to `$BOSS_HOME/org.md` (local only, never pushed). Loaded for every boss on this machine after the host commands and
before the project's `BOSS.md`: what holds for every Acme project, so no project repeats it. A project's `BOSS.md`
overrides this file; this file overrides the template.

## Pages and proof
- Every page (worker proof, research, review pages) is published to example-pages, never anywhere else:
  a self-contained `index.html` in a folder, then `example-pages deploy <dir> --json`. Report the printed URL.
- Proof URLs look like `https://pages.example.com/<slug>/` (`proof_urls` in `org.json` lets the pane find them).
- Open each page before reporting it: it must load and show this change.

## GitHub (org `acme`)
- Repos live under `acme/` (say, `acme/widgets`); `jane` reviews anything touching billing.

## People and approvals
- Chat posts, merges, prod writes and spend wait for the user, in their own words.
