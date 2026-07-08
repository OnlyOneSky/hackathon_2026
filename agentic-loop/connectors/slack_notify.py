"""Slack connector — the notifications shown across the board in the proposal.

The loop notifies a human at three points:
  - spec ready    -> "review the spec" (developer decides approve/edit/reject)
  - PR opened     -> "awaiting review" (human gate #2)
  - 6x failure    -> "card returned to Backlog" with the reason

In mode="mock" this prints; in mode="real" it POSTs to an incoming-webhook URL.

Env for real mode:
  SLACK_WEBHOOK_URL - an incoming-webhook URL for the target channel
"""

from __future__ import annotations

import os


def notify(text: str, *, mode: str = "mock") -> None:
    if mode == "mock":
        print(f"    [slack] {text}")
        return
    import requests  # local import so mock mode needs no dependency

    url = os.environ["SLACK_WEBHOOK_URL"]
    requests.post(url, json={"text": text}, timeout=15).raise_for_status()
