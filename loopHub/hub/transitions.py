"""Board state machine + guardrails (kanban design doc: 8 moves, 5 guardrails).

Pure decision logic: given a StatusChange and a context of predicates, return
the action loop-hub must take. Side effects (Taiga writes, queueing) live in
app.py; this module is fully unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .events import StatusChange
from .spec_agent import has_open_questions

# roles as used in config.status_names
BACKLOG, DRAFTING, REVIEW, DEV, PR_DONE, DONE = (
    "backlog", "spec_drafting", "spec_review", "dev", "pr_done", "done")

# Legal transitions (from_role, to_role) → move number in the design doc.
LEGAL_MOVES: dict[tuple[str, str], int] = {
    (BACKLOG, DRAFTING): 1,
    (DRAFTING, REVIEW): 2,
    (REVIEW, DEV): 3,
    (REVIEW, DRAFTING): 4,
    (REVIEW, BACKLOG): 5,
    (DEV, PR_DONE): 6,
    (DEV, REVIEW): 7,
    (PR_DONE, REVIEW): 8,
    (PR_DONE, DONE): 9,   # merge → Done (infra doc §2)
}


@dataclass
class EnqueueSpec:
    story_id: int
    spec_version: int = 1
    regenerate: bool = False


@dataclass
class EnqueueRun:
    story_id: int
    spec_snapshot: str      # data.description from the SIGNED payload (guardrail 1)
    repo_name: str


@dataclass
class Bounce:
    story_id: int
    to_role: str
    comment: str


@dataclass
class Ignore:
    reason: str


Action = EnqueueSpec | EnqueueRun | Bounce | Ignore


class Context(Protocol):
    def has_active_job(self, story_id: int) -> bool: ...
    def team_repos(self, project_id: int) -> list[str] | None: ...   # None = unknown project
    def repo_of(self, ev: StatusChange) -> str | None: ...
    def has_new_feedback(self, ev: StatusChange) -> bool: ...


def role_of(name: str, status_names: dict[str, str]) -> str | None:
    for role, display in status_names.items():
        if display == name:
            return role
    return None


def decide(ev: StatusChange, status_names: dict[str, str], ctx: Context) -> Action:
    frm = role_of(ev.from_status, status_names)
    to = role_of(ev.to_status, status_names)
    if frm is None or to is None:
        return Ignore(f"unknown column {ev.from_status!r} -> {ev.to_status!r}")
    if frm == to:
        return Ignore("no-op move")

    move = LEGAL_MOVES.get((frm, to))
    if move is None:
        # Guardrail 2: illegal move — bounce back to source with explanation
        return Bounce(ev.story_id, frm,
                      f"⛔ 非法移動：{ev.from_status} → {ev.to_status} 不在流程中，"
                      f"卡片已退回 {ev.from_status}。")

    if move == 1 or move == 4:
        # into Spec Drafting — guardrail: repo must be registered (move ①)
        repos = ctx.team_repos(ev.project_id)
        if repos is None:
            return Bounce(ev.story_id, frm,
                          "⛔ 此專案未註冊任何 repo，請聯絡管理員設定 repos.toml。")
        repo = ctx.repo_of(ev)
        if repo not in repos:
            return Bounce(ev.story_id, frm,
                          f"⛔ `repo` 欄位缺漏或未註冊（目前值：{repo!r}）。"
                          f"本團隊可選：{', '.join(sorted(repos))}。")
        # Guardrail 5: one active job per card
        if ctx.has_active_job(ev.story_id):
            return Ignore(f"re-entry guard: story {ev.story_id} already has an active job")
        if move == 4:
            # Guardrail 4: regenerate requires fresh feedback
            if not ctx.has_new_feedback(ev):
                return Bounce(ev.story_id, frm,
                              "📝 重新產生規格前，請先在卡片留下回饋意見"
                              "（說明上一版哪裡不對），再移動卡片。")
            return EnqueueSpec(ev.story_id, regenerate=True)
        return EnqueueSpec(ev.story_id)

    if move == 3:
        # The approval. Block if Open questions survive (design doc rule).
        if has_open_questions(ev.description):
            return Bounce(ev.story_id, REVIEW,
                          "⛔ 規格仍有 Open questions 未解決。"
                          "請回覆並刪除該段後再核准。")
        if ctx.has_active_job(ev.story_id):
            return Ignore(f"re-entry guard: story {ev.story_id} already has an active run")
        repos = ctx.team_repos(ev.project_id) or []
        repo = ctx.repo_of(ev)
        if repo not in repos:
            return Bounce(ev.story_id, REVIEW,
                          f"⛔ `repo` 欄位缺漏或未註冊（目前值：{repo!r}）。")
        # Guardrail 1: snapshot from the signed payload, never a later GET
        return EnqueueRun(ev.story_id, spec_snapshot=ev.description, repo_name=repo)

    # moves 2, 5, 6, 7, 8, 9 need no hub-triggered work on the webhook itself
    return Ignore(f"move {move} needs no action")
