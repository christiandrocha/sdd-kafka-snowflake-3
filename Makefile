.PHONY: up down logs register-connectors produce-initial produce-incremental produce-dry-run \
        dbt-parse dbt-run dbt-test lint yamllint security precommit-install ci-local \
        load load-plan dry-run batch-window profile-a profile-b deploy-platform deploy-pipeline

# ── Infrastructure ──────────────────────────────────────────────────────────
up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

register-connectors:
	./scripts/register_connectors.sh

# ── Data loading (source Postgres) ──────────────────────────────────────────
produce-initial:
	python3 tests/load_to_postgres.py --data-dir tests/data/ --batch initial --db-url $(DATABASE_URL)

produce-incremental:
	python3 tests/load_to_postgres.py --data-dir tests/data/ --batch incremental --db-url $(DATABASE_URL)

# v2's `dry-run` (renamed in COST_GOVERNANCE item 20: `dry-run` is now the
# measurement dry run below).
produce-dry-run:
	python3 tests/load_to_postgres.py --data-dir tests/data/ --dry-run

# ── Measurement (COST_GOVERNANCE item 20; docs/measurement/PROTOCOL.md) ────
# Windows: the exact dates of PROTOCOL.md §3. tests/unit/test_makefile.py
# checks that the two stay identical. A rerun (PROTOCOL §5) edits both.
LOAD_START_dry-run := 2026-11-24T12:00Z
LOAD_END_dry-run   := 2026-11-24T18:00Z
LOAD_START_A       := 2026-11-26T00:00Z
LOAD_END_A         := 2026-11-28T00:00Z
LOAD_START_B       := 2026-11-28T00:00Z
LOAD_END_B         := 2026-11-30T00:00Z

LOAD_WINDOWS := dry-run A B
# Expanded inside the recipe, so it also fires under `make -n`.
check_window = $(if $(filter $(WINDOW),$(LOAD_WINDOWS)),,$(error WINDOW must be one of: $(LOAD_WINDOWS) (got '$(WINDOW)')))
load_args = --window $(WINDOW) --start $(LOAD_START_$(WINDOW)) --end $(LOAD_END_$(WINDOW)) \
            --out docs/measurement/runs/$(WINDOW)

# `.env` is sourced into the generator's environment only; nothing is printed.
# The generator's exit code is passed through: 0 valid, 1 window not valid,
# 3 the task check does not see exactly ten gate tasks.
load:
	$(check_window)
	set -a; if [ -f .env ]; then . ./.env; fi; set +a; \
	  python3 tests/load/generate_load.py $(load_args)

# The plan only: touches no database.
load-plan:
	$(check_window)
	python3 tests/load/generate_load.py $(load_args) --plan-only

dry-run:
	$(MAKE) load WINDOW=dry-run

# Profile switch, Dagster half (PROTOCOL §4 step 2): BATCH_WINDOW_MINUTES in .env,
# recreate both Dagster containers (env_file is read at creation), log the step.
#   make batch-window N=0 SWITCH=S2
SWITCH_LOG := docs/measurement/runs/switch.log
batch-window:
	@case "$(N)" in ''|*[!0-9]*) echo "N must be a whole number of minutes (0 = profile A, 10 = profile B)" >&2; exit 2;; esac
	@test -f .env || { echo ".env not found" >&2; exit 1; }
	@if grep -q '^BATCH_WINDOW_MINUTES=' .env; then \
	  sed -i 's/^BATCH_WINDOW_MINUTES=.*/BATCH_WINDOW_MINUTES=$(N)/' .env; \
	else \
	  if [ -n "$$(tail -c1 .env)" ]; then echo >> .env; fi; \
	  echo 'BATCH_WINDOW_MINUTES=$(N)' >> .env; \
	fi
	docker compose up -d --force-recreate dagster dagster-daemon
	@mkdir -p $(dir $(SWITCH_LOG))
	@test -f $(SWITCH_LOG) || echo 'at_utc,switch,step,ref' > $(SWITCH_LOG)
	@echo "$$(date -u +%Y-%m-%dT%H:%M:%SZ),$(or $(SWITCH),-),dagster_recreated,BATCH_WINDOW_MINUTES=$(N)" >> $(SWITCH_LOG)
	@tail -n1 $(SWITCH_LOG)

# Profile switch, Terraform half (Decision 2): PREPARE the PR, never apply.
# Works in a temporary worktree from origin/main, so your checkout is untouched.
# The PR opens as a DRAFT: at the switch time, `gh pr ready <n>`, merge, and
# approve `apply (main)` in the snowflake-dev environment.
#   make profile-a SWITCH=S2 AT="2026-11-26 00:00 UTC"
#   make profile-b SWITCH=S3 AT="2026-11-28 00:00 UTC" TIMEOUT_MS=12000
define prepare_profile_pr
	@case "$(TIMEOUT_MS)" in ''|*[!0-9]*) [ -z "$(TIMEOUT_MS)" ] || { echo "TIMEOUT_MS must be a whole number" >&2; exit 2; };; esac
	@set -e; \
	git fetch -q origin main; \
	branch="profile/$(1)-$$(date -u +%Y%m%dT%H%M%S)"; \
	wt="$$(mktemp -d)"; trap 'git worktree remove --force "$$wt" >/dev/null 2>&1 || true' EXIT; \
	git worktree add -q -b "$$branch" "$$wt" origin/main; \
	f="$$wt/terraform/env/dev.tfvars"; \
	sed -i 's/^cost_profile *= *"[a-z]*"/cost_profile = "$(1)"/' "$$f"; \
	grep -q '^cost_profile = "$(1)"$$' "$$f" || { echo "cost_profile line not found in dev.tfvars" >&2; exit 1; }; \
	if [ -n "$(TIMEOUT_MS)" ]; then \
	  if grep -q '^gate_task_timeout_ms *=' "$$f"; then \
	    sed -i 's/^gate_task_timeout_ms *=.*/gate_task_timeout_ms = $(TIMEOUT_MS)/' "$$f"; \
	  else \
	    printf '\n# Decision 5: max(10 s, 5 x p99) from the dry run (PROTOCOL §7 D5).\ngate_task_timeout_ms = $(TIMEOUT_MS)\n' >> "$$f"; \
	  fi; \
	fi; \
	if git -C "$$wt" diff --quiet; then \
	  echo "main already has cost_profile = $(1) and no other change: nothing to prepare" >&2; \
	  git worktree remove --force "$$wt"; git branch -q -D "$$branch"; exit 1; \
	fi; \
	git -C "$$wt" diff; \
	git -C "$$wt" commit -q -am "chore(profile): cost_profile = $(1)$(if $(TIMEOUT_MS), and gate_task_timeout_ms = $(TIMEOUT_MS)) (REQ-07)"; \
	git -C "$$wt" push -q -u origin "$$branch"; \
	title="profile switch: cost_profile = $(1)"; \
	if [ -n "$(SWITCH)" ]; then title="$(SWITCH) $$title"; fi; \
	if [ -n "$(AT)" ]; then title="$$title — merge at $(AT)"; fi; \
	gh pr create --draft --base main --head "$$branch" --title "$$title" \
	  --body "Profile switch (DESIGN Decision 2; docs/measurement/PROTOCOL.md §4). Prepared by \`make profile-*\`; nothing is applied until this PR is merged and \`apply (main)\` is approved in snowflake-dev. Same minute: \`make batch-window N=$(2) SWITCH=$(SWITCH)\`. REQ-07."; \
	git worktree remove --force "$$wt"; git branch -q -D "$$branch"
endef

profile-a:
	$(call prepare_profile_pr,baseline,0)

profile-b:
	$(call prepare_profile_pr,optimized,10)

# ── Deploy (Decision 1 / 11): applies run in CI only (Constitution R1) ─────
# Platform: open the PR of the current branch after the cheap local checks;
# merging it triggers `apply (main)`, which waits for the snowflake-dev reviewer.
deploy-platform:
	@branch="$$(git rev-parse --abbrev-ref HEAD)"; \
	if [ "$$branch" = main ]; then echo "deploy-platform opens a PR: run it on a feature branch, not main" >&2; exit 1; fi
	@if command -v terraform >/dev/null; then \
	  terraform fmt -check -recursive terraform && \
	  for root in platform pipeline; do \
	    terraform -chdir=terraform/$$root init -backend=false -input=false >/dev/null && \
	    terraform -chdir=terraform/$$root validate || exit 1; \
	  done; \
	else \
	  echo "terraform not installed: fmt/validate skipped here; the 'static' CI job runs them on the PR"; \
	fi
	python3 -m pytest tests/unit -q
	git push -u origin HEAD
	gh pr create --fill --base main

# Pipeline: the FIRST pipeline apply is a workflow_dispatch (Decision 11.4),
# once the connector has created the Bronze tables. This only starts the run;
# it waits for the snowflake-dev approval like any apply. Later pipeline
# changes go through ordinary PRs.
deploy-pipeline:
	gh workflow run terraform.yml --ref main -f target=pipeline
	@echo "Started. Approve 'apply-pipeline' in the snowflake-dev environment: gh run list --workflow terraform.yml --limit 1"

# ── dbt (runs inside the Dagster container, project bind-mounted) ───────────
# `dbt parse` opens no warehouse connection — it is the free validation.
dbt-parse:
	docker compose exec dagster-daemon \
	  bash -c "cd /opt/dagster/dbt && dbt parse --target $${DBT_TARGET:-dev}"

dbt-run:
	docker compose exec dagster-daemon \
	  bash -c "cd /opt/dagster/dbt && dbt run --select silver gold --target $${DBT_TARGET:-dev}"

dbt-test:
	docker compose exec dagster-daemon \
	  bash -c "cd /opt/dagster/dbt && dbt test --select silver gold --target $${DBT_TARGET:-dev}"

# ── Quality ─────────────────────────────────────────────────────────────────
lint:
	ruff check .

yamllint:
	yamllint connectors/ observability/

security:
	bandit -r dagster/ scripts/ tests/ -ll --skip B101,B608

precommit-install:
	pre-commit install

# Mirrors the shell-syntax and reference checks of .github/workflows/ci.yml,
# so the cheap half of CI can be run before pushing.
ci-local:
	@for f in scripts/*.sh; do echo "bash -n $$f"; bash -n "$$f"; done
	@$(MAKE) lint yamllint
