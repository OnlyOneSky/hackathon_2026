import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from hub.app import create_app
from hub.config import Config, RepoEntry, Team
from hub.events import parse
from hub.queue import JobQueue
from hub.security import verify_signature

SECRET = "test-secret"


def make_cfg(tmp_path) -> Config:
    return Config(
        taiga_base_url="http://localhost:9000",
        status_names={
            "backlog": "Backlog", "spec_drafting": "Spec Drafting",
            "spec_review": "Spec Review", "dev": "Dev",
            "pr_done": "PR-Done", "done": "Done",
        },
        port=8400,
        queue_db_path=str(tmp_path / "q.sqlite3"),
        webhook_secret=SECRET,
        taiga_token="t",
        teams={"payments": Team("payments", 1, {"bankapp": RepoEntry("bankapp", "/tmp/bankapp", "main")})},
    )


def story_move(from_status: str, to_status: str, story_id: int = 42) -> dict:
    return {
        "action": "change",
        "type": "userstory",
        "change": {"diff": {"status": {"from": from_status, "to": to_status}}},
        "data": {
            "id": story_id, "ref": 7, "version": 3,
            "subject": "轉帳要有單日累計限額",
            "description": "## 故事（必填）...",
            "project": {"id": 1},
            "custom_attributes_values": {"repo": "bankapp"},
        },
    }


def signed_post(client, payload: dict, secret: str = SECRET):
    raw = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha1).hexdigest()
    return client.post("/webhooks/taiga", content=raw,
                       headers={"x-taiga-webhook-signature": sig,
                                "content-type": "application/json"})


# --- security ---

def test_signature_roundtrip():
    raw = b'{"a": 1}'
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha1).hexdigest()
    assert verify_signature(raw, SECRET, sig)
    assert not verify_signature(raw + b" ", SECRET, sig)   # raw body matters
    tampered = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    assert not verify_signature(raw, SECRET, tampered)
    assert not verify_signature(raw, "", sig)
    assert not verify_signature(raw, SECRET, "")


# --- event parsing ---

def test_parse_status_change():
    ev = parse(story_move("Backlog", "Spec Drafting"))
    assert ev is not None
    assert ev.story_id == 42 and ev.project_id == 1
    assert ev.from_status == "Backlog" and ev.to_status == "Spec Drafting"
    assert ev.custom_attributes["repo"] == "bankapp"


@pytest.mark.parametrize("payload", [
    {"action": "create", "type": "userstory", "data": {}},
    {"action": "change", "type": "task", "data": {}},
    {"action": "change", "type": "userstory",
     "change": {"diff": {"subject": {"from": "a", "to": "b"}}}, "data": {}},
])
def test_parse_ignores_other_events(payload):
    assert parse(payload) is None


# --- queue ---

def test_queue_reentry_guard(tmp_path):
    q = JobQueue(str(tmp_path / "q.sqlite3"))
    assert q.enqueue("spec_draft", 42, {"x": 1}) is not None
    assert q.enqueue("spec_draft", 42, {"x": 2}) is None      # active duplicate
    job = q.claim("spec_draft")
    assert job["story_id"] == 42 and job["payload"] == {"x": 1}
    assert q.enqueue("spec_draft", 42, {"x": 3}) is None      # still running
    q.finish(job["id"], ok=True)
    assert q.enqueue("spec_draft", 42, {"x": 4}) is not None  # done -> allowed


# --- webhook endpoint ---

@pytest.fixture
def client(tmp_path):
    app = create_app(make_cfg(tmp_path), resolve_statuses=False)
    with TestClient(app) as c:
        yield c


def test_tampered_signature_403(client):
    r = signed_post(client, story_move("Backlog", "Spec Drafting"), secret="wrong")
    assert r.status_code == 403


def test_valid_signature_accepted(client):
    r = signed_post(client, story_move("Backlog", "Spec Drafting"))
    assert r.status_code == 200


def test_non_status_event_ignored(client):
    payload = {"action": "create", "type": "userstory", "data": {}}
    r = signed_post(client, payload)
    assert r.json() == {"ignored": True}
