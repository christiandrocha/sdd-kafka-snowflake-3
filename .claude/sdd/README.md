# Spec-Driven Development — how this repository is built

Every change to this repository goes through a written spec before code, and through an
independent, measured validation after code. This file is the process; `CONSTITUTION.md`
is the rules that hold in every phase; `_index.md` is the live status.

## Lifecycle

| # | Phase | Cursor command | Chat | Artifact (in `features/<FEATURE>/`) | Exit gate |
|---|-------|----------------|------|-------------------------------------|-----------|
| 0 | Brainstorm | `/sdd-brainstorm <FEATURE> <idea>` | any | `BRAINSTORM_<FEATURE>.md` (in `backlog/`) | A direction is chosen. *Optional for small features.* |
| 1 | Define | `/sdd-define <FEATURE>` | any | `DEFINE_<FEATURE>.md` | Approved by the owner. Clarity ≥ 12/15. **Scope freezes here.** |
| 2 | Design | `/sdd-design <FEATURE>` | any | `DESIGN_<FEATURE>.md` | Independent review signed off → version 1.0. |
| 2b | Review | `/sdd-review <FEATURE>` | **new**, Ask mode | — (answer only) | READY FOR BUILD. Blockers only; everything else is a Build note. |
| 3 | Build | `/sdd-build <FEATURE> <items>` | any, Agent mode | code + `BUILD_REPORT_<FEATURE>.md` | CI green. Every PR cites a `REQ-xx`. One PR per command. |
| 4 | Validate | `/sdd-validate <FEATURE>` | **new** | `VALIDATION_<FEATURE>.md` | Every acceptance test has evidence, by a session that did not build it. |
| 5 | Ship | `/sdd-ship <FEATURE>` | any | `SHIPPED_<YYYY-MM-DD>.md` | Ship gates checked; durable decisions promoted to ADRs; folder moved to `archive/`. |
| 6 | Retro | `/sdd-retro <FEATURE>` | any | `RETRO_<FEATURE>.md` | Its *Changes Applied* diff is merged. Part of the Ship gate. |
| — | Fast track | `/sdd-fasttrack <FT-id>` | any | row in `_index.md` | One acceptance test with evidence. |
| — | Status | `/sdd-status` | any | — (read-only) | — |

The commands live in `.cursor/commands/` and are the executable form of this table: if the process
changes, the command file changes in the same PR (the Retro checks it).

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
