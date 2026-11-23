"""Static and dry-run guards for the Makefile (COST_GOVERNANCE item 20).

REQ-06 / REQ-07 (load windows identical to docs/measurement/PROTOCOL.md §3),
Decision 2 (profile-* only PREPARE a PR), Decision 11 (deploy-pipeline only
dispatches the workflow) and Constitution R1 (no apply / destroy / merge from
the Makefile). Every check uses `make -n` or reads the file: nothing runs.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"
PROTOCOL = ROOT / "docs" / "measurement" / "PROTOCOL.md"

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="GNU make not installed")


def make_n(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "--no-print-directory", "-n", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def code_lines() -> list[str]:
    """Makefile lines without comments (a `#` inside a recipe string is kept)."""
    return [ln for ln in MAKEFILE.read_text().splitlines() if not ln.lstrip().startswith("#")]


def protocol_windows() -> dict[str, tuple[str, str, str]]:
    """PROTOCOL.md §3 table: | Window | `--window` | `--start` | `--end` | `--out` |."""
    rows = re.findall(
        r"^\| [^|]+ \| `([^`]+)` \| `([^`]+)` \| `([^`]+)` \| `([^`]+)` \|$",
        PROTOCOL.read_text(),
        flags=re.M,
    )
    return {w: (start, end, out) for w, start, end, out in rows if w != "--window"}  # header


# ── R1: nothing in the Makefile applies, destroys or merges ────────────────


@pytest.mark.parametrize(
    "forbidden",
    [r"terraform\s+(-chdir=\S+\s+)?apply", r"\bdestroy\b", r"gh\s+pr\s+merge", r"--auto\b"],
)
def test_makefile_never_applies_destroys_or_merges(forbidden: str) -> None:
    hits = [ln for ln in code_lines() if re.search(forbidden, ln)]
    assert not hits, f"forbidden command in Makefile: {hits}"


# ── load / load-plan / dry-run: the PROTOCOL windows, exactly ──────────────


def test_protocol_table_has_the_three_windows() -> None:
    assert set(protocol_windows()) == {"dry-run", "A", "B"}


@pytest.mark.parametrize("window", ["dry-run", "A", "B"])
def test_load_plan_uses_the_protocol_dates(window: str) -> None:
    start, end, out = protocol_windows()[window]
    res = make_n("load-plan", f"WINDOW={window}")
    assert res.returncode == 0, res.stderr
    cmd = res.stdout.strip().splitlines()[-1]
    assert cmd == (
        f"python3 tests/load/generate_load.py --window {window} --start {start} "
        f"--end {end} --out {out} --plan-only"
    )


def test_load_sources_env_and_runs_for_real() -> None:
    res = make_n("load", "WINDOW=B")
    assert res.returncode == 0, res.stderr
    assert ". ./.env" in res.stdout
    assert "--window B --start 2026-11-27T00:00Z --end 2026-11-29T00:00Z" in res.stdout
    assert "--plan-only" not in res.stdout
    assert "--no-task-check" not in res.stdout  # would void the window


@pytest.mark.parametrize("target", ["load", "load-plan"])
@pytest.mark.parametrize("window", ["", "C", "a", "dryrun"])
def test_unknown_window_fails_before_running(target: str, window: str) -> None:
    res = make_n(target, f"WINDOW={window}")
    assert res.returncode != 0
    assert "WINDOW must be one of" in res.stderr


def test_dry_run_is_the_measurement_dry_run() -> None:
    res = make_n("dry-run")
    assert res.returncode == 0, res.stderr
    assert "--window dry-run --start 2026-11-24T12:00Z --end 2026-11-24T18:00Z" in res.stdout


def test_v2_dry_run_kept_under_its_new_name() -> None:
    res = make_n("produce-dry-run")
    assert res.returncode == 0, res.stderr
    assert "tests/load_to_postgres.py" in res.stdout and "--dry-run" in res.stdout


# ── profile-a / profile-b: prepare a draft PR, never apply ─────────────────


@pytest.mark.parametrize(
    ("target", "profile", "window"),
    [("profile-a", "baseline", "0"), ("profile-b", "optimized", "10")],
)
def test_profile_targets_prepare_a_draft_pr(target: str, profile: str, window: str) -> None:
    res = make_n(target, "SWITCH=S9")
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert f'cost_profile = "{profile}"' in out
    assert "git worktree add" in out and "origin/main" in out  # the user's checkout is untouched
    assert "gh pr create --draft --base main" in out
    assert f"make batch-window N={window} SWITCH=S9" in out
    assert "(REQ-07)" in out  # Constitution R5


def test_profile_b_timeout_is_written_only_when_given() -> None:
    without = make_n("profile-b").stdout
    with_ms = make_n("profile-b", "TIMEOUT_MS=12000").stdout
    assert "gate_task_timeout_ms = 12000" in with_ms
    assert 'if [ -n "12000" ]' in with_ms
    assert "gate_task_timeout_ms = 12000" not in without
    assert 'if [ -n "" ]' in without  # the timeout branch is inert without TIMEOUT_MS


# ── batch-window ────────────────────────────────────────────────────────────


def test_batch_window_edits_one_key_and_recreates_dagster() -> None:
    res = make_n("batch-window", "N=10", "SWITCH=S3")
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert "s/^BATCH_WINDOW_MINUTES=.*/BATCH_WINDOW_MINUTES=10/" in out
    assert "docker compose up -d --force-recreate dagster dagster-daemon" in out
    assert "S3,dagster_recreated,BATCH_WINDOW_MINUTES=10" in out
    assert "cat .env" not in out  # never prints the secrets file


# ── deploy-* ────────────────────────────────────────────────────────────────


def test_deploy_pipeline_only_dispatches_the_workflow() -> None:
    res = make_n("deploy-pipeline")
    assert res.returncode == 0, res.stderr
    assert "gh workflow run terraform.yml --ref main -f target=pipeline" in res.stdout


def test_deploy_pipeline_target_matches_the_workflow_input() -> None:
    wf = (ROOT / ".github" / "workflows" / "terraform.yml").read_text()
    assert re.search(r"options:\s*\[pipeline\]", wf)


def test_deploy_platform_refuses_main_and_opens_a_pr() -> None:
    res = make_n("deploy-platform")
    assert res.returncode == 0, res.stderr
    assert 'if [ "$branch" = main ]' in res.stdout
    assert "python3 -m pytest tests/unit -q" in res.stdout
    assert "gh pr create --fill --base main" in res.stdout
