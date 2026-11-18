"""Summarise and compare Terraform plans for .github/workflows/terraform.yml.

Decision 11 consequence (DESIGN_COST_GOVERNANCE): the environment approval of
the `apply` job happens before the job starts, and the PR plan (read-only
identity) cannot be applied by TERRAFORM_SVC, so `apply` re-plans. This module
reduces a plan to what a reviewer approved — the set of (address, actions) that
change — and compares the re-plan with the PR's. A divergence is a warning, not
a failure (owner decision 2026-11-18).

Usage:
  terraform show -json tfplan | python plan_summary.py summarize > summary.json
  python plan_summary.py compare pr_summary.json main_summary.json   # always exit 0
"""

from __future__ import annotations

import json
import sys


def summarize(plan: dict) -> list[dict]:
    """Changed resources only, sorted, without values (they may differ by identity)."""
    changes = []
    for rc in plan.get("resource_changes", []):
        actions = rc.get("change", {}).get("actions", [])
        if actions in (["no-op"], ["read"]):
            continue
        changes.append({"address": rc["address"], "actions": actions})
    return sorted(changes, key=lambda c: c["address"])


def compare(pr: list[dict], main: list[dict]) -> list[str]:
    """Human-readable differences; empty when the re-plan matches the PR plan."""
    pr_map = {c["address"]: c["actions"] for c in pr}
    main_map = {c["address"]: c["actions"] for c in main}
    diffs = []
    for address in sorted(pr_map.keys() | main_map.keys()):
        before, after = pr_map.get(address), main_map.get(address)
        if before == after:
            continue
        if before is None:
            diffs.append(f"only in the apply re-plan: {address} {after}")
        elif after is None:
            diffs.append(f"only in the PR plan: {address} {before}")
        else:
            diffs.append(f"different actions for {address}: PR {before} -> apply {after}")
    return diffs


def main(argv: list[str]) -> int:
    if argv[1:2] == ["summarize"]:
        json.dump(summarize(json.load(sys.stdin)), sys.stdout, indent=1)
        print()
        return 0
    if argv[1:2] == ["compare"] and len(argv) == 4:
        with open(argv[2]) as f_pr, open(argv[3]) as f_main:
            diffs = compare(json.load(f_pr), json.load(f_main))
        for line in diffs:
            print(line)
        return 0  # never blocks
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
