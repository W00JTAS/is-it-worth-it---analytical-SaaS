# IS_IT_WORTH_IT

This project has a web/visual UI ("Z stroną").

<!-- Sections worth adding as the project accumulates real answers — skeleton lives in
     ../../.claude/skills/new-project/templates/project-CLAUDE.md:
       - Domain decisions the repo doesn't explain
       - Commands you couldn't guess
       - Traps: looks standard, behaves differently   <- highest value, hardest to derive
       - Conventions that differ from the defaults
       - Definition of done (this project)
       - This project's extensions (index, not content)
     Add a section only when there is a concrete entry for it. Empty headings cost tokens every
     turn and teach nothing. -->

## Learning loop and handoffs

Governed by `~/.claude/rules/project-learning-loop.md` (machine-wide) — it used to be copied in here
verbatim. Two deltas that are true for this repo specifically:

- The mechanism is not theoretical here: a lesson living only in a handoff was broken by the next
  implementer **four times in this project's first four sessions**.
- The knowledge-debt hooks are wired (`.claude/hooks/session-start.sh` / `session-end.sh`), so the
  `session_id:` line at the top of a handoff is mandatory — without it the next session falsely
  reports unpaid debt.

## Whole-branch review

Before merging a phase, run the `repo-reviewer` subagent. It keeps its own memory of bug classes
this repo has already produced, with a detector command for each, and adds to it after every review.
Every bug that mattered here was caught by a whole-branch review and none by `npm test`,
`npm run build` or `npm run lint` — all of which passed while the bugs were live.
