"""Taiga connector (outbound) — moves a card to a column.

The human gate #1 (approve the spec) is performed BY THE HUMAN moving the card
from Spec to Dev in Taiga — the system does not do that. The system only moves
cards on automated outcomes:
  - 6x failure in the Agentic Loop -> move the card BACK to Backlog (with a tag)
  - (optionally) success           -> move the card to PR/Done

In mode="mock" this prints; in mode="real" it PATCHes the user story status via
the Taiga API.

Env for real mode:
  TAIGA_URL, TAIGA_AUTH_TOKEN, and a status-name -> status-id map for the project.
"""

from __future__ import annotations

import os


def move_card(card_ref: int | str, to_column: str, *, tag: str | None = None,
              mode: str = "mock") -> None:
    if mode == "mock":
        suffix = f"  (tag: {tag})" if tag else ""
        print(f"    [taiga] move card #{card_ref} -> '{to_column}'{suffix}")
        return

    import requests  # local import so mock mode needs no dependency

    base = os.environ["TAIGA_URL"].rstrip("/")
    token = os.environ["TAIGA_AUTH_TOKEN"]
    status_id = int(os.environ[f"TAIGA_STATUS_{to_column.upper()}"])
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # Taiga requires the current version for an optimistic-lock PATCH.
    us = requests.get(f"{base}/api/v1/userstories/{card_ref}", headers=headers, timeout=15).json()
    requests.patch(
        f"{base}/api/v1/userstories/{card_ref}", headers=headers, timeout=15,
        json={"status": status_id, "version": us["version"]},
    ).raise_for_status()
