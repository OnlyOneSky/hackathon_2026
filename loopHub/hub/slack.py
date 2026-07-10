"""Slack notifications for the human gates (kanban design doc move ②/⑥/⑦).

Configured via env: LOOPHUB_SLACK_TOKEN (bot token, chat:write) and
LOOPHUB_SLACK_CHANNEL (channel ID, not name). Unset -> notify() is a silent
no-op; Slack failures are logged and never break board write-backs.
"""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger("loop-hub")


def _card_url(base_url: str, story: dict) -> str:
    slug = (story.get("project_extra_info") or {}).get("slug")
    if slug and story.get("ref"):
        return f"{base_url}/project/{slug}/us/{story['ref']}"
    return base_url


def notify(text: str) -> None:
    token = os.environ.get("LOOPHUB_SLACK_TOKEN", "")
    channel = os.environ.get("LOOPHUB_SLACK_CHANNEL", "")
    if not token or not channel:
        return
    try:
        r = httpx.post("https://slack.com/api/chat.postMessage",
                       headers={"Authorization": f"Bearer {token}"},
                       json={"channel": channel, "text": text,
                             "unfurl_links": False},
                       timeout=10)
        body = r.json()
        if not body.get("ok"):
            log.warning("slack notify failed: %s", body.get("error"))
    except Exception:                                     # noqa: BLE001
        log.exception("slack notify failed")


def spec_ready(base_url: str, story: dict, reviewer: str, version: int) -> None:
    notify(f"📝 *Spec v{version} 待審查* — <{_card_url(base_url, story)}|#{story.get('ref')} "
           f"{story.get('subject', '')}>\n@{reviewer} 請至看板審查並核准（拖至 Dev）。")


def loop_converged(base_url: str, story: dict, run_id: str, artifact: str | None) -> None:
    notify(f"✅ *Loop 收斂，PR 待人工審查* — <{_card_url(base_url, story)}|#{story.get('ref')} "
           f"{story.get('subject', '')}>\nrun `{run_id}`"
           + (f" · artifact: `{artifact}`" if artifact else ""))


def loop_escalated(base_url: str, story: dict, run_id: str, reason: str) -> None:
    notify(f"🚨 *Loop 升級處理，需要人工介入* — <{_card_url(base_url, story)}|#{story.get('ref')} "
           f"{story.get('subject', '')}>\nrun `{run_id}` · {reason[:200]}")
