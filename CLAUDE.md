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

Each SDD phase has a Cursor skill in `.cursor/skills/` (invoked only explicitly) (`/sdd-status`, `/sdd-define`,
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
| Objects | suffixed `_V3` (e.g. `CDC_WH_V3`) so the A/B config A can coexist — confirm in COST_GOVERNANCE design |
| Warehouse generation | set with `GENERATION = '1'`; `RESOURCE_CONSTRAINT = STANDARD_GEN_1` is rejected on this account |
| Agent environment | dev only (Constitution R2) |

## Forbidden for agents

See Constitution R1–R8. In short: no `apply`/destroy/drop, no production credentials, no secrets
in context, no edits to files owned by another active feature.
