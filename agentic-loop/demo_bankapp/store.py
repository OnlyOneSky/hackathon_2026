"""In-memory persistence for the demo bank app.

This stands in for a database. It tracks each customer's tier, their
cumulative transfer total per day, and an append-only audit trail. The
audit trail is what constitution clause §3 ("every money movement leaves an
audit trail") is checked against.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Dict, List, Tuple

# Customer daily transfer limits by tier. Money is ALWAYS Decimal (constitution §1).
TIER_LIMITS: Dict[str, Decimal] = {
    "standard": Decimal("10000.00"),
    "premium": Decimal("50000.00"),
}

# customer_id -> tier
_CUSTOMERS: Dict[str, str] = {
    "cust-001": "standard",
    "cust-002": "premium",
}

# (customer_id, iso-date) -> cumulative amount already transferred that day
_DAILY_TOTALS: Dict[Tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0.00"))

# Append-only audit trail. Each entry is a dict (constitution §3).
_AUDIT: List[dict] = []


def reset() -> None:
    """Reset all mutable state. Used by tests to isolate cases."""
    _DAILY_TOTALS.clear()
    _AUDIT.clear()


def tier_of(customer_id: str) -> str:
    if customer_id not in _CUSTOMERS:
        raise KeyError(f"unknown customer: {customer_id}")
    return _CUSTOMERS[customer_id]


def daily_limit(customer_id: str) -> Decimal:
    return TIER_LIMITS[tier_of(customer_id)]


def daily_total(customer_id: str, day: date) -> Decimal:
    return _DAILY_TOTALS[(customer_id, day.isoformat())]


def add_to_daily_total(customer_id: str, day: date, amount: Decimal) -> None:
    _DAILY_TOTALS[(customer_id, day.isoformat())] += amount


def write_audit(record: dict) -> None:
    _AUDIT.append(record)


def audit_entries() -> List[dict]:
    return list(_AUDIT)


def seed_daily_total(customer_id: str, day: date, amount: Decimal) -> None:
    """Test helper: pretend the customer has already moved `amount` today."""
    _DAILY_TOTALS[(customer_id, day.isoformat())] = amount
