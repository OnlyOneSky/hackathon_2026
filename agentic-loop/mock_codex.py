"""mock_codex.py — deterministic stand-ins for the Codex agent roles.

Used when orchestrator runs with mode="mock". These let the ENTIRE loop run
locally with no Codex CLI and no network, so the control logic (caps, gates,
git-diff enforcement, pytest) can be demonstrated and tested on its own.

The mock Actor varies its behaviour by scenario so we can demo three things:
  - "normal" : iteration 1 has a boundary bug (>=); iteration 2 fixes it (>).
               Shows the test->fix->retest loop converging.
  - "tamper" : iteration 1 also tries to weaken a protected test file; the
               orchestrator's git-diff gate catches and reverts it. Shows the
               anti-reward-hacking control.
  - "never"  : always buggy; the loop hits the iteration cap and escalates.
               Shows the runaway-protection cap.
"""

from __future__ import annotations

from pathlib import Path

# --- The spec the mock Spec agent "produces" from the request. --------------
_SPEC = {
    "summary": "Enforce a per-tier daily cumulative transfer limit; block and audit over-limit transfers.",
    "acceptance_criteria": [
        {"id": "AC-1", "given": "cumulative + amount <= tier limit",
         "when": "transfer executes", "then": "allowed", "constitution": ["§1"]},
        {"id": "AC-2", "given": "cumulative + amount > tier limit",
         "when": "transfer executes", "then": "blocked with LIMIT_EXCEEDED",
         "constitution": ["§5"]},
        {"id": "AC-3", "given": "amount is a float",
         "when": "transfer executes", "then": "rejected", "constitution": ["§1", "§2"]},
        {"id": "AC-4", "given": "a transfer is blocked",
         "when": "block occurs", "then": "an audit record is written",
         "constitution": ["§3"]},
    ],
    "applicable_constitution": ["§1", "§2", "§3", "§5"],
}

# --- Correct implementation: passes every acceptance test. ------------------
_CORRECT = '''\
"""Transfer domain logic for the demo bank app. (agent-implemented)"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from . import store


class TransferError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def execute_transfer(customer_id: str, amount: Decimal, day: date | None = None) -> dict:
    # §2 validate external input; §1 money must be Decimal, never float.
    if not isinstance(amount, Decimal):
        raise TypeError("amount must be a Decimal")
    if amount <= Decimal("0"):
        raise ValueError("amount must be positive")

    day = day or date.today()
    try:
        limit = store.daily_limit(customer_id)
        new_total = store.daily_total(customer_id, day) + amount
    except Exception:
        # §5 fail closed: if the limit cannot be evaluated, deny.
        raise TransferError("LIMIT_CHECK_FAILED", "could not evaluate limit")

    if new_total > limit:  # strictly over the limit is blocked; equal is allowed
        store.write_audit({"customer_id": customer_id, "amount": str(amount),
                           "outcome": "blocked", "code": "LIMIT_EXCEEDED"})
        raise TransferError("LIMIT_EXCEEDED", "daily transfer limit exceeded")

    store.add_to_daily_total(customer_id, day, amount)
    store.write_audit({"customer_id": customer_id, "amount": str(amount),
                       "outcome": "ok", "code": None})
    return {"status": "ok", "customer_id": customer_id, "amount": str(amount)}
'''

# --- Buggy implementation: off-by-one boundary (>=) fails AC-1 exact-equal. --
_BUGGY = _CORRECT.replace(
    "if new_total > limit:  # strictly over the limit is blocked; equal is allowed",
    "if new_total >= limit:  # BUG: blocks the exact-equal case too",
)

# A weakened test the tampering Actor tries to slip in (gets reverted).
_TAMPERED_TEST = "# (actor tried to delete the over-limit assertion here)\n"


def spec(request: str) -> dict:
    return dict(_SPEC)


def actor(repo_dir: Path, scenario: str, attempt: int, last_error: str) -> None:
    transfers = repo_dir / "demo_bankapp" / "transfers.py"

    if scenario == "never":
        transfers.write_text(_BUGGY)
        return

    if scenario == "tamper" and attempt == 0:
        # Try to weaken a protected test AND write code. The orchestrator's
        # git-diff gate will revert the test and reject this whole attempt.
        transfers.write_text(_CORRECT)
        test_file = repo_dir / "demo_bankapp" / "tests" / "test_transfer_limit.py"
        original = test_file.read_text()
        weakened = original.replace(
            'with pytest.raises(TransferError) as exc:',
            'pass  # disabled by actor\n    if False:\n        pass', 1)
        test_file.write_text(weakened)
        return

    # normal scenario: buggy first attempt, correct thereafter.
    if scenario == "normal" and attempt == 0:
        transfers.write_text(_BUGGY)
        return

    transfers.write_text(_CORRECT)


def qa(repo_dir: Path) -> dict:
    # Tests have already passed when QA is called. The mock QA confirms the
    # boundary/equal case is genuinely covered (it is — AC-1 exact-equal test).
    return {"verdict": "pass", "gaps": []}


def security(repo_dir: Path) -> dict:
    code = (repo_dir / "demo_bankapp" / "transfers.py").read_text()
    findings = []
    ok = True
    # §1: money is Decimal, never float.
    if "Decimal" not in code or "float(" in code:
        ok = False
        findings.append({"clause": "§1", "status": "violated", "evidence": "float used for money"})
    else:
        findings.append({"clause": "§1", "status": "compliant", "evidence": "Decimal used"})
    # §3: blocked movements are audited.
    if 'write_audit' in code and '"blocked"' in code:
        findings.append({"clause": "§3", "status": "compliant", "evidence": "write_audit on block"})
    else:
        ok = False
        findings.append({"clause": "§3", "status": "violated", "evidence": "no audit on block"})
    return {"verdict": "pass" if ok else "fail", "findings": findings}
