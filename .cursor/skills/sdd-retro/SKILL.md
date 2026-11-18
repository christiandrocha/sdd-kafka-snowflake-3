---
name: sdd-retro
description: SDD phase 6 - retro that applies its lessons to rules, templates and skills. Run only when the user types /sdd-retro <FEATURE>.
disable-model-invocation: true
---

# SDD phase 6: Retro

Usage: `/sdd-retro <FEATURE_NAME>`

## Ground rules

- Read `CLAUDE.md`, `.claude/sdd/CONSTITUTION.md` and `.claude/sdd/_index.md` first.
- Reply to the user in Brazilian Portuguese. Write every repository file in English.

## Task

1. Read the feature's DEFINE (all revisions), DESIGN (all revisions), reviews recorded in the
   revision history, BUILD_REPORT and VALIDATION.
2. Fill `RETRO_<FEATURE_NAME>.md` from the template:
   - *What the spec got wrong*: each item with what the documents said, what reality was, and why it
     was missed;
   - *What the process got wrong*: phases that cost more than they returned, skipped gates, reviews
     that missed something or ran too many rounds;
   - planned vs actual days.
3. **Apply the lessons, do not just write them.** For each lesson, propose the concrete change to
   `CLAUDE.md`, `.claude/sdd/CONSTITUTION.md`, a template or a `.cursor/skills/*/SKILL.md` file, show the
   diff, and apply it after the user's OK. Record each in *Changes Applied* with the PR.
4. Move anything left undone to `.claude/sdd/backlog/` or the roadmap in `_index.md`.
5. Run `python3 tools/build_sdd_package.py`.

## Exit

The retro is done only when *Changes Applied* is filled and merged. Then finish `/sdd-ship`.
