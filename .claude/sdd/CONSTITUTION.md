# Constitution

Non-negotiable rules for every human and AI agent working in this repository, in every SDD
phase, fast track included. If an instruction conflicts with this file, this file wins.

Adapted from the constitution pattern in
[ThomazRossito/data-agents](https://github.com/ThomazRossito/data-agents) (`kb/constitution.md`).

## Principles

| # | Principle | Meaning |
|---|-----------|---------|
| P1 | Spec before code | No Build without an approved DEFINE and a reviewed DESIGN (fast track: mini-DEFINE). |
| P2 | Measure, don't claim | A cost, performance or correctness statement in the README needs a query or test that reproduces it. |
| P3 | The builder never validates | Validation is done by a separate session without build context. |
| P4 | Secure by default | Least privilege; no credentials in code, prompts, logs or artifacts. |
| P5 | Context first | Read `CLAUDE.md`, the feature folder and the relevant ADRs before planning. Never assume. |

## Hard rules for agents

| # | Rule |
|---|------|
| R1 | **Never** run `terraform apply`, `terraform destroy`, or any `DROP`, `TRUNCATE`, `DELETE` without `WHERE`, `ALTER ... SUSPEND` on shared objects. Agents run `terraform plan` and propose; `apply` happens only through the CI pipeline with approval. |
| R2 | **Never** hold or request production credentials. Agents work against the dev environment only. |
| R3 | **Never** print, write or commit secrets. Read them from environment variables; never read the secret store contents into context. |
| R4 | **Always** present a plan before multi-file or multi-step changes, and wait for approval. |
| R5 | **Always** cite a `REQ-xx` in every commit/PR. No requirement, no change. |
| R6 | **Never** modify a file owned by another active feature (see `_index.md`). Shared files: one writer at a time. |
| R7 | If the request scores below 3/5 on clarity (goal, scope, acceptance), ask before planning. |
| R8 | When unsure whether an action is reversible, treat it as irreversible and ask. |

## Data rules

| # | Rule |
|---|------|
| D1 | No real personal data in prompts, fixtures or test data. Synthetic only. |
| D2 | Columns holding personal data are tagged and masked before any new consumer reads them. |
| D3 | Bronze is append-only (ADR-0025). Any purge mechanism must be explicit, audited and documented — never an ad-hoc `DELETE`. |
