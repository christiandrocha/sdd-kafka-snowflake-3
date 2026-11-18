---
name: sdd-status
description: SDD status report (read-only). Run only when the user types /sdd-status.
disable-model-invocation: true
---

# SDD: status

Read-only. Do not edit any file.

## Ground rules

- Read `CLAUDE.md`, `.claude/sdd/CONSTITUTION.md` and `.claude/sdd/_index.md` first.
- Reply to the user in Brazilian Portuguese.

## Task

1. From `.claude/sdd/_index.md`, list every feature and fast track with its current phase.
2. For each active feature, open its folder in `.claude/sdd/features/<FEATURE>/` and check which
   artifacts exist (DEFINE, DESIGN, BUILD_REPORT, VALIDATION, SHIPPED, RETRO) and their version and
   status lines. Flag any mismatch between `_index.md` and the files.
3. List the open items in `_index.md` that block the next step, and today's position in the
   15-day plan.
4. Run `python3 tools/build_sdd_package.py --check` and report whether the package is stale.

## Answer format

- A table: feature · phase · last artifact (version) · next step · next command to run.
- Blocking items, if any.
- One line: the single most important thing to do next.
