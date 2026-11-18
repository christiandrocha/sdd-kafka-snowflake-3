---
name: sdd-validate
description: SDD phase 4 - independent validation with evidence in a fresh chat. Run only when the user types /sdd-validate <FEATURE>.
disable-model-invocation: true
---

# SDD phase 4: Validate

Usage: `/sdd-validate <FEATURE_NAME>` — **run it in a new chat.** The builder never validates
(Constitution P3).

## Ground rules

- Read `CLAUDE.md` and `.claude/sdd/CONSTITUTION.md`.
- Load **only**: the DEFINE of the feature, the merged code, the measurement or test artifacts the
  DEFINE points to (e.g. `docs/measurement/`) and `.claude/sdd/templates/VALIDATION_TEMPLATE.md`.
  **Do not read the DESIGN or the BUILD_REPORT** before you have drafted the results — they are the
  builder's account, and you are checking the result, not the story.
- If this chat took part in the Build, say so and stop.
- Reply to the user in Brazilian Portuguese. Write the validation file in English.
- Read-only on everything except the VALIDATION file. Never run anything that changes the Snowflake
  account; read-only queries are fine when the user runs them or provides the output.

## Task

1. For every `AT-xxx` in the DEFINE, determine how it is verified, run or request the check, and
   record the **evidence** (test output, query and its result, file path). A result without its query
   or command is a claim, not evidence.
2. For every success criterion, record target, measured value, method and whether it was met. A
   falsified hypothesis is a valid result: report it as such.
3. List what could not be verified under *Unverified claims*.
4. Only now read the BUILD_REPORT and flag any statement in it that the evidence contradicts.
5. Write `.claude/sdd/features/<FEATURE_NAME>/VALIDATION_<FEATURE_NAME>.md` from the template with a
   verdict: PASS / PASS WITH NOTES / FAIL. Run `python3 tools/build_sdd_package.py`.

## Exit

PASS → `/sdd-ship <FEATURE_NAME>`. FAIL → the findings become the work list for `/sdd-build`.
