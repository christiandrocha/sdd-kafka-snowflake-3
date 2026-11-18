"""Static guards for .github/workflows (COST_GOVERNANCE items 16-18, REQ-08 / AT-009).

Constitution R1 (no destroy, applies only through the protected environment),
Decision 11 (forks get no secrets, PR plans are read-only), D1 (no personal
data in public logs) and the owner decisions of build run 4.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
TF = WORKFLOWS / "terraform.yml"


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1 reads `on:` as True
    return data


WF = _load(TF)
JOBS = WF["jobs"]
TEXT = TF.read_text()


def _runs(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def _step(job: dict, name_part: str) -> dict:
    matches = [s for s in job["steps"] if name_part in s.get("name", "")]
    assert len(matches) == 1, name_part
    return matches[0]


def test_deploy_yml_is_gone():
    assert not (WORKFLOWS / "deploy.yml").exists()


def test_triggers_and_jobs():
    assert set(WF["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert WF["on"]["push"]["branches"] == ["main"]
    assert set(JOBS) == {"static", "plan", "apply", "apply-pipeline"}
    assert WF["permissions"] == {"contents": "read"}
    assert WF["defaults"]["run"]["shell"] == "bash"  # pipefail for `plan | tee`


def test_no_destroy_and_no_auto_approve_anywhere():
    assert "destroy" not in _runs_all()
    assert "auto-approve" not in TEXT


def _runs_all() -> str:
    return "\n".join(_runs(j) for j in JOBS.values())


def test_static_job_has_no_secrets_and_no_environment():
    job = JOBS["static"]
    assert "environment" not in job
    assert "secrets." not in yaml.safe_dump(job)


def test_plan_job_never_runs_for_forks_and_is_read_only():
    job = JOBS["plan"]
    assert "github.event.pull_request.head.repo.full_name == github.repository" in job["if"]
    assert job["environment"] == "snowflake-plan"
    assert job["env"]["TF_VAR_plan_role"] == "TERRAFORM_PLAN_ROLE"
    assert "terraform apply" not in _runs(job)
    assert "snowflake-dev" not in yaml.safe_dump(job)


@pytest.mark.parametrize("name", ["apply", "apply-pipeline"])
def test_applies_only_through_the_protected_environment_on_main(name):
    job = JOBS[name]
    assert job["environment"] == "snowflake-dev"
    assert "github.ref == 'refs/heads/main'" in job["if"]
    assert job["concurrency"] == {"group": "terraform-apply", "cancel-in-progress": False}
    assert "terraform apply" in _runs(job)


@pytest.mark.parametrize("name", ["apply", "apply-pipeline"])
def test_every_apply_is_followed_by_a_detailed_exitcode_plan(name):
    runs = _runs(JOBS[name])
    assert runs.count("terraform apply") == runs.count("-detailed-exitcode")
    assert "AT-001" in runs


def test_apply_compares_the_replan_with_the_pr_plan_without_blocking():
    job = JOBS["apply"]
    for root in ["platform", "pipeline"]:
        step = _step(job, f"{root} — compare with the PR plan")
        assert "plan_summary.py compare" in step["run"]
        assert "::warning" in step["run"]
        assert "exit 1" not in step["run"]
        assert "continue-on-error" not in step  # it cannot fail: compare always exits 0
    assert "found=false" in _step(job, "Fetch the PR plan summaries")["run"]


def test_pipeline_plan_skip_is_written_to_the_job_summary():
    step = _step(JOBS["plan"], "pipeline plan skipped")
    assert step["if"] == "steps.bronze.outputs.state != 'ready'"
    assert "GITHUB_STEP_SUMMARY" in step["run"] and "::notice" in step["run"]


def test_budget_email_comes_only_from_a_secret():
    assert "vars.BUDGET_NOTIFY_EMAIL" not in TEXT
    step = _step(JOBS["apply"], "budget.sql")
    assert step["env"]["BUDGET_NOTIFY_EMAIL"] == "${{ secrets.BUDGET_NOTIFY_EMAIL }}"
    assert "notify_email=${BUDGET_NOTIFY_EMAIL}" in step["run"]


@pytest.mark.parametrize("name", ["apply", "apply-pipeline"])
def test_verify_runs_as_the_read_only_identity(name):
    step = _step(JOBS[name], "verify_governance.sql")
    assert step["env"]["SNOWFLAKE_USER"] == "${{ vars.SNOWFLAKE_PLAN_USER }}"
    assert step["env"]["SNOWFLAKE_PRIVATE_KEY_RAW"] == "${{ secrets.SNOWFLAKE_PLAN_PRIVATE_KEY }}"
    assert "tail -n 1" in step["run"]  # console warnings go to stdout


def test_secrets_only_in_jobs_with_an_environment():
    for name, job in JOBS.items():
        if "secrets." in yaml.safe_dump(job):
            assert job.get("environment") in {"snowflake-plan", "snowflake-dev"}, name


def test_id_token_only_where_aws_state_is_needed():
    for name, job in JOBS.items():
        perms = job.get("permissions", {})
        if perms.get("id-token") == "write":
            assert "aws-actions/configure-aws-credentials@v4" in yaml.safe_dump(job), name


def test_actions_are_pinned_and_from_known_publishers():
    uses = re.findall(r"uses:\s*([^\s]+)", TEXT)
    assert uses
    for ref in uses:
        owner, _, version = ref.partition("@")
        assert owner.split("/")[0] in {"actions", "hashicorp", "aws-actions"}, ref
        assert re.fullmatch(r"v\d+", version), ref


def test_tool_versions_are_pinned():
    assert WF["env"]["TERRAFORM_VERSION"] == "1.11.4"
    assert re.fullmatch(r"\d+\.\d+\.\d+", WF["env"]["SNOWFLAKE_CLI_VERSION"])


def test_bronze_tables_match_the_pipeline_domains():
    variables = (ROOT / "terraform" / "pipeline" / "variables.tf").read_text()
    block = variables.split('variable "gate_domains"', 1)[1].split("}", 1)[0]
    assert set(re.findall(r'"([A-Z_]+)"', block)) == set(WF["env"]["BRONZE_TABLES"].split())


def test_ci_runs_the_unit_tests():
    ci = (WORKFLOWS / "ci.yml").read_text()
    assert "pytest tests/unit -q" in ci


def _reference_check_code() -> str:
    ci = _load(WORKFLOWS / "ci.yml")
    steps = [s for j in ci["jobs"].values() for s in j["steps"]]
    step = next(s for s in steps if s.get("name", "").startswith("Arquivos referenciados"))
    return step["run"].split("<<'PY'\n", 1)[1].rsplit("PY", 1)[0]


def test_ci_reference_check_passes_on_this_repo(monkeypatch):
    import textwrap

    monkeypatch.chdir(ROOT)
    with pytest.raises(SystemExit) as exit_:
        exec(textwrap.dedent(_reference_check_code()), {})
    assert exit_.value.code == 0


def test_ci_reference_check_still_catches_a_missing_helper(monkeypatch, tmp_path):
    import shutil
    import textwrap

    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    shutil.copytree(ROOT / ".github" / "scripts", tmp_path / ".github" / "scripts")
    (tmp_path / ".github" / "workflows" / "x.yml").write_text(
        "run: python ../../.github/scripts/does_not_exist.py\n"
        "run: python ../../.github/scripts/plan_summary.py\n"
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exit_:
        exec(textwrap.dedent(_reference_check_code()), {})
    assert exit_.value.code == 1
