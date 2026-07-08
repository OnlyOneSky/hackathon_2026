# Engineering Constitution

> Version-controlled rule set. Every change produced by the agent loop is checked
> against these clauses by the Security Critic before a PR is opened.
> Adding or amending a clause here immediately extends the safety net to all
> subsequent changes. This file is READ-ONLY to the coding agent (the Actor).
>
> Each clause has a stable ID (§N) so the Security Critic can cite it by number.

## §1 — Money is never floating point
All monetary amounts MUST use a fixed-point decimal type (e.g. `Decimal`),
never `float` or `double`. This includes intermediate calculations.

## §2 — Validate all external input
Any value originating outside the service (API request body, query params,
upstream service response) MUST be validated before use. No raw external value
may reach business logic or persistence unchecked.

## §3 — Every money movement leaves an audit trail
Any operation that moves, holds, or limits funds MUST write an audit record
(who, what, amount, timestamp, outcome). A blocked/denied operation MUST also
be audited, not silently dropped.

## §4 — No customer PII in logs
Account numbers, names, balances, and other customer PII MUST NOT be written to
application logs. Use opaque IDs or masked values for diagnostics.

## §5 — Fail closed on limits and authorization
When a limit check or authorization check cannot be completed (error, timeout,
missing data), the operation MUST be denied, never allowed by default.
