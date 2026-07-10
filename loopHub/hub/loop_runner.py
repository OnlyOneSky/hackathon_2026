"""Loop runner worker (M6) + outcome write-backs (M7).

Review→Dev approval → frozen runs/<run-id>/spec.md (snapshot from the signed
webhook payload) → subprocess `python -m loopengine run` → board write-back:
converge → PR-Done + artifact comment; escalate → Spec Review + failure report.
The loop itself needs zero changes.
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .queue import JobQueue
from .taiga import TaigaClient

log = logging.getLogger("loop-hub")

LOOPENGINE_ROOT = Path(
    "/Users/jeffchen/Workspace/Projects/Hackathon 2026/loopEngineer")
HUB_RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
RUN_TIMEOUT_S = 45 * 60


def run_loop_for_job(cfg: Config, taiga: TaigaClient,
                     status_ids: dict[int, dict[str, int]],
                     story_id: int, payload: dict) -> None:
    project_id = payload["project_id"]
    repo_name = payload["repo"]
    team = cfg.team_for_project(project_id)
    repo_path = Path(team.repos[repo_name].url)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    run_dir = HUB_RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    spec_file = run_dir / "spec.md"
    spec_file.write_text(payload["spec_snapshot"])       # guardrail 1: frozen input

    ids = status_ids[project_id]
    taiga.comment(story_id, f"🚀 已核准，開始執行 agentic loop（run `{run_id}`，repo `{repo_name}`）。")

    log.info("loop_run %s: story %s repo=%s", run_id, story_id, repo_path)
    engine_runs = LOOPENGINE_ROOT / "runs"
    before = {p.name for p in engine_runs.iterdir()} if engine_runs.is_dir() else set()
    # the repo's loop.toml may pick gate synthesis (test author writes the gate)
    gate_mode = "provided"
    loop_toml = repo_path / "loop.toml"
    if loop_toml.is_file():
        import tomllib
        try:
            gate_mode = tomllib.loads(loop_toml.read_text()).get("gate", {}) \
                                .get("gate_mode", "provided")
        except tomllib.TOMLDecodeError:
            pass
    try:
        proc = subprocess.run(
            ["python3", "-m", "loopengine", "run",
             "--spec", str(spec_file), "--repo", str(repo_path), "--agent", "claude",
             "--gate", gate_mode],
            cwd=LOOPENGINE_ROOT, capture_output=True, text=True, timeout=RUN_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        taiga.move_with_comment(story_id, ids["spec_review"],
                                f"⏱️ run `{run_id}` 超過時間上限，已中止。請檢視規格後重新核准。")
        return

    (run_dir / "stdout.log").write_text(proc.stdout)
    (run_dir / "stderr.log").write_text(proc.stderr)

    state = _load_state(engine_runs, before)
    status = (state or {}).get("status", "converged" if proc.returncode == 0 else "escalated")
    result = (state or {}).get("result") or {}
    artifact = result.get("artifact")
    outcome = result.get("outcome", "")

    if status == "converged":
        # move ⑥: Dev → PR-Done with the PR artifact on the card
        comment = (f"✅ Loop 收斂（run `{run_id}`）。\n\n"
                   f"**Outcome:** {outcome or 'converged'}\n"
                   + (f"**PR artifact:** `{artifact}`\n" if artifact else "")
                   + f"**Run record:** `{run_dir}`")
        taiga.move_with_comment(story_id, ids["pr_done"], comment)
        log.info("loop_run %s converged; story %s -> PR-Done", run_id, story_id)
        from .slack import loop_converged
        loop_converged(cfg.taiga_base_url, taiga.get_story(story_id), run_id, artifact)
    else:
        # move ⑦: Dev → Spec Review with the failure report
        tail = proc.stdout[-1500:]
        comment = (f"🛑 Loop 升級處理（run `{run_id}`，status: {status}）。\n\n"
                   f"**Failure report:** {outcome or '(見 run record)'}\n"
                   f"**Run record:** `{run_dir}`\n\n```\n{tail}\n```")
        taiga.move_with_comment(story_id, ids["spec_review"], comment)
        log.info("loop_run %s escalated; story %s -> Spec Review", run_id, story_id)
        from .slack import loop_escalated
        loop_escalated(cfg.taiga_base_url, taiga.get_story(story_id), run_id,
                       outcome or status)


def _load_state(engine_runs: Path, before: set[str]) -> dict | None:
    """The run record loopengine just created (newest dir not present before)."""
    if not engine_runs.is_dir():
        return None
    new = [p for p in engine_runs.iterdir() if p.name not in before]
    for p in sorted(new, key=lambda p: p.name, reverse=True):
        f = p / "state.json"
        if f.is_file():
            try:
                return json.loads(f.read_text())
            except ValueError:
                pass
    return None


def loop_run_worker(cfg: Config, queue: JobQueue, taiga: TaigaClient,
                    status_ids: dict[int, dict[str, int]],
                    stop: threading.Event) -> None:
    """Single worker thread — runs serialize globally (fine at demo scale)."""
    while not stop.is_set():
        job = queue.claim("loop_run")
        if job is None:
            time.sleep(0.5)
            continue
        try:
            run_loop_for_job(cfg, taiga, status_ids, job["story_id"], job["payload"])
            queue.finish(job["id"], ok=True)
        except Exception as e:                            # noqa: BLE001
            log.exception("loop_run job %s failed", job["id"])
            try:
                ids = status_ids[job["payload"]["project_id"]]
                taiga.move_with_comment(job["story_id"], ids["spec_review"],
                                        f"🛑 Loop 執行失敗：{e}")
            except Exception:                             # noqa: BLE001
                log.exception("write-back failed for job %s", job["id"])
            queue.finish(job["id"], ok=False, error=str(e))
