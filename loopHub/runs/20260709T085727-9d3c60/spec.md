---
story: bankapp#37
spec_version: 1
generated: 2026-07-09T09:30:00Z
---
# Feature: daily cumulative transfer-limit validation

## Summary
Block a transfer when the customer's cumulative daily total would exceed their
tier limit; otherwise allow it. Keep an audit trail either way. The existing
tests in `tests/` are the contract — make them pass.

## Acceptance criteria
- A transfer within the limit is allowed and returns "OK".
- A transfer that would exceed the limit is blocked with `LimitExceeded`.

## Applicable constitution clauses
See the constitution; the money-handling and audit rules apply.

> DEMO NOTE: this spec is deliberately terse. It omits the exact-at-limit rule
> and does not spell out the Decimal requirement, so the first attempt commonly
> trips either the boundary test (C) or the §1 security check (E) and the loop
> self-corrects on the next pass. This is the "watch it fix its own mistake"
> scenario; count is typically ~2 but not guaranteed — rehearse and record it.
