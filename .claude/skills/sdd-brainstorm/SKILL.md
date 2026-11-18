---
name: sdd-brainstorm
description: SDD phase 0 - options and trade-offs for a new feature. Run only when the user types /sdd-brainstorm <FEATURE> <idea>.
disable-model-invocation: true
---

# SDD phase 0: Brainstorm

Usage: `/sdd-brainstorm <FEATURE_NAME> <one-line idea>` — e.g. `/sdd-brainstorm ORCHESTRATOR_AIRFLOW_PORT port Dagster to Airflow 3`.

## Ground rules

- Read `CLAUDE.md`, `.claude/sdd/CONSTITUTION.md` and `.claude/sdd/_index.md` first.
- The feature name and the idea come after the command. If the name is missing, ask and stop.
  Feature names are `UPPER_SNAKE_CASE` in English.
- Reply to the user in Brazilian Portuguese. Write every repository file in English.
- No code in this phase. Do not modify any file outside the one you create.

## Task

1. Read `.claude/sdd/templates/BRAINSTORM_TEMPLATE.md`.
2. Read what already exists on the subject: `_index.md` (roadmap, next features), the ADRs in
   `docs/adr/`, and any archived feature that touches the same area.
3. Before writing, ask the user **at most 3** questions whose answers change the options (goal,
   constraint, deadline). Wait for the answers.
4. Create `.claude/sdd/backlog/BRAINSTORM_<FEATURE_NAME>.md` from the template with 2–4 distinct
   options, each with trade-offs, cost/risk, and what would have to be true for it to win.
   Mark every factual claim that you did not verify as *unverified*.
5. End with a recommendation and the decision the user must make.

## Exit

The user picks a direction. Next command: `/sdd-define <FEATURE_NAME>`.
