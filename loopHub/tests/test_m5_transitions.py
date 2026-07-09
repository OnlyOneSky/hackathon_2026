from dataclasses import dataclass, field

import pytest

from hub.events import StatusChange
from hub.transitions import (Bounce, EnqueueRun, EnqueueSpec, Ignore, decide)

NAMES = {
    "backlog": "Backlog", "spec_drafting": "Spec Drafting",
    "spec_review": "Spec Review", "dev": "Dev",
    "pr_done": "PR-Done", "done": "Done",
}

SPEC = """---
story: bankapp#7
spec_version: 1
generated: 2026-07-09T12:00:00Z
---
# Feature: limit

## Acceptance criteria
- AC-1: ok
"""


@dataclass
class FakeCtx:
    active: bool = False
    repos: list[str] | None = field(default_factory=lambda: ["bankapp"])
    repo: str | None = "bankapp"
    feedback: bool = True

    def has_active_job(self, story_id):
        return self.active

    def team_repos(self, project_id):
        return self.repos

    def repo_of(self, ev):
        return self.repo

    def has_new_feedback(self, ev):
        return self.feedback


def ev(frm, to, description=SPEC):
    return StatusChange(story_id=42, story_ref=7, project_id=1, subject="s",
                        description=description, version=1, from_status=frm,
                        to_status=to, custom_attributes={}, raw={})


def test_move1_enqueues_spec():
    a = decide(ev("Backlog", "Spec Drafting"), NAMES, FakeCtx())
    assert isinstance(a, EnqueueSpec) and not a.regenerate


def test_move1_missing_repo_bounces():
    a = decide(ev("Backlog", "Spec Drafting"), NAMES, FakeCtx(repo=None))
    assert isinstance(a, Bounce) and a.to_role == "backlog" and "repo" in a.comment


def test_move1_unregistered_repo_lists_choices():
    a = decide(ev("Backlog", "Spec Drafting"), NAMES, FakeCtx(repo="evil"))
    assert isinstance(a, Bounce) and "bankapp" in a.comment


def test_reentry_guard_drops_duplicate():
    a = decide(ev("Backlog", "Spec Drafting"), NAMES, FakeCtx(active=True))
    assert isinstance(a, Ignore) and "re-entry" in a.reason


def test_move3_approval_snapshots_signed_description():
    a = decide(ev("Spec Review", "Dev"), NAMES, FakeCtx())
    assert isinstance(a, EnqueueRun)
    assert a.spec_snapshot == SPEC and a.repo_name == "bankapp"


def test_move3_blocked_by_open_questions():
    spec = SPEC + "\n## Open questions\n- 含手續費嗎？\n"
    a = decide(ev("Spec Review", "Dev", description=spec), NAMES, FakeCtx())
    assert isinstance(a, Bounce) and "Open questions" in a.comment


def test_move4_requires_feedback():
    a = decide(ev("Spec Review", "Spec Drafting"), NAMES, FakeCtx(feedback=False))
    assert isinstance(a, Bounce) and "回饋" in a.comment


def test_move4_with_feedback_regenerates():
    a = decide(ev("Spec Review", "Spec Drafting"), NAMES, FakeCtx(feedback=True))
    assert isinstance(a, EnqueueSpec) and a.regenerate


def test_illegal_move_bounced_to_source():
    a = decide(ev("Backlog", "Dev"), NAMES, FakeCtx())
    assert isinstance(a, Bounce) and a.to_role == "backlog" and "非法" in a.comment


@pytest.mark.parametrize("frm,to", [
    ("Spec Drafting", "Spec Review"),   # move 2 (agent)
    ("Spec Review", "Backlog"),         # move 5
    ("Dev", "PR-Done"),                 # move 6
    ("Dev", "Spec Review"),             # move 7
    ("PR-Done", "Spec Review"),         # move 8
    ("PR-Done", "Done"),                # merge
])
def test_passive_moves_need_no_action(frm, to):
    assert isinstance(decide(ev(frm, to), NAMES, FakeCtx()), Ignore)


def test_unknown_column_ignored():
    assert isinstance(decide(ev("Backlog", "Mystery"), NAMES, FakeCtx()), Ignore)
