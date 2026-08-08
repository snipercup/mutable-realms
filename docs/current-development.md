# Current Development

Mutable Realms develops one idea at a time. This document tracks the single active idea and the recently closed trail. It is not a backlog: ideas that are interesting but not being worked on belong in [maintenance-guide.md](maintenance-guide.md) under *Known deferred work*; finished ideas are recorded there under *Development history*.

## Active idea

_None yet. When an idea arrives, it is scoped here before implementation using the template below._

### Idea title — proposed | scoped | in progress | complete | abandoned

- **Goal:** one paragraph describing what the idea should make possible.
- **Scope:** what changes (backend / frontend / docs / tests) · what is deliberately out of scope.
- **Verification:** how success will be checked — suite/lint, deterministic CLI seam, browser readback, narration-profile live turn.
- **Commit:** branch + commit message once pushed to main.

## Recently completed

| Idea | Completed | Commit |
| --- | --- | --- |

## How an idea becomes work

1. **User describes the idea in prose** — no format required.
2. **Restate as a scoped slice** — goal, what changes, what is out of scope, how to verify. Follow the vertical-slice pattern in the maintenance guide (migration → operation → context → validation → agent surface → turn policy → docs → tests) unless the idea is presentation-only.
3. **Record the scope here** (status: scoped / in progress) before implementing.
4. **Implement and verify** — full suite, lint, and live verification proportional to risk.
5. **Flip status to complete** with verification evidence and a suggested branch + commit message; the user commits and pushes.
6. **Close the entry.** If the idea is postponed mid-way, move it as one line into the maintenance guide's *Known deferred work* table and mark it abandoned here.

Notes on the process, learned during the plan era and still enforced:

- One supported mutation per narrated turn; authoritative state is SQLite; narration and visualization are derived views.
- Never claim a capability works without real verification output (tests + live evidence).
- Keep the tracker small: one active idea, a short closed trail, no backlog accumulation.
