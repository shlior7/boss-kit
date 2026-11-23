# Reporting format (short, action-first) (BOSS-template.md section 9, full wording)

The template keeps each rule of section 9 as one short line; this is the full wording, with its examples and steps. Read it before your first report in a session.

- First line = my next action, or "nothing needed". At most 3 items needing me, each naming the workspace to open.
- Then URGENT / NEXT / CAN WAIT / FYI one-liners. Lists capped at 5. Numbered steps for multi-step. Concrete time estimates. Make wins visible.
- Decisions: one question, recommended option first, trade-off in one line.
- No preamble, no recap, no closing pleasantries. URLs as [Title](url). Restate stack state each turn. End with "Your move: <one concrete action>", and write that same line to this boss's `next.txt` (the path `bosskit.py show` prints; the boss-deck pane shows it).
- Voice mode: plain sentences, no tables or symbols, spell out PR numbers.
- On a background-task notification, answer from the verified result.
- One "with you" line per manual worker (the user working in its session by hand): its workspace, what the user is doing there in a few words (the `manual` event, its `notes.md`), and how it fits the plan or the stack, e.g. "with you: webhooks, hand-tracing the retry loop; feeds fix-42, no conflict".
- Link each finished task's proof next to its PR ([demo](url), [page](url)), and say plainly when a PR has none.
