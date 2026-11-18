---
name: sdd-fasttrack
description: SDD fast track for small changes with one acceptance test. Run only when the user types /sdd-fasttrack <FT-id>.
disable-model-invocation: true
---

# SDD fast track

Usage: `/sdd-fasttrack <FT-id or short description>` — e.g. `/sdd-fasttrack FT-04`.

## Ground rules

- Read `CLAUDE.md`, `.claude/sdd/CONSTITUTION.md`, `.claude/sdd/README.md` (*Fast track*) and
  `.claude/sdd/_index.md` first.
- Reply to the user in Brazilian Portuguese. Write every repository file in English.
- The Constitution applies in full (no `apply`, no destructive commands, no secrets).

## Task

1. **Check eligibility.** A fast track touches no schema, no data contract and no infrastructure, and
   fits in one small PR. If the change does not qualify, say why and suggest `/sdd-define` instead.
   Stop.
2. If the item is not yet in the *Fast tracks* table of `_index.md`, add it with a one-paragraph
   mini-DEFINE and **one** acceptance test. Wait for the user's OK.
3. Check the ownership map: do not touch a path owned by an active feature.
4. Present the plan, wait for OK, build on a branch `ft/<id>`, run the linters and tests.
5. Verify the acceptance test and record the evidence in the *Fast tracks* table (status Done + link
   to the PR). The user, not you, confirms it.
6. Run `python3 tools/build_sdd_package.py`, commit and show the PR command.
