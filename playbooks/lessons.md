# Lessons (BOSS-template.md section 14, full wording)

The template keeps each rule of section 14 as one short line; this is the full wording, with its examples and steps. Read it before you add or promote a lesson.

When something was learned the hard way, record it in one of two layers, decided by one question: **would a boss on a different repo hit this too?**
- **No → project lesson:** this repo's quirks, its deploy process, its reviewers' conventions. `bin/boss-lesson add "<lesson>" --why "<what happened>"` writes `$BOSS_HOME/<project>/lessons.md`.
- **Yes → shared lesson:** tooling and process (watchers, permission prompts, terminals, git workflows). `bin/boss-lesson add "<lesson>" --shared --why "..."` writes `$BOSS_HOME/lessons.md`, tagged with your project and the date.
- `bin/boss-lesson promote <n>` copies a project lesson into the shared file when it turns out to hold everywhere, and marks the original as promoted.
- Both files are append-only and numbered; never renumber or rewrite an entry. The tool refuses an exact duplicate and warns on one that starts the same way. Read the warning before adding.
- A boss can propose a shared lesson to another by mail (`--kind fyi --subject "lesson: ..."`). The receiver decides whether to add or promote it.
- Your own open concerns that aren't lessons yet go in your boss folder's `notes.md`.
