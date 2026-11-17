# DEFINE: {Feature Name}

> One-sentence description of what we're building and why it matters.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | {FEATURE_NAME} |
| **Date** | {YYYY-MM-DD} |
| **Author** | {author} |
| **Status** | {Draft / Needs Clarification / Ready for Design / Approved} |
| **Clarity Score** | {X}/15 (minimum 12 to proceed) |
| **Approved by** | {name — the scope freezes at approval; changes need a new DEFINE revision} |

---

## Problem Statement

{1–3 sentences. Who has the problem, what it costs them, and the evidence (a measurement, not an impression).}

---

## Goals

| Priority | Goal |
|----------|------|
| **MUST** | {MVP fails without this} |
| **SHOULD** | {Important, workaround exists} |
| **COULD** | {Cut first if the timeline is tight} |

---

## Requirements

> Every requirement has a stable ID. Every PR cites at least one ID. Every ID maps to at least one acceptance test.

| ID | Requirement | Priority | Verified by |
|----|-------------|----------|-------------|
| REQ-01 | {What the system must do — testable, not a task} | MUST | AT-001 |
| REQ-02 | {...} | SHOULD | AT-002 |

---

## Success Criteria

Measurable outcomes. Each one states **the number, the source of the number, and the method**.

- [ ] {Metric — e.g., "credits/day on WH_X, from ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, over a 48h controlled-load window"}

> A criterion may be a falsifiable hypothesis (e.g., "≥ 25% reduction"). If the measurement
> disproves it, the feature still ships with the measured result documented — the deliverable is
> the measurement, not the hoped-for number.

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | {Happy path} | {Initial state} | {Action} | {Expected, observable result} |
| AT-002 | {Error / edge case} | {...} | {...} | {...} |

---

## File Ownership (preliminary — refined in DESIGN)

| Path | Access |
|------|--------|
| {path/} | Owns |
| {path} | Reads |
| {path} | Shared — serialize |

## Build Skills / Context

| Agent role | Loads |
|------------|-------|
| Builder | {KB domains, skills, docs this feature needs} |
| Validator | {DEFINE + measurement queries only — no DESIGN, no build context} |

---

## Out of Scope

- {What we're NOT doing, and where it goes instead (roadmap / later feature / ADR only)}

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Technical | {...} | {...} |
| Timeline | {...} | {...} |
| Cost | {credit budget for this feature's own testing} | {...} |

---

## Assumptions

| ID | Assumption | If wrong, impact | Validated? |
|----|------------|------------------|------------|
| A-001 | {...} | {...} | [ ] |

---

## Clarity Score Breakdown

| Element | Score (0-3) | Notes |
|---------|-------------|-------|
| Problem | | |
| Users | | |
| Goals | | |
| Success | | |
| Scope | | |
| **Total** | **/15** | |

---

## Open Questions

{Blocking questions first, each with an owner and a default if unanswered.}

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | {YYYY-MM-DD} | {author} | Initial version |

---

## Next Step

**Ready for:** `/design .claude/sdd/features/{FEATURE_NAME}/DEFINE_{FEATURE_NAME}.md`
