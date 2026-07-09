"""M3 standalone connector check — run against a scratch card BEFORE wiring agents.

Usage (from loopHub/):
    LOOPHUB_TAIGA_TOKEN=<loop-bot token> uv run python scripts/m3_connector_check.py <story_id>

Done when: the script writes a description, moves the card, and comments.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hub import config as config_mod
from hub.app import resolve_status_ids
from hub.taiga import TaigaClient


def main() -> None:
    story_id = int(sys.argv[1])
    cfg = config_mod.load()
    assert cfg.taiga_token, "set LOOPHUB_TAIGA_TOKEN"
    t = TaigaClient(cfg.taiga_base_url, cfg.taiga_token)

    story = t.get_story(story_id)
    project_id = story["project"]
    print(f"[1/3] get_story ok: #{story['ref']} {story['subject']!r} "
          f"v{story['version']} project={project_id}")

    ids = resolve_status_ids(cfg)[project_id]

    updated = t.write_spec_and_move(
        story_id,
        "# Feature: M3 connector check\n\n(scratch write — safe to delete)",
        ids["spec_review"], reviewer="jeffchen", spec_version=1)
    print(f"[2/3] write_spec_and_move ok: now v{updated['version']}, "
          f"status id {updated['status']}")

    bounced = t.move_with_comment(
        story_id, ids["backlog"],
        "M3 check: bounce-with-comment works — card returned to Backlog.")
    print(f"[3/3] bounce ok: now v{bounced['version']}. M3 done-when satisfied.")


if __name__ == "__main__":
    main()
