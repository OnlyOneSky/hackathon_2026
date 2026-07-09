"""loop-hub FastAPI app.

M2 scope: verify signature, filter events, resolve status names→ids at
startup, enqueue jobs, log-only workers. Agent/loop workers arrive in M4/M6.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response

from . import config as config_mod
from .events import parse
from .queue import JobQueue
from .security import verify_signature

log = logging.getLogger("loop-hub")

# job types
SPEC_DRAFT = "spec_draft"
LOOP_RUN = "loop_run"


def resolve_status_ids(cfg: config_mod.Config) -> dict[int, dict[str, int]]:
    """For each registered project: display name (as configured) -> status id.

    Fails loudly if any configured column name is missing in a project —
    a renamed column must break startup, not silently drop events.
    """
    client = httpx.Client(
        base_url=cfg.taiga_base_url,
        headers={"Authorization": f"Bearer {cfg.taiga_token}"},
        timeout=10,
    )
    out: dict[int, dict[str, int]] = {}
    for team in cfg.teams.values():
        r = client.get("/api/v1/userstory-statuses", params={"project": team.taiga_project})
        r.raise_for_status()
        by_name = {s["name"]: s["id"] for s in r.json()}
        missing = [n for n in cfg.status_names.values() if n not in by_name]
        if missing:
            raise RuntimeError(
                f"project {team.taiga_project} ({team.name}) is missing status "
                f"column(s) {missing}; found {sorted(by_name)}"
            )
        out[team.taiga_project] = {role: by_name[name] for role, name in cfg.status_names.items()}
    return out


def log_worker(queue: JobQueue, job_type: str, stop: threading.Event) -> None:
    """M2 placeholder worker: claims jobs and logs them."""
    while not stop.is_set():
        job = queue.claim(job_type)
        if job is None:
            time.sleep(0.5)
            continue
        log.info("worker[%s] claimed job %s: story=%s payload=%s",
                 job_type, job["id"], job["story_id"], job["payload"])
        queue.finish(job["id"], ok=True)


def create_app(cfg: config_mod.Config | None = None, resolve_statuses: bool = True) -> FastAPI:
    cfg = cfg or config_mod.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if resolve_statuses:
            app.state.status_ids = resolve_status_ids(cfg)
            log.info("resolved status ids: %s", app.state.status_ids)
        stop = threading.Event()
        for jt in (SPEC_DRAFT, LOOP_RUN):
            threading.Thread(target=log_worker, args=(app.state.queue, jt, stop),
                             daemon=True, name=f"worker-{jt}").start()
        yield
        stop.set()

    app = FastAPI(title="loop-hub", lifespan=lifespan)
    app.state.cfg = cfg
    app.state.queue = JobQueue(cfg.queue_db_path)
    app.state.status_ids = {}

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

        import json
        try:
            payload = json.loads(raw)
        except ValueError:
            return Response(status_code=400)

        ev = parse(payload)
        if ev is None:
            return {"ignored": True}

        names = cfg.status_names
        log.info("status change: story #%s %r %s -> %s (project %s)",
                 ev.story_ref, ev.subject, ev.from_status, ev.to_status, ev.project_id)

        if ev.to_status == names["spec_drafting"]:
            job_id = app.state.queue.enqueue(SPEC_DRAFT, ev.story_id, {"event": ev.raw})
            if job_id is None:
                log.info("duplicate spec_draft for story %s dropped (re-entry guard)", ev.story_id)
                return {"enqueued": False, "reason": "duplicate"}
            return {"enqueued": True, "job_id": job_id, "job_type": SPEC_DRAFT}

        if ev.from_status == names["spec_review"] and ev.to_status == names["dev"]:
            job_id = app.state.queue.enqueue(LOOP_RUN, ev.story_id, {"event": ev.raw})
            if job_id is None:
                log.info("duplicate loop_run for story %s dropped (re-entry guard)", ev.story_id)
                return {"enqueued": False, "reason": "duplicate"}
            return {"enqueued": True, "job_id": job_id, "job_type": LOOP_RUN}

        return {"ignored": True, "reason": "transition not handled in M2"}

    return app
