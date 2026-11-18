# VALIDATION: {Feature Name}

> Independent verification of the DEFINE's acceptance tests and success criteria.
> **Written by a reviewer that did not build the feature** — a fresh session with no
> build context, loading only the DEFINE, the merged code and the measurement queries.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | {FEATURE_NAME} |
| **Date** | {YYYY-MM-DD} |
| **Validator** | {who / which session — must differ from the builder} |
| **DEFINE version** | {x.y} |
| **Commit validated** | {sha} |
| **Verdict** | {PASS / PASS WITH NOTES / FAIL} |

---

## Requirement Traceability

| REQ | Acceptance test | PR(s) | Result | Evidence |
|-----|-----------------|-------|--------|----------|
| REQ-01 | AT-001 | #{n} | {PASS/FAIL} | {query output, test run, screenshot path} |

---

## Success Criteria — Measured

| Criterion | Target | Measured | Method / source | Met? |
|-----------|--------|----------|-----------------|------|
| {metric} | {target} | {number} | {view, window, load profile} | {Y/N} |

> Paste the exact query used for each number in the appendix. A number without its query is a claim.

---

## Findings

| # | Severity | Finding | Action |
|---|----------|---------|--------|
| 1 | {blocker / major / minor} | {what is wrong or unproven} | {fix before ship / accept and document / roadmap} |

---

## Unverified Claims

{Anything the feature asserts that this validation could NOT verify, and why. These go into the README "Known gaps" section.}

---

## Appendix — Queries and Commands

```sql
-- {criterion}: {query}
```

---

## Next Step

**If PASS:** `/sdd-ship {FEATURE_NAME}`
**If FAIL:** back to Build with the findings above as the work list.
