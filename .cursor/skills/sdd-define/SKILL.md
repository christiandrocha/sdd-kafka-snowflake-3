---
name: sdd-define
description: SDD phase 1 - write or revise a feature DEFINE (requirements, acceptance tests). Run only when the user types /sdd-define <FEATURE>.
disable-model-invocation: true
---

# SDD phase 1: Define

Usage: `/sdd-define <FEATURE_NAME>`

## Ground rules

- Read `CLAUDE.md`, `.claude/sdd/CONSTITUTION.md` and `.claude/sdd/_index.md` first.
- The feature name comes after the command. If it is missing, ask and stop.
- Reply to the user in Brazilian Portuguese. Write every repository file in English.
- No code and no design in this phase: *what* and *why*, never *how*.

## Task

1. Read `.claude/sdd/templates/DEFINE_TEMPLATE.md` and, if it exists,
   `.claude/sdd/backlog/BRAINSTORM_<FEATURE_NAME>.md`.
2. If `.claude/sdd/features/<FEATURE_NAME>/DEFINE_<FEATURE_NAME>.md` already exists and is
   **Approved**, do not rewrite it. Scope is frozen: propose a new revision, list exactly what
   changes and why, and wait for the user's OK before editing.
3. Otherwise create the folder and the DEFINE from the template:
   - every requirement has a stable `REQ-xx` and maps to at least one `AT-xxx`;
   - every success criterion names **the number, the source of the number and the method**;
   - a criterion may be a falsifiable hypothesis; say so explicitly;
   - fill *File Ownership (preliminary)* and check it against the ownership map in `_index.md`
     — report any path another active feature already owns;
   - score clarity honestly; below 12/15, list the questions and stop.
4. Add the feature to the *Features* table in `_index.md` with phase "Define — awaiting approval".
5. Run `python3 tools/build_sdd_package.py`.

## Exit

The user approves (Status → Approved, *Approved by* filled). Next command: `/sdd-design <FEATURE_NAME>`.
Do not mark the DEFINE as approved yourself.
