# Spec-Driven Development — how this repository is built

Every change to this repository goes through a written spec before code, and through an
independent, measured validation after code. This file is the process; `CONSTITUTION.md`
is the rules that hold in every phase; `_index.md` is the live status.

## Lifecycle

| # | Phase | Artifact (in `features/<FEATURE>/`) | Exit gate |
|---|-------|-------------------------------------|-----------|
| 0 | Brainstorm | `BRAINSTORM_<FEATURE>.md` | A direction is chosen. *Optional for small features.* |
| 1 | Define | `DEFINE_<FEATURE>.md` | Approved. Clarity ≥ 12/15. **Scope freezes here.** |
| 2 | Design | `DESIGN_<FEATURE>.md` | Independent design review recorded (second opinion). |
| 3 | Build | code + `BUILD_REPORT_<FEATURE>.md` | CI green. Every PR cites a `REQ-xx`. |
| 4 | Validate | `VALIDATION_<FEATURE>.md` | Every acceptance test has a **measured** result, by a reviewer who did not build it. |
| 5 | Ship | `SHIPPED_<YYYY-MM-DD>.md` | Ship gates checked; durable decisions promoted to ADRs; folder moved to `archive/`. |
| 6 | Retro | `RETRO_<FEATURE>.md` | Its *Changes Applied* diff is merged. Part of the Ship gate. |

Templates live in `templates/`. Brainstorms not yet promoted live in `backlog/`.

## Where a decision lives

- **While a feature is active**, a decision lives inline in its DESIGN, under *Key Decisions*,
  next to the code it shapes.
- **At Ship**, every decision with lasting value is promoted to a numbered ADR in `docs/adr/`,
  and the DESIGN links to it. From then on the ADR is the single source of truth.
- A decision that only made sense inside the feature stays in the archived DESIGN.

## Fast track

A change qualifies when it touches no schema, no data contract and no infrastructure, and fits
in one small PR. It skips Brainstorm and Design — **never** the mini-DEFINE (one paragraph +
one acceptance test, in `_index.md`) and **never** Validate. The Constitution applies in full.

## Parallel work

- A feature folder is the unit of parallelism. An agent working on a feature loads only that
  folder, `CLAUDE.md`, `CONSTITUTION.md` and the skills listed in its DEFINE.
- Two features may run in parallel only if their **File Ownership** sets do not intersect.
- One git worktree / branch per feature. Integration happens only through PR + CI.
- Files listed as *Shared — serialize* in `_index.md` have one writer at a time.
- The practical limit is review bandwidth, not agents: no more features in Build than the
  owner can review the same day.

## What the client sees (when this blueprint is used on an engagement)

The client approves the **DEFINE** and receives the **Ship** (code, runbooks, validation
evidence). Brainstorm, design review and retro are internal working practice.
