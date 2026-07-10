"""Job workers: spec drafting (M4) and loop runs (M6).

Each worker claims jobs from the SQLite queue and performs the Taiga
write-backs. Workers never raise: failures land on the card as a comment
(spec) or are logged (until M7 adds escalate write-backs).
"""
from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path

from .config import Config
from .queue import JobQueue
from .spec_agent import ValidationError, draft_spec
from .taiga import TaigaClient

log = logging.getLogger("loop-hub")


def resolve_constitution(cfg: Config, project_id: int, repo_name: str,
                         default_path: Path) -> str:
    """Repo-local constitution.md wins over the skills default (loop precedence)."""
    team = cfg.team_for_project(project_id)
    if team and repo_name in team.repos:
        repo_file = Path(team.repos[repo_name].url) / "constitution.md"
        if repo_file.is_file():
            return repo_file.read_text()
    return default_path.read_text()


def extract_repo(taiga: TaigaClient, cfg: Config, project_id: int,
                 story_id: int, attr_ids: dict[int, int]) -> str | None:
    """Read the `repo` custom attribute via the API (webhook payload keys vary)."""
    attr_id = attr_ids.get(project_id)
    if attr_id is None:
        return None
    r = taiga.c.get(f"/api/v1/userstories/custom-attributes-values/{story_id}")
    if r.status_code != 200:
        return None
    values = r.json().get("attributes_values") or {}
    v = values.get(str(attr_id)) or values.get(attr_id)
    return v.strip() if isinstance(v, str) and v.strip() else None


def current_spec_version(description: str) -> int:
    m = re.search(r"^spec_version:\s*(\d+)", description, re.MULTILINE)
    return int(m.group(1)) if m else 0


def spec_draft_worker(cfg: Config, queue: JobQueue, taiga: TaigaClient,
                      status_ids: dict[int, dict[str, int]],
                      attr_ids: dict[int, int],
                      default_constitution: Path,
                      reviewer: str,
                      stop: threading.Event,
                      llm=None) -> None:
    from .spec_agent import call_llm
    llm = llm or call_llm
    while not stop.is_set():
        job = queue.claim("spec_draft")
        if job is None:
            time.sleep(0.5)
            continue
        story_id = job["story_id"]
        try:
            story = taiga.get_story(story_id)
            project_id = story["project"]
            repo = extract_repo(taiga, cfg, project_id, story_id, attr_ids)
            constitution = resolve_constitution(cfg, project_id, repo or "",
                                                default_constitution)
            regenerate = bool(job["payload"].get("regenerate"))
            prev_spec = story["description"] if regenerate else None
            version = current_spec_version(story["description"]) + 1 if regenerate else 1
            feedback = job["payload"].get("feedback") or []

            log.info("spec_draft: story %s repo=%s v%s regenerate=%s",
                     story_id, repo, version, regenerate)
            spec = draft_spec(
                subject=story["subject"],
                description=story["description"],
                constitution_md=constitution,
                story_ref=f"{repo or 'unknown'}#{story['ref']}",
                spec_version=version,
                previous_spec=prev_spec,
                feedback_comments=feedback,
                llm=llm,
            )
            review_id = status_ids[project_id]["spec_review"]
            taiga.write_spec_and_move(story_id, spec, review_id, reviewer, version)
            log.info("spec_draft: story %s spec v%s written, moved to Spec Review",
                     story_id, version)
            from .slack import spec_ready
            spec_ready(cfg.taiga_base_url, story, reviewer, version, cfg.slack_users)
            queue.finish(job["id"], ok=True)
        except ValidationError as e:
            msg = f"🤖 規格產生失敗（驗證未通過）：{e}。卡片留在 Spec Drafting，請人工處理。"
            _safe_comment(taiga, story_id, msg)
            queue.finish(job["id"], ok=False, error=str(e))
        except Exception as e:                                    # noqa: BLE001
            log.exception("spec_draft: story %s failed", story_id)
            _safe_comment(taiga, story_id, f"🤖 規格產生失敗：{e}")
            queue.finish(job["id"], ok=False, error=str(e))


def _safe_comment(taiga: TaigaClient, story_id: int, text: str) -> None:
    try:
        taiga.comment(story_id, text)
    except Exception:                                             # noqa: BLE001
        log.exception("could not comment on story %s", story_id)
