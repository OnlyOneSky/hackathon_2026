"""loop-hub FastAPI app.

Webhook → verify signature → parse event → transitions.decide() → side effects
(enqueue job / bounce card / ignore). Workers do the slow Taiga/LLM/loop work.
A 60 s poller reconciles missed events (GET fallback path only).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response

from . import config as config_mod
from . import transitions
from .events import StatusChange, parse
from .queue import JobQueue
from .security import verify_signature
from .taiga import TaigaClient
from .workers import spec_draft_worker

log = logging.getLogger("loop-hub")

# job types
SPEC_DRAFT = "spec_draft"
LOOP_RUN = "loop_run"

DEFAULT_CONSTITUTION = Path(
    "/Users/jeffchen/Workspace/Projects/Hackathon 2026/loopEngineer/skills/constitution.md")
REVIEWER = "admin"      # demo: 阿哲 is the admin account
BOT_USERNAME = "loop-bot"


def resolve_status_ids(cfg: config_mod.Config) -> dict[int, dict[str, int]]:
    """Per project: role -> status id. Fails loudly on renamed columns."""
    client = httpx.Client(base_url=cfg.taiga_base_url,
                          headers={"Authorization": f"Bearer {cfg.taiga_token}"},
                          timeout=10)
    out: dict[int, dict[str, int]] = {}
    for team in cfg.teams.values():
        r = client.get("/api/v1/userstory-statuses", params={"project": team.taiga_project})
        r.raise_for_status()
        by_name = {s["name"]: s["id"] for s in r.json()}
        missing = [n for n in cfg.status_names.values() if n not in by_name]
        if missing:
            raise RuntimeError(
                f"project {team.taiga_project} ({team.name}) is missing status "
                f"column(s) {missing}; found {sorted(by_name)}")
        out[team.taiga_project] = {role: by_name[name]
                                   for role, name in cfg.status_names.items()}
    return out


def resolve_repo_attr_ids(cfg: config_mod.Config) -> dict[int, int]:
    """Per project: id of the required `repo` custom attribute."""
    client = httpx.Client(base_url=cfg.taiga_base_url,
                          headers={"Authorization": f"Bearer {cfg.taiga_token}"},
                          timeout=10)
    out: dict[int, int] = {}
    for team in cfg.teams.values():
        r = client.get("/api/v1/userstory-custom-attributes",
                       params={"project": team.taiga_project})
        r.raise_for_status()
        for a in r.json():
            if a["name"] == "repo":
                out[team.taiga_project] = a["id"]
                break
        else:
            raise RuntimeError(f"project {team.taiga_project} has no `repo` custom attribute")
    return out


class HubContext:
    """transitions.Context backed by the queue + Taiga API."""

    def __init__(self, cfg: config_mod.Config, queue: JobQueue,
                 taiga: TaigaClient, attr_ids: dict[int, int]):
        self.cfg, self.queue, self.taiga, self.attr_ids = cfg, queue, taiga, attr_ids

    def has_active_job(self, story_id: int) -> bool:
        return self.queue.has_active(story_id)

    def team_repos(self, project_id: int) -> list[str] | None:
        team = self.cfg.team_for_project(project_id)
        return sorted(team.repos) if team else None

    def repo_of(self, ev: StatusChange) -> str | None:
        # Webhook payloads key custom attrs inconsistently across versions —
        # read via API (cheap GET; not the approval snapshot, so TOCTOU-safe).
        from .workers import extract_repo
        return extract_repo(self.taiga, self.cfg, ev.project_id, ev.story_id,
                            self.attr_ids)

    def _human_comments_since_spec(self, ev: StatusChange) -> list[str]:
        """Guardrail 4 source: comments newer than the spec's `generated` ts,
        excluding loop-hub's own write-backs (they are not reviewer feedback)."""
        m = re.search(r"^generated:\s*(\S+)", ev.description, re.MULTILINE)
        generated = m.group(1) if m else ""
        r = self.taiga.c.get(f"/api/v1/history/userstory/{ev.story_id}")
        if r.status_code != 200:
            return []
        return [e["comment"] for e in r.json()
                if e.get("comment")
                and (e.get("user") or {}).get("username") != BOT_USERNAME
                and (not generated or e["created_at"] > generated)]

    def has_new_feedback(self, ev: StatusChange) -> bool:
        return bool(self._human_comments_since_spec(ev))

    def feedback_comments(self, ev: StatusChange) -> list[str]:
        return self._human_comments_since_spec(ev)


def log_worker(queue: JobQueue, job_type: str, stop: threading.Event) -> None:
    """Placeholder worker (loop_run until M6)."""
    while not stop.is_set():
        job = queue.claim(job_type)
        if job is None:
            time.sleep(0.5)
            continue
        log.info("worker[%s] claimed job %s: story=%s", job_type, job["id"], job["story_id"])
        queue.finish(job["id"], ok=True)


def reconciliation_poller(app_state, cfg: config_mod.Config, stop: threading.Event,
                          interval: float = 60.0) -> None:
    """Any card sitting in Spec Drafting with no draft marker and no active job
    gets enqueued (idempotent; GET fallback path)."""
    while not stop.is_set():
        stop.wait(interval)
        if stop.is_set():
            return
        try:
            taiga: TaigaClient = app_state.taiga
            for team in cfg.teams.values():
                drafting_id = app_state.status_ids[team.taiga_project]["spec_drafting"]
                r = taiga.c.get("/api/v1/userstories",
                                params={"project": team.taiga_project,
                                        "status": drafting_id})
                if r.status_code != 200:
                    log.warning("poller: story list failed (%s) for project %s",
                                r.status_code, team.taiga_project)
                    continue
                for us in r.json():
                    story = taiga.get_story(us["id"])   # GET fallback (no payload in hand)
                    if story["description"].startswith("---"):
                        continue                        # draft marker present
                    if app_state.queue.enqueue(SPEC_DRAFT, us["id"], {"poller": True}):
                        log.info("poller: re-enqueued story %s stuck in Spec Drafting", us["id"])
        except Exception:                                # noqa: BLE001
            log.exception("poller iteration failed")


def create_app(cfg: config_mod.Config | None = None, resolve_statuses: bool = True,
               llm=None) -> FastAPI:
    cfg = cfg or config_mod.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = threading.Event()
        if resolve_statuses:
            app.state.status_ids = resolve_status_ids(cfg)
            app.state.attr_ids = resolve_repo_attr_ids(cfg)
            log.info("resolved status ids: %s", app.state.status_ids)
            app.state.taiga = TaigaClient(cfg.taiga_base_url, cfg.taiga_token)
            app.state.ctx = HubContext(cfg, app.state.queue, app.state.taiga,
                                       app.state.attr_ids)
            threading.Thread(
                target=spec_draft_worker,
                args=(cfg, app.state.queue, app.state.taiga, app.state.status_ids,
                      app.state.attr_ids, DEFAULT_CONSTITUTION, REVIEWER, stop),
                kwargs={"llm": llm}, daemon=True, name="worker-spec").start()
            threading.Thread(target=reconciliation_poller,
                             args=(app.state, cfg, stop),
                             daemon=True, name="poller").start()
            from .loop_runner import loop_run_worker
            threading.Thread(
                target=loop_run_worker,
                args=(cfg, app.state.queue, app.state.taiga, app.state.status_ids, stop),
                daemon=True, name="worker-loop").start()
        else:
            threading.Thread(target=log_worker, args=(app.state.queue, LOOP_RUN, stop),
                             daemon=True, name="worker-loop").start()
        yield
        stop.set()

    app = FastAPI(title="loop-hub", lifespan=lifespan)
    app.state.cfg = cfg
    app.state.queue = JobQueue(cfg.queue_db_path)
    app.state.status_ids = {}
    app.state.ctx = None

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/webhooks/taiga")
    async def taiga_webhook(request: Request):
        raw = await request.body()
        sig = request.headers.get("x-taiga-webhook-signature", "")
        if not verify_signature(raw, cfg.webhook_secret, sig):
            log.warning("webhook rejected: bad signature")
            return Response(status_code=403)
        try:
            payload = json.loads(raw)
        except ValueError:
            return Response(status_code=400)

        ev = parse(payload)
        if ev is None:
            return {"ignored": True}
        if ev.by_username == BOT_USERNAME:
            # Our own write-backs (bounces, auto-moves) must never re-enter
            # the state machine — that way lies infinite bounce loops.
            return {"ignored": True, "reason": "own action"}
        log.info("status change: story #%s %r %s -> %s (project %s)",
                 ev.story_ref, ev.subject, ev.from_status, ev.to_status, ev.project_id)

        ctx = app.state.ctx
        if ctx is None:                                  # unit-test mode
            return {"ignored": True, "reason": "no context (test mode)"}

        action = transitions.decide(ev, cfg.status_names, ctx)
        return apply_action(app, ev, action, ctx)

    return app


def apply_action(app: FastAPI, ev: StatusChange, action: transitions.Action,
                 ctx: HubContext) -> dict:
    if isinstance(action, transitions.Ignore):
        log.info("ignore: %s", action.reason)
        return {"ignored": True, "reason": action.reason}

    if isinstance(action, transitions.Bounce):
        status_id = app.state.status_ids[ev.project_id][action.to_role]
        try:
            app.state.taiga.move_with_comment(action.story_id, status_id, action.comment)
            log.info("bounced story %s -> %s: %s", action.story_id, action.to_role,
                     action.comment)
        except Exception:                                # noqa: BLE001
            log.exception("bounce failed for story %s", action.story_id)
        return {"bounced": True, "to": action.to_role}

    if isinstance(action, transitions.EnqueueSpec):
        payload = {"regenerate": action.regenerate}
        if action.regenerate:
            payload["feedback"] = ctx.feedback_comments(ev)
        job_id = app.state.queue.enqueue(SPEC_DRAFT, action.story_id, payload)
        if job_id is None:
            return {"enqueued": False, "reason": "duplicate"}
        return {"enqueued": True, "job_id": job_id, "job_type": SPEC_DRAFT}

    if isinstance(action, transitions.EnqueueRun):
        job_id = app.state.queue.enqueue(LOOP_RUN, action.story_id, {
            "spec_snapshot": action.spec_snapshot,       # from the SIGNED payload
            "repo": action.repo_name,
            "project_id": ev.project_id,
        })
        if job_id is None:
            return {"enqueued": False, "reason": "duplicate"}
        return {"enqueued": True, "job_id": job_id, "job_type": LOOP_RUN}

    raise AssertionError(f"unhandled action {action!r}")
