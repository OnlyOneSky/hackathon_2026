"""Transfer domain logic for the demo bank app.

INITIAL STATE: the daily cumulative transfer-limit feature is NOT implemented
yet. `execute_transfer` currently records every transfer unconditionally. The
acceptance tests in tests/test_transfer_limit.py therefore FAIL.

This is the "target" the agent loop must hit: implement the limit check so all
acceptance criteria pass, without weakening tests or violating the constitution.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from . import store


class TransferError(Exception):
    """Raised when a transfer is blocked. Carries a machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def execute_transfer(customer_id: str, amount: Decimal, day: date | None = None) -> dict:
    """Execute a transfer for `customer_id`.

    TODO(agent): enforce the per-tier daily cumulative limit. Until then this
    just records the movement, which is why AC-2 / AC-4 fail.
    """
    day = day or date.today()
    store.add_to_daily_total(customer_id, day, amount)
    return {"status": "ok", "customer_id": customer_id, "amount": str(amount)}
