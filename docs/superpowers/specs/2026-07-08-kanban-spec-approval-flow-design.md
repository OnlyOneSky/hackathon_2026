# Kanban Spec-Approval Flow — Design

**Date:** 2026-07-08
**Scope:** The board-level flow that surrounds (but does not include) the agentic loop.
The loop internals are specified separately in `loopEngineer/docs/superpowers/specs/`
and are unchanged by this design.

## Problem

The original proposal used four columns (Backlog → Spec → Dev → PR/Done). The Spec
column silently held four states (AI drafting / draft ready / under human review /
approved-waiting), so the two most common reviewer actions had no defined path:

- **Reject** — no distinction between "regenerate with my feedback" and "the
  requirement itself is wrong, back to the PM."
- **Modify** — undefined where human edits live and whether the Dev-stage loop
  consumes the *edited* spec or regenerates from the card, silently discarding edits.

## Design decisions (confirmed with owner)

1. **Spec lives on the board card only.** The card description/comment is the single
   source of truth the human reads, edits, and approves. No spec file is maintained in
   the repo as a review surface; the connector snapshots the card text at approval time
   (see guardrail 1) as the audit record and the loop's frozen input.
2. **Five columns** — the Spec column splits into *Spec Drafting (AI)* and
   *Spec Review (Human)* so every state is visible and every human decision is a card move.
3. **Loop escalation returns to Spec Review** (not Backlog), tagged with the failure
   report, so it lands with the person who approved the spec.

## The flow

**Backlog → Spec Drafting (AI) → Spec Review (Human ①) → Dev (Agentic Loop) → PR/Done (Human ②)**

| # | Move | Mover | Meaning |
|---|------|-------|---------|
| 1 | Backlog → Spec Drafting | PM (human) | Start. Webhook triggers the Spec agent, which reads the card's requirement text and writes the draft spec into the card. |
| 2 | Spec Drafting → Spec Review | Agent | Draft ready. Slack notifies the reviewer; the ball is visibly in the human's court. |
| 3 | Spec Review → Dev | Developer (human) | **The approval.** The connector snapshots the card's spec text verbatim at this moment; that snapshot is the frozen input to the loop. *Modify* = edit the card text first, then move. *Approve as-is* = just move. |
| 4 | Spec Review → Spec Drafting | Developer (human) | **Reject-and-regenerate.** Requires a feedback comment (guardrail 4). The agent revises its previous draft using the feedback — not from scratch. |
| 5 | Spec Review → Backlog | Developer (human) | **Reject the requirement.** The problem is upstream; the card returns to the PM's queue. |
| 6 | Dev → PR/Done | Agent | Loop converged; PR opened. Human Review & Merge remains gate ②. No auto-merge. |
| 7 | Dev → Spec Review | Agent | **Escalation** at the iteration/time cap. Failure report attached as a card comment. Human fixes the spec and re-approves (move 3, fresh run) or rejects (move 5). |
| 8 | PR/Done → Spec Review | Developer (human) | **PR rejected on substance.** Reviewer feedback rides along as a card comment; the spec is amended to capture what was actually wanted, then re-approved via move 3. Trivial nits are handled in normal PR review without a backward move. |

Invariant: *the spec is always the reason code exists.* Any substantive rework flows
through the spec, never directly into the loop.

## Guardrails (all live in the connector, outside the loop)

1. **Approval snapshot** — on move 3, the connector records the card's spec text
   verbatim in the run record. This is the approved-spec-of-record / audit trail,
   since the board is the only editing surface.
2. **Illegal-move guard** — the webhook handler bounces any move that skips the state
   machine (e.g. Backlog → Dev) back to its source column with an explanatory comment.
   The board is the interface; the connector enforces the state machine.
3. **Role-restricted transitions** — board permissions (supported by Jira/Taiga)
   restrict who may perform moves 3/4/5/8, so the human gates are enforced by the
   tool, not by convention.
4. **Feedback required on regenerate** — move 4 without a new comment does not
   re-trigger the agent; the connector posts a card comment requesting feedback.
5. **Re-entry guard** — one active run per card. A move into Dev (or Spec Drafting)
   while a run for that card is active is bounced with a comment.

## Out of scope

- Internals of the agentic loop (Actor↔Critic, caps, protected paths) — see
  `loopEngineer/`.
- Multi-board / multi-repo routing, and Done-column automation on merge webhooks —
  mentioned in the proposal as future work only if needed.
