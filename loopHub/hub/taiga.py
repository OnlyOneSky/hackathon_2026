"""Taiga REST connector (infra doc §4 write-back).

One PATCH carries description + status + comment; Taiga's `version` field is
the optimistic lock — a concurrent human edit makes the PATCH fail loudly.
"""
from __future__ import annotations

import httpx


class TaigaClient:
    def __init__(self, base_url: str, token: str):
        self.c = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )

    def get_story(self, story_id: int) -> dict:
        r = self.c.get(f"/api/v1/userstories/{story_id}")
        r.raise_for_status()
        return r.json()

    def write_spec_and_move(self, story_id: int, spec_md: str,
                            review_status_id: int, reviewer: str,
                            spec_version: int) -> dict:
        s = self.get_story(story_id)          # fresh version for optimistic lock
        r = self.c.patch(f"/api/v1/userstories/{story_id}", json={
            "version": s["version"],
            "description": spec_md,           # spec IS the card description
            "status": review_status_id,
            "comment": f"@{reviewer} spec v{spec_version} 草稿完成，請審查。",
        })
        r.raise_for_status()
        return r.json()

    def move_with_comment(self, story_id: int, status_id: int, comment: str) -> dict:
        """Bounce / outcome write-back: move a card and explain why."""
        s = self.get_story(story_id)
        r = self.c.patch(f"/api/v1/userstories/{story_id}", json={
            "version": s["version"],
            "status": status_id,
            "comment": comment,
        })
        r.raise_for_status()
        return r.json()

    def comment(self, story_id: int, text: str) -> dict:
        s = self.get_story(story_id)
        r = self.c.patch(f"/api/v1/userstories/{story_id}", json={
            "version": s["version"],
            "comment": text,
        })
        r.raise_for_status()
        return r.json()


def auth_token(base_url: str, username: str, password: str) -> str:
    """POST /api/v1/auth — used once to mint loop-bot's token."""
    r = httpx.post(f"{base_url}/api/v1/auth", json={
        "type": "normal", "username": username, "password": password,
    }, timeout=15)
    r.raise_for_status()
    return r.json()["auth_token"]
