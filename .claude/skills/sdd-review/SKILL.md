---
name: sdd-review
description: SDD gate - independent, blockers-only design review in a fresh chat. Run only when the user types /sdd-review <FEATURE>.
disable-model-invocation: true
---

# SDD gate: independent design review

Usage: `/sdd-review <FEATURE_NAME>` — **run it in a new chat, preferably in Ask mode.**

## Ground rules

- **Read only two files:** `.claude/sdd/features/<FEATURE_NAME>/DEFINE_<FEATURE_NAME>.md` and
  `DESIGN_<FEATURE_NAME>.md`. Do not read the SDD package, previous reviews, chat history or other
  features. If this chat has already discussed or edited this design, say so: the review is not
  independent, and the user must open a new chat.
- **Do not edit any file.**
- Reply to the user in Brazilian Portuguese.

## Task

Report **only blocking problems** — issues that make it unsafe or impossible to start the Build:

- a contradiction between the DEFINE and the DESIGN, or inside the DESIGN;
- a `REQ-xx` with no design element or no acceptance test;
- an ordering or dependency error that would break a deploy or a migration;
- a risk without mitigation that could invalidate the result (data loss, voided measurement, a cost
  with no ceiling);
- a factual claim the design depends on, stated as fact but not sourced.

Everything else is a **Build note**: it does not block and does not justify another review round.

## Answer format

- Verdict: **READY FOR BUILD** or **BLOCKED**.
- Numbered blocking issues, each with: where (section), why it blocks, the smallest fix.
- Up to 5 Build notes.

## Exit

- READY FOR BUILD → the user (or the design chat) records the sign-off in the DESIGN's revision
  history as version 1.0 and the Build notes as a checklist. Next: `/sdd-build <FEATURE_NAME> <items>`.
- BLOCKED → fix only the blocking issues in the design chat, then one more `/sdd-review` in a new chat.
