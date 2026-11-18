---
name: sdd-design
description: SDD phase 2 - write a feature DESIGN from an approved DEFINE. Run only when the user types /sdd-design <FEATURE>.
disable-model-invocation: true
---

# SDD phase 2: Design

Usage: `/sdd-design <FEATURE_NAME>`

## Ground rules

- Read `CLAUDE.md`, `.claude/sdd/CONSTITUTION.md` and `.claude/sdd/_index.md` first.
- The feature name comes after the command. If it is missing, ask and stop.
- The DEFINE must be **Approved**. If it is not, say so and stop.
- Reply to the user in Brazilian Portuguese. Write every repository file in English.
- No production code in this phase. Small sketches inside the DESIGN are fine and must be labelled
  as sketches.

## Task

1. Read the approved `DEFINE_<FEATURE_NAME>.md`, `.claude/sdd/templates/DESIGN_TEMPLATE.md`, the ADRs
   it references and the current code the feature will touch.
2. **Verify before you design.** For every assumption in the DEFINE and every external fact the
   design depends on (provider support, billing behaviour, API fields), check the official
   documentation or the live code. Record each result in a *Findings* table with its source.
   Anything you could not verify is labelled *unverified* and becomes a risk.
3. Write `.claude/sdd/features/<FEATURE_NAME>/DESIGN_<FEATURE_NAME>.md`:
   - *Key Decisions* with context, choice, rationale, rejected alternatives and consequences;
   - a *Requirement coverage* table: every `REQ-xx` → design element → `AT-xxx`;
   - *File Manifest* and *File Ownership & Parallelism* (no path owned by another active feature);
   - if the feature is measured, the measurement plan **with predictions written before measuring**;
   - risks with mitigations.
4. If you wrote logic that decides behaviour (state machines, schedulers, gates), simulate it with a
   small script before claiming it works, and report what the simulation found.
5. Update the feature's line in `_index.md` ("Design — draft") and run
   `python3 tools/build_sdd_package.py`.

## Exit

Next step: an **independent** review in a **new chat**: `/sdd-review <FEATURE_NAME>`.
Do not run the review in this chat.
