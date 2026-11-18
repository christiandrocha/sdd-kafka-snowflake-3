---
name: sdd-ship
description: SDD phase 5 - promote decisions to ADRs, update README, archive the feature. Run only when the user types /sdd-ship <FEATURE>.
disable-model-invocation: true
---

# SDD phase 5: Ship

Usage: `/sdd-ship <FEATURE_NAME>`

## Ground rules

- Read `CLAUDE.md`, `.claude/sdd/CONSTITUTION.md` and `.claude/sdd/_index.md` first.
- The VALIDATION verdict must be PASS or PASS WITH NOTES. Otherwise say so and stop.
- Reply to the user in Brazilian Portuguese. Write every repository file in English.

## Task

1. **Promote durable decisions.** For each *Key Decision* in the DESIGN, decide with the user
   whether it has lasting value. Each durable one becomes a numbered ADR in `docs/adr/` (next free
   number, existing ADR format) and the DESIGN links to it. Decisions that correct an older ADR
   supersede its wording explicitly.
2. Update the README sections the feature changed (numbers must match the VALIDATION, each with the
   query that produced it) and list unverified claims under *Known gaps*.
3. Run the retro: `/sdd-retro <FEATURE_NAME>` must be done before the next step — the Ship gate
   requires its *Changes Applied* table to be merged.
4. Write `SHIPPED_<YYYY-MM-DD>.md` from the template and tick every *Ship Gate*.
5. Move `.claude/sdd/features/<FEATURE_NAME>/` to `.claude/sdd/archive/<FEATURE_NAME>/` and update
   `_index.md` (phase Shipped, ownership released). The package script reads only
   `.claude/sdd/features/`, so a shipped feature leaves the package by design; remove it from
   `FEATURES` in `tools/build_sdd_package.py`.
6. Run `python3 tools/build_sdd_package.py`, commit citing the feature, and show the PR command.

## Exit

Feature shipped; its owned paths are free for other features.
