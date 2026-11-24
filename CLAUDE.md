# CLAUDE.md — sdd-kafka-snowflake-3

Single source of truth for any AI agent (Claude Code, Cursor) working in this repository.
`.cursor/rules/` only points here. When the code changes what this file says, this file is
updated in the same PR — the Retro gate checks it.

## What this repository is

CDC from PostgreSQL to Snowflake (Debezium → Kafka → Snowpipe Streaming via Kafka Connector v4
→ Bronze/Silver/Gold in dbt Core → Dagster), evolved from `sdd-kafka-snowflake-2` with two
goals: **cost governance 2.0, proven by measurement**, and **infrastructure as code**.
v2 stays frozen as the baseline the measurements compare against.

## Read before acting

1. `.claude/sdd/CONSTITUTION.md` — rules that always apply.
2. `.claude/sdd/README.md` — the SDD lifecycle.
3. `.claude/sdd/_index.md` — active features, file ownership, plan.
4. The folder of the feature you are working on, and the ADRs it references.

Each SDD phase is a skill in `.claude/skills/` (invoked only explicitly; read by Claude Code, including
inside Cursor) (`/sdd-status`, `/sdd-brainstorm`, `/sdd-define`,
`/sdd-design`, `/sdd-review`, `/sdd-build`, `/sdd-validate`, `/sdd-ship`, `/sdd-retro`,
`/sdd-fasttrack`). When the user runs one, follow its `SKILL.md` exactly; it overrides general habits.
`/sdd-review` and `/sdd-validate` must run in a chat that has not worked on the feature.

**Do not read `.claude/sdd/SDD_V3_PACKAGE.md`.** It is a generated, read-only copy for
humans and may be stale. Always read the source files above. After changing any SDD file,
regenerate it with `python tools/build_sdd_package.py`.

## Conventions

- Language: **English** for code, comments, specs, ADRs and commit messages.
- Feature names: `UPPER_SNAKE_CASE` in English. Requirement IDs: `REQ-xx`. Acceptance tests: `AT-xxx`.
- Commits/PRs cite at least one `REQ-xx`.
- dbt: Bronze `incremental`/`merge` (idempotent over redelivery); Silver and Gold `table` unless a
  model justifies otherwise in its header comment (see v2 `dbt_project.yml` rationale).
- Snowflake objects are created by Terraform, not by hand. Scripts in `scripts/` are for
  verification and one-off bootstrap only.

## Environments and names

| Item | Value |
|------|-------|
| Snowflake account | `GWHUBCF-QQ53235` (org `GWHUBCF`, locator `KT15332`) — **trial**, created 2026-11-17. Not the v2 account. |
| Snowflake region | AWS `sa-east-1` (São Paulo) |
| Objects | v2 names, no suffix: `CDC_POC`, `CDC_WH`, `CDC_ROLE`, `CDC_ROLE_RO` (Terraform variable defaults; COST_GOVERNANCE Decision 3) |
| Terraform | `terraform/platform` (then `terraform/pipeline`); `cost_profile` and limits only in `terraform/env/dev.tfvars`. Provider `snowflakedb/snowflake`, exact version in `.terraform.lock.hcl` |
| Terraform identities | `TERRAFORM_SVC` (apply, CI only) · `TERRAFORM_PLAN_SVC` / `TERRAFORM_PLAN_ROLE` (read-only plan). Agents use the plan identity only |
| ACCOUNTADMIN in Terraform | only the resources listed in COST_GOVERNANCE Decision 9 (monitors, `CDC_WH`, …); enforced by `tests/unit/test_terraform_providers.py` |
| Warehouse generation | set with `GENERATION = '1'`; `RESOURCE_CONSTRAINT = STANDARD_GEN_1` is rejected on this account |
| Agent environment | dev only (Constitution R2) |
| Cost profile switch | `cost_profile` in `dev.tfvars` **and** `BATCH_WINDOW_MINUTES` in `.env` (0 = `baseline`, 10 = `optimized`) change together (COST_GOVERNANCE Decision 2): `make profile-a`/`profile-b` prepare a draft PR, `make batch-window` changes Dagster |
| GitHub | `main` protected by a ruleset (PR + `lint`/`validate` required, no bypass). Environment `snowflake-dev` (apply): required reviewer, `main` only. `snowflake-plan` (PR plans): no reviewer |

## Measurement windows (COST_GOVERNANCE)

Source of truth: `docs/measurement/PROTOCOL.md`. Windows in UTC: dry run 2026-11-24 12:00–18:00 ·
A 2026-11-26 00:00 → 11-28 00:00 · B → 11-30 00:00 · idle → 11-30 06:00. While a window is open,
agents do not:

- run anything on `CDC_WH` (that includes the measurement queries);
- merge, or prepare for merge, anything that reaches the stack other than the scheduled switch PR
  (Terraform, `.env`, `tests/load/`, `dagster/`);
- touch the Snowflake account or Postgres for SCD2_RESTAURANTS (its DESIGN Decision 9).

Any of these voids the window (PROTOCOL §5). A rerun moves the dates; PROTOCOL §9 records it.

## Forbidden for agents

See Constitution R1–R8. In short: no `apply`/destroy/drop, no production credentials, no secrets
in context, no edits to files owned by another active feature.
