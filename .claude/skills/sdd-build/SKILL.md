---
name: sdd-build
description: SDD phase 3 - build one group of DESIGN manifest items as one PR. Run only when the user types /sdd-build <FEATURE> <items>.
disable-model-invocation: true
---

# SDD phase 3: Build

Usage: `/sdd-build <FEATURE_NAME> <manifest items>` — e.g. `/sdd-build COST_GOVERNANCE items 1-4`.
**Agent mode.** One command = one small, reviewable PR.

## Ground rules

- Read `CLAUDE.md`, `.claude/sdd/CONSTITUTION.md` and `.claude/sdd/_index.md` first.
- The DESIGN must be at version 1.0 (signed off by `/sdd-review`). If it is not, say so and stop.
- Reply to the user in Brazilian Portuguese. Write code, comments and commit messages in English.
- **Constitution R1:** never run `terraform apply`, `terraform destroy`, `DROP`, `TRUNCATE`,
  `DELETE` without `WHERE`, or anything that changes the Snowflake account. You may run
  `terraform fmt`, `validate` and `plan` (with the read-only plan identity only), linters and tests.
- **Constitution R6:** touch only the files the DESIGN's *File Ownership* gives this feature. Shared
  files: one change at a time, and say which shared file you are touching.
- Never read, print or write secrets. Never ask for the `TERRAFORM_SVC` key.

## Task

1. Read the DESIGN in full, its *Findings* and the Build notes from the review. Restate in 3–5
   lines which manifest items you will build, which `REQ-xx` they serve and which files they touch.
2. **Present the plan and wait for the user's OK** (Constitution R4).
3. Work on a branch `feat/<feature-slug>-<items>`.
4. Before writing a resource, a config key or an API call, check its current documentation; the
   DESIGN's code patterns are sketches. If reality contradicts the DESIGN, stop and report — the
   DESIGN gets a new revision first, the code second.
5. Write tests together with the code. Run `ruff check .`, the unit tests, `terraform fmt -check` and
   `terraform validate` as applicable. All must pass.
6. Append to `.claude/sdd/features/<FEATURE_NAME>/BUILD_REPORT_<FEATURE_NAME>.md` (create it from the
   template if needed): items built, files, commands run and their results, deviations from the
   DESIGN, open issues.
7. Commit with a message citing the `REQ-xx`, push the branch and show the user the `gh pr create`
   command. Do not merge.
8. Run `python3 tools/build_sdd_package.py`.

## Exit

The user reviews and merges the PR; CI applies through the protected environment. When every
manifest item is built: next command, **in a new chat**, `/sdd-validate <FEATURE_NAME>`.
