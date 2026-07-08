"""Acceptance tests for the daily cumulative transfer-limit feature.

These tests are the machine-checkable form of the Spec's acceptance criteria.
They are PROTECTED: the Actor is forbidden to modify them (enforced by the
orchestrator via `git diff` after the Actor runs). The Actor's job is to make
the code satisfy these as written.
"""

from datetime import date
from decimal import Decimal

import pytest

from demo_bankapp import store
from demo_bankapp.transfers import TransferError, execute_transfer

DAY = date(2026, 6, 26)


def setup_function(_):
    store.reset()


# AC-1: cumulative + amount strictly under the limit -> allowed.
def test_ac1_under_limit_is_allowed():
    store.seed_daily_total("cust-001", DAY, Decimal("3000.00"))
    result = execute_transfer("cust-001", Decimal("2000.00"), day=DAY)
    assert result["status"] == "ok"
    assert store.daily_total("cust-001", DAY) == Decimal("5000.00")


# AC-1 boundary: cumulative + amount EXACTLY equal to the limit -> allowed.
# (A naive `>=` comparison wrongly blocks this case.)
def test_ac1_exactly_at_limit_is_allowed():
    store.seed_daily_total("cust-001", DAY, Decimal("9000.00"))
    result = execute_transfer("cust-001", Decimal("1000.00"), day=DAY)  # ==10000 limit
    assert result["status"] == "ok"


# AC-2: cumulative + amount over the limit -> blocked with LIMIT_EXCEEDED.
def test_ac2_over_limit_is_blocked():
    store.seed_daily_total("cust-001", DAY, Decimal("9500.00"))
    with pytest.raises(TransferError) as exc:
        execute_transfer("cust-001", Decimal("1000.00"), day=DAY)  # ->10500 > 10000
    assert exc.value.code == "LIMIT_EXCEEDED"
    # A blocked transfer must NOT change the running total.
    assert store.daily_total("cust-001", DAY) == Decimal("9500.00")


# AC-3 (constitution §1/§2): float amounts are rejected; money stays Decimal.
def test_ac3_float_amount_is_rejected():
    with pytest.raises((TypeError, ValueError)):
        execute_transfer("cust-001", 1000.0, day=DAY)  # float, not Decimal


# AC-4 (constitution §3): a blocked transfer writes an audit record.
def test_ac4_blocked_transfer_is_audited():
    store.seed_daily_total("cust-002", DAY, Decimal("49999.00"))
    with pytest.raises(TransferError):
        execute_transfer("cust-002", Decimal("2.00"), day=DAY)  # premium 50000 limit
    blocked = [a for a in store.audit_entries() if a.get("outcome") == "blocked"]
    assert len(blocked) == 1
    assert blocked[0]["code"] == "LIMIT_EXCEEDED"
